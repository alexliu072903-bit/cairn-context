#!/usr/bin/env python3
"""Read the decisions of a Cairn repository as JSON.

Usage:
  read.py [REPOSITORY] [--project ID ...] [--since YYYY-MM-DD] [--status LIST]

This is the reference reader. Other programs (an app, a web service, a script)
should either call it or reproduce its output; tests/conformance/ holds the
fixtures both must agree on. Generated paths are repository-relative. Decision
content is returned verbatim; review authored content before sharing it.

  --project ID      only this project; repeat for several. The output then names
                    only the requested projects, never the others in the repository.
  --since DATE      only decisions with decided_at on or after DATE
  --status LIST     comma-separated subset of valid,superseded,revoked

REPOSITORY defaults to the "repository" value in ~/.cairn/config.json (or the
file named by $CAIRN_CONFIG), then to the repository that contains this script.

Exit status: 0 on success (file-level problems are reported in the JSON, not by
the exit code), 1 when a requested project does not exist, 2 when the
repository cannot be read.

Only the Python standard library is used.
"""

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

SCHEMA_VERSION = 1
# 规范化后的章节键 -> 各语言标题；顺序即输出顺序。
SECTION_KEYS = (
    ("decision", ("Decision", "结论")),
    ("rationale", ("Rationale", "为什么")),
    ("scope", ("Scope", "适用范围")),
    ("excluded", ("Explicitly excluded", "明确不做")),
    ("overturn", ("Overturn signal", "推翻条件")),
)
TIMESTAMP = re.compile(r"^(\d{4}-\d{2}-\d{2})[T ]")


