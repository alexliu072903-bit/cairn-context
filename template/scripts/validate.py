#!/usr/bin/env python3
"""Validate the decision files in a Cairn repository.

Usage:
  validate.py [REPOSITORY] [--json] [--strict]

REPOSITORY defaults to the "repository" value in ~/.cairn/config.json (or the
file named by $CAIRN_CONFIG), then to the repository that contains this script.

Exit status: 0 when there are no errors, 1 when there is at least one error
(or any warning with --strict), 2 when the repository cannot be read.

Only the Python standard library is used.
"""

import argparse
import datetime
import json
import os
import re
import sys
import types
from pathlib import Path

ALLOWED_STATUS = ("valid", "superseded", "revoked")
REQUIRED_FIELDS = ("project", "decision", "status", "decided_by", "decided_at")
LIST_FIELDS = ("supersedes", "superseded_by")
KNOWN_FIELDS = REQUIRED_FIELDS + LIST_FIELDS
# 章节标题：每种语言一套，按文件实际使用的那一套检查是否齐全。
SECTION_SETS = {
    "English": ("Decision", "Rationale", "Scope", "Explicitly excluded", "Overturn signal"),
    "Chinese": ("结论", "为什么", "适用范围", "明确不做", "推翻条件"),
}
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
KEY_VALUE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)$")
LIST_ITEM = re.compile(r"^\s+-\s+(.*)$")


class Report:
    """Collects errors and warnings with the file they belong to."""

    def __init__(self):
        self.items = []

    def error(self, path, message):
        self.items.append({"level": "error", "path": str(path), "message": message})

    def warning(self, path, message):
        self.items.append({"level": "warning", "path": str(path), "message": message})

    @property
    def errors(self):
        return [i for i in self.items if i["level"] == "error"]

    @property
    def warnings(self):
        return [i for i in self.items if i["level"] == "warning"]