def load_validate():
    """Load the sibling validate.py so every script parses decisions the same way."""
    path = Path(__file__).resolve().with_name("validate.py")
    spec = importlib.util.spec_from_file_location("cairn_validate", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def split_sections(body):
    """Return (title or None, {heading: text}) for the Markdown body of a decision."""
    title = None
    sections = {}
    heading = None
    buffer = []
    for line in body.split("\n"):
        if line.startswith("## "):
            if heading is not None:
                sections[heading] = "\n".join(buffer).strip()
            heading = line[3:].strip()
            buffer = []
        elif line.startswith("# ") and title is None and heading is None:
            title = line[2:].strip()
        elif heading is not None:
            buffer.append(line)
    if heading is not None:
        sections[heading] = "\n".join(buffer).strip()
    return title, sections


def language_of(validate, headings):
    """Name the language whose section titles the file uses, or 'unknown'."""
    scores = {
        "en": sum(1 for h in validate.SECTION_SETS["English"] if h in headings),
        "zh": sum(1 for h in validate.SECTION_SETS["Chinese"] if h in headings),
    }
    best = max(scores, key=lambda name: scores[name])
    return best if scores[best] else "unknown"


def relative(path, root):
    """Use the logical path, never the resolved target of a link."""
    return path.relative_to(root).as_posix()


def is_link(path):
    # Path.is_junction was added in Python 3.12. Resolve also catches junctions
    # when running on earlier Windows versions.
    return path.is_symlink() or getattr(path, "is_junction", lambda: False)()


def safe_path(path, root):
    """Reject redirected components below the explicitly selected repository."""
    current = root
    try:
        for part in path.relative_to(root).parts:
            current = current / part
            if is_link(current) or current.resolve() != current:
                return False
    except (OSError, RuntimeError):
        return False
    return True


def diagnostic_message(item):
    """Do not echo input values or OS exceptions into an export's diagnostics."""
    message = item["message"]
    if message.startswith("status ") and " is not one of:" in message:
        return "status must be valid, superseded or revoked"
    for prefix, safe in (
        ("cannot read file", "cannot read decision file"),
        ("field project is", "project field does not match the selected project"),
        ("field decision is", "decision field does not match the file name"),
        ("frontmatter line", "frontmatter contains an invalid key/value line"),
        ("frontmatter key", "frontmatter contains a duplicate key"),
        ("decided_at ", "decided_at is not a date in YYYY-MM-DD form"),
        ("unknown frontmatter", "unknown frontmatter field"),
        ("supersedes chain", "supersedes chain contains a cycle"),
        ("supersedes ", "supersedes target is missing or still marked valid"),
        ("superseded_by ", "superseded_by target is missing or does not reciprocate supersedes"),
        ("replaced by more than one", "replaced by more than one decision"),
    ):
        if message.startswith(prefix):
            return safe
    # Remaining messages contain only fixed text or known field/section names.
    return message


def read_decision(validate, root, project_id, path, report):
    """Return the decision record for one file, or None when it cannot be trusted."""
    first_problem = len(report.items)
    parsed = validate.parse_decision(path, report)
    if parsed is not None:
        fields, body = parsed
        stamp = fields.get("decided_at", "")
        match = TIMESTAMP.match(stamp)
        if match:
            fields["decided_at"] = match.group(1)
            report.warning(path, "timestamp was reduced to its calendar date")
        validate.check_decision(path, project_id, fields, body, report)
    history = None
    if parsed is not None:
        history = {"id": path.stem, "path": path, "fields": fields}
    if parsed is None or any(p["level"] == "error" for p in report.items[first_problem:]):
        return None, history

    title, sections = split_sections(body)
    record = {
        "id": path.stem,
        "project": project_id,
        "title": title or path.stem,
        "status": fields["status"],
        "decided_by": fields["decided_by"],
        "decided_at": fields["decided_at"],
        "supersedes": fields.get("supersedes", []),
        "superseded_by": fields.get("superseded_by", []),
        "language": language_of(validate, list(sections)),
        "sections": {},
        "file": relative(path, root),
    }
    for key, names in SECTION_KEYS:
        record["sections"][key] = next((sections[n] for n in names if n in sections), "")
    return record, history


def read_repository(validate, root, projects=None, since=None, statuses=None):
    """Return (result dict, missing project ids). Raises FileNotFoundError without projects/."""
    root = root.resolve()
    projects_dir = root / "projects"
    if not safe_path(projects_dir, root) or not projects_dir.is_dir():
        raise FileNotFoundError("no readable projects/ directory found")
    available = sorted(
        p.name for p in projects_dir.iterdir()
        if not p.name.startswith("_") and (is_link(p) or p.is_dir())
    )
    wanted = list(dict.fromkeys(projects)) if projects else available
    missing = [name for name in wanted if name not in available]
    problems = []
    output = []
    for name in wanted:
        if name in missing:
            continue
        report = validate.Report()
        records = []
        history = []
        project_dir = projects_dir / name
        decisions_dir = project_dir / "decisions"
        if not safe_path(decisions_dir, root):
            report.error(project_dir, "linked project or decisions directory is not exported")
        elif decisions_dir.is_dir():
            for path in sorted(decisions_dir.glob("*.md")):
                if not safe_path(path, root):
                    report.error(path, "linked decision file is not exported")
                    continue
                record, parsed = read_decision(validate, root, name, path, report)
                if parsed is not None:
                    history.append(parsed)
                if record is not None:
                    records.append(record)
        # Validate all selected-project history before applying date/status filters.
        validate.check_history(name, history, report)
        invalid = {p["path"] for p in report.errors}
        decisions = [
            record for record in records
            if str(decisions_dir / (record["id"] + ".md")) not in invalid
            and (not since or record["decided_at"] >= since)
            and (not statuses or record["status"] in statuses)
        ]
        for item in report.items:
            problems.append({
                "level": item["level"],
                "path": relative(Path(item["path"]), root),
                "message": diagnostic_message(item),
            })
        decisions.sort(key=lambda d: d["id"])
        decisions.sort(key=lambda d: d["decided_at"], reverse=True)
        output.append({"id": name, "decisions": decisions})
    for name in missing:
        problems.append(
            {"level": "error", "path": "projects/" + name, "message": "project not found"}
        )
    # 指定了 --project 时不暴露其余项目的名字，避免导出结果泄露未授权项目的存在。
    listed = [n for n in wanted if n not in missing] if projects else available
    return {
        "schema": SCHEMA_VERSION,
        "ok": not missing,
        "projects": output,
        "available_projects": listed,
        "errors": [p for p in problems if p["level"] == "error"],
        "warnings": [p for p in problems if p["level"] == "warning"],
    }, missing


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read Cairn decisions as JSON.")
    parser.add_argument("repository", nargs="?", help="path to the Cairn repository")
    parser.add_argument("--project", action="append", default=[], help="project id; repeatable")
    parser.add_argument("--since", help="only decisions decided on or after this date")
    parser.add_argument("--status", help="comma-separated: valid,superseded,revoked")
    args = parser.parse_args(argv)

    validate = load_validate()
    since = args.since
    if since:
        try:
            validate.parse_date(since)
        except ValueError:
            parser.error("--since must be a date in YYYY-MM-DD form")
    statuses = None
    if args.status:
        statuses = [s.strip() for s in args.status.split(",") if s.strip()]
        unknown = [s for s in statuses if s not in validate.ALLOWED_STATUS]
        if unknown:
            parser.error("unknown status: %s" % ", ".join(unknown))

    for project in args.project:
        if not re.fullmatch(r"[a-z0-9-]+", project):
            parser.error("--project must be a lowercase project id")
    try:
        root = validate.resolve_repository(args.repository)
        result, missing = read_repository(validate, root, args.project, since, statuses)
    except (OSError, RuntimeError):
        print(json.dumps({
            "schema": SCHEMA_VERSION, "ok": False, "projects": [],
            "available_projects": [], "errors": [{"level": "error", "path": "projects",
            "message": "repository cannot be read"}], "warnings": [],
        }))
        return 2
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