def unquote(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def parse_decision(path, report):
    """Return (frontmatter dict, body text) or None when the file cannot be parsed."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        report.error(path, "cannot read file: %s" % exc)
        return None
    text = text.replace("\r\n", "\n")
    if not text.startswith("---\n"):
        report.error(path, "missing frontmatter: the file must start with a line containing only ---")
        return None
    end = text.find("\n---", 4)
    if end == -1:
        report.error(path, "unterminated frontmatter: no closing --- line")
        return None
    block = text[4:end]
    body = text[end + 4 :].lstrip("\n")
    fields = {}
    last_key = None
    for number, line in enumerate(block.split("\n"), start=2):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        item = LIST_ITEM.match(line)
        if item and last_key in LIST_FIELDS and isinstance(fields.get(last_key), list):
            fields[last_key].append(unquote(item.group(1)))
            continue
        match = KEY_VALUE.match(line)
        if not match:
            report.error(path, "frontmatter line %d is not 'key: value': %r" % (number, line))
            continue
        key, value = match.group(1), match.group(2).strip()
        if key in fields:
            report.error(path, "frontmatter key %r appears more than once" % key)
            last_key = None
            continue
        last_key = key
        if key in LIST_FIELDS:
            if value.startswith("[") and value.endswith("]"):
                fields[key] = [unquote(v) for v in value[1:-1].split(",") if v.strip()]
            elif value:
                fields[key] = [unquote(value)]
            else:
                fields[key] = []
        else:
            fields[key] = unquote(value)
    return fields, body


def check_decision(path, project_id, fields, body, report):
    """Check one decision file on its own."""
    for name in REQUIRED_FIELDS:
        if not fields.get(name):
            report.error(path, "missing required field %r" % name)

    if fields.get("project") and fields["project"] != project_id:
        report.error(
            path,
            "field project is %r but the file is under projects/%s/" % (fields["project"], project_id),
        )
    if fields.get("decision") and fields["decision"] != path.stem:
        report.error(
            path,
            "field decision is %r but the file name is %r" % (fields["decision"], path.stem),
        )
    if fields.get("status") and fields["status"] not in ALLOWED_STATUS:
        report.error(
            path,
            "status %r is not one of: %s" % (fields["status"], ", ".join(ALLOWED_STATUS)),
        )
    if fields.get("decided_at"):
        try:
            datetime.datetime.strptime(fields["decided_at"], "%Y-%m-%d")
        except ValueError:
            report.error(path, "decided_at %r is not a date in YYYY-MM-DD form" % fields["decided_at"])
    for key in LIST_FIELDS:
        if fields.get("decision") and fields.get("decision") in fields.get(key, []):
            report.error(path, "a decision cannot be listed in its own %s" % key)

    for key in fields:
        if key not in KNOWN_FIELDS:
            report.warning(path, "unknown frontmatter field %r" % key)
    if not ID_PATTERN.match(path.stem):
        report.warning(path, "decision id should use lowercase letters, digits, and hyphens")

    lines = body.split("\n")
    headings = [line[3:].strip() for line in lines if line.startswith("## ")]
    if not any(line.startswith("# ") for line in lines):
        report.warning(path, "missing a title line starting with '# '")
    best = max(SECTION_SETS, key=lambda name: sum(1 for h in SECTION_SETS[name] if h in headings))
    if not any(h in headings for h in SECTION_SETS[best]):
        report.warning(path, "none of the expected sections were found")
    else:
        for section in SECTION_SETS[best]:
            if section not in headings:
                report.warning(path, "missing section '## %s' (write 'To be validated' if unknown)" % section)


def check_history(project_id, decisions, report):
    """Check supersession links across the decisions of one project."""
    by_id = {d["id"]: d for d in decisions}
    successors = {}  # 旧决定 id -> 替代它的决定 id 集合（来自 supersedes 或 superseded_by）

    for decision in decisions:
        for target in decision["fields"].get("supersedes", []):
            old = by_id.get(target)
            if old is None:
                report.error(
                    decision["path"],
                    "supersedes %r, but projects/%s/decisions/%s.md does not exist" % (target, project_id, target),
                )
                continue
            successors.setdefault(target, set()).add(decision["id"])
            if old["fields"].get("status") == "valid":
                report.error(
                    decision["path"],
                    "supersedes %r, which is still marked valid; mark it superseded or revoked" % target,
                )

    for decision in decisions:
        for target in decision["fields"].get("superseded_by", []):
            new = by_id.get(target)
            if new is None:
                report.error(
                    decision["path"],
                    "superseded_by %r, but projects/%s/decisions/%s.md does not exist" % (target, project_id, target),
                )
                continue
            successors.setdefault(decision["id"], set()).add(target)
            if decision["id"] not in new["fields"].get("supersedes", []):
                report.warning(
                    decision["path"],
                    "superseded_by %r, but that decision does not list %r in supersedes" % (target, decision["id"]),
                )
        if decision["fields"].get("superseded_by") and decision["fields"].get("status") == "valid":
            report.warning(decision["path"], "has superseded_by but its status is still valid")

    for target, followers in sorted(successors.items()):
        if len(followers) > 1:
            names = ", ".join(sorted(followers))
            report.warning(
                by_id[target]["path"],
                "replaced by more than one decision (%s)" % names,
            )

    reported = set()
    for decision in decisions:
        stack = [(decision["id"], [decision["id"]])]
        while stack:
            current, path_ids = stack.pop()
            for target in by_id[current]["fields"].get("supersedes", []):
                if target not in by_id:
                    continue
                if target in path_ids:
                    key = frozenset(path_ids + [target])
                    if key not in reported:
                        reported.add(key)
                        report.error(decision["path"], "supersedes chain contains a cycle through %r" % target)
                    continue
                stack.append((target, path_ids + [target]))

    for decision in decisions:
        if decision["fields"].get("status") == "superseded" and decision["id"] not in successors:
            report.warning(
                decision["path"],
                "status is superseded, but no decision supersedes it",
            )


def check_index(project, report):
    """Warn when an existing decisions-index.md no longer matches the decisions."""
    target = project / "decisions-index.md"
    script = Path(__file__).resolve().with_name("index.py")
    if not target.is_file() or not script.is_file():
        return
    import importlib.util

    spec = importlib.util.spec_from_file_location("cairn_index", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    me = types.SimpleNamespace(Report=Report, parse_decision=parse_decision)
    expected, _, _ = module.render_project(me, project)
    try:
        current = target.read_text(encoding="utf-8")
    except OSError:
        return
    if current != expected:
        report.warning(target, "the index is out of date; run scripts/index.py")


def validate(root):
    """Validate a repository and return (report, counts)."""
    report = Report()
    projects_dir = root / "projects"
    counts = {"projects": 0, "decisions": 0}
    if not projects_dir.is_dir():
        return None, counts

    for project in sorted(p for p in projects_dir.iterdir() if p.is_dir()):
        counts["projects"] += 1
        for name in ("README.md", "state.md"):
            if not (project / name).is_file():
                report.warning(project / name, "project is missing %s" % name)
        decisions_dir = project / "decisions"
        parsed = []
        if decisions_dir.is_dir():
            for path in sorted(decisions_dir.glob("*.md")):
                counts["decisions"] += 1
                result = parse_decision(path, report)
                if result is None:
                    continue
                fields, body = result
                check_decision(path, project.name, fields, body, report)
                parsed.append({"id": path.stem, "path": path, "fields": fields})
        check_history(project.name, parsed, report)
        check_index(project, report)
    return report, counts


def resolve_repository(argument):
    if argument:
        return Path(os.path.expanduser(argument))
    config = Path(os.environ.get("CAIRN_CONFIG", os.path.expanduser("~/.cairn/config.json")))
    if config.is_file():
        try:
            data = json.loads(config.read_text(encoding="utf-8"))
            if data.get("repository"):
                return Path(os.path.expanduser(data["repository"]))
        except (OSError, ValueError):
            pass
    return Path(__file__).resolve().parent.parent


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate Cairn decision files.")
    parser.add_argument("repository", nargs="?", help="path to the Cairn repository")
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    parser.add_argument("--strict", action="store_true", help="treat warnings as errors")
    args = parser.parse_args(argv)

    root = resolve_repository(args.repository)
    report, counts = validate(root)
    if report is None:
        message = "no projects/ directory found in %s" % root
        if args.json:
            print(json.dumps({"ok": False, "error": message}))
        else:
            print(message, file=sys.stderr)
        return 2

    failed = bool(report.errors) or (args.strict and bool(report.warnings))
    if args.json:
        print(
            json.dumps(
                {
                    "ok": not failed,
                    "repository": str(root),
                    "projects": counts["projects"],
                    "decisions": counts["decisions"],
                    "errors": report.errors,
                    "warnings": report.warnings,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        for item in report.items:
            try:
                shown = Path(item["path"]).relative_to(root)
            except ValueError:
                shown = item["path"]
            print("%s: %s: %s" % (shown, item["level"], item["message"]))
        print(
            "%d decision(s) in %d project(s): %d error(s), %d warning(s)"
            % (counts["decisions"], counts["projects"], len(report.errors), len(report.warnings))
        )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
