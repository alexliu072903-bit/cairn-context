#!/usr/bin/env python3
"""Install, upgrade, and inspect a Cairn repository and its Skill.

Usage:
  install.py install --identity NAME --project ID --repository PATH [targets] [options]
  install.py upgrade --repository PATH [targets] [options]
  install.py status  [--repository PATH] [targets] [--json]

Targets (repeat or combine):
  --claude-code        the Claude Code skills directory
  --codex              the Codex skills directory
  --skills-dir PATH    any other skills directory
  --detect             every host above whose configuration directory exists

Options:
  --dry-run            report what would change and write nothing
  --json               print machine-readable output
  --replace-config     (install) overwrite an existing config that points elsewhere

`install` creates a private repository from template/, writes the configuration,
and installs the Skill. It refuses a non-empty repository, an existing Skill, and
a configuration that points at a different repository, and checks every target
before writing anything.

`upgrade` refreshes only the managed scripts and the protocol version of an
existing repository, plus the installed Skill in the given targets. It never
touches decisions, project files, or the protocol text.

`status` reports whether Cairn is enabled, what is wrong when it is not, and
whether an upgrade is available.

Only the Python standard library is used.
"""

import argparse
import datetime
import json
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TEMPLATE = ROOT / "template"
SKILL_NAME = "cairn-context"
SCHEMA_VERSION = 1
PROJECT_ID = re.compile(r"^[a-z0-9-]+$")
# 升级只更新宿主程序依赖的脚本和协议版本，不碰决定、项目文件和协议正文。
MANAGED_FILES = (
    "scripts/index.py",
    "scripts/validate.py",
    "scripts/read.py",
    "protocol/VERSION",
)
HOSTS = (
    ("claude-code", "CLAUDE_CONFIG_DIR", ".claude", "CLAUDE_SKILLS_ROOT"),
    ("codex", "CODEX_HOME", ".codex", "CODEX_SKILLS_ROOT"),
)


class CairnError(Exception):
    """A refusal with a stable machine-readable code."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def home_path(value):
    return Path(os.path.expanduser(str(value)))


def config_path():
    """Use the same configuration resolver as the installed reader/index/validator."""
    spec = importlib.util.spec_from_file_location("cairn_validate", TEMPLATE / "scripts" / "validate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.config_path()


def host_dirs(host_id):
    """Return (host configuration directory, skills directory) for a known host."""
    for name, home_var, default_dir, skills_var in HOSTS:
        if name != host_id:
            continue
        base = home_path(os.environ.get(home_var) or "~/" + default_dir)
        override = os.environ.get(skills_var) or (
            os.environ.get("CAIRN_SKILLS_ROOT") if name == "codex" else None
        )
        return base, home_path(override) if override else base / "skills"
    raise KeyError(host_id)


def resolve_targets(args):
    """Return a list of {"id", "skills_dir", "kind"} from the target options."""
    targets = []
    seen = set()

    def add(host_id, skills_dir, kind):
        key = str(skills_dir)
        if key not in seen:
            seen.add(key)
            targets.append({"id": host_id, "skills_dir": skills_dir, "kind": kind})

    if getattr(args, "claude_code", False):
        add("claude-code", host_dirs("claude-code")[1], "generic")
    if getattr(args, "codex", False):
        add("codex", host_dirs("codex")[1], "codex")
    if getattr(args, "detect", False):
        for name, _, _, _ in HOSTS:
            base, skills = host_dirs(name)
            if base.is_dir():
                add(name, skills, "codex" if name == "codex" else "generic")
    for value in getattr(args, "skills_dir", None) or []:
        add("custom", home_path(value), "generic")
    return targets


def sha(path):
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_config():
    """Return (config dict or None, reason) for the configured Cairn."""
    path = config_path()
    if not path.is_file():
        return None, "not_found"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CairnError("config_invalid", "configuration cannot be read: %s" % exc)
    if not isinstance(data, dict):
        raise CairnError("config_invalid", "configuration must be a JSON object")
    for key in ("repository", "default_project"):
        if not data.get(key):
            raise CairnError("config_invalid", "configuration is missing %r" % key)
    for key in ("repository", "default_project", "identity"):
        if key in data and not isinstance(data[key], str):
            raise CairnError("config_invalid", "configuration field %r must be a string" % key)
    return data, None


def protocol_version(repository):
    """The repository protocol version; repositories without the file are version 0."""
    path = repository / "protocol" / "VERSION"
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0


def current_protocol_version():
    return int((TEMPLATE / "protocol" / "VERSION").read_text(encoding="utf-8").strip())


def managed_changes(repository):
    """List the managed files that are missing from or differ in a repository."""
    changes = []
    for name in MANAGED_FILES:
        source = TEMPLATE / name
        target = repository / name
        if not target.is_file():
            changes.append({"file": name, "action": "add"})
        elif sha(source) != sha(target):
            changes.append({"file": name, "action": "update"})
    return changes


def run_script(repository, script, *extra):
    result = subprocess.run(
        [sys.executable, str(repository / "scripts" / script), str(repository)] + list(extra),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=dict(os.environ, PYTHONIOENCODING="utf-8"),
    )
    return result


def fill_placeholders(path, replacements):
    text = path.read_text(encoding="utf-8")
    for old, new in replacements.items():
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")


def skill_files(target):
    return ("SKILL.md", "agents/openai.yaml") if target["kind"] == "codex" else ("SKILL.md",)


def check_destination(root, destination):
    """Refuse redirected files/directories before any upgrade write."""
    current = root
    for part in destination.relative_to(root).parts:
        current = current / part
        if current.is_symlink() or current.resolve() != current:
            raise CairnError("unsafe_path", "refusing a linked upgrade destination: %s" % current)
    if destination.is_file() and destination.stat().st_nlink > 1:
        raise CairnError("unsafe_path", "refusing a hard-linked upgrade destination: %s" % destination)


def copy_managed(source, root, destination):
    check_destination(root, destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Replace the directory entry instead of truncating a potentially linked file.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(source.read_bytes())
        shutil.copymode(source, temporary)
        os.replace(temporary, destination)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def install_skill(target):
    root = target["skills_dir"].resolve()
    destination = root / SKILL_NAME
    for name in skill_files(target):
        copy_managed(ROOT / name, root, destination / name)


def do_install(args):
    if not args.identity or not args.project or not args.repository:
        raise CairnError("missing_argument", "--identity, --project and --repository are required")
    if not PROJECT_ID.fullmatch(args.project):
        raise CairnError(
            "invalid_project", "project id must contain only lowercase letters, digits, and hyphens"
        )
    repository = home_path(args.repository).resolve()
    targets = resolve_targets(args) or [
        {"id": "codex", "skills_dir": host_dirs("codex")[1], "kind": "codex"}
    ]
    config = config_path()

    if repository.exists() and (not repository.is_dir() or any(repository.iterdir())):
        raise CairnError("repository_not_empty", "refusing to overwrite non-empty repository: %s" % repository)
    for target in targets:
        if (target["skills_dir"] / SKILL_NAME).exists() or (target["skills_dir"] / SKILL_NAME).is_symlink():
            raise CairnError(
                "skill_exists",
                "refusing to overwrite existing Skill: %s" % (target["skills_dir"] / SKILL_NAME),
            )
    if config.is_file() and not args.replace_config:
        try:
            existing = json.loads(config.read_text(encoding="utf-8"))
            same = home_path(existing.get("repository", "")).resolve() == repository.resolve()
        except (OSError, ValueError, AttributeError):
            same = False
        if not same:
            raise CairnError(
                "config_exists",
                "refusing to replace %s, which points at another repository; "
                "pass --replace-config to replace it" % config,
            )

    actions = [
        {"action": "create_repository", "path": str(repository)},
        {"action": "write_config", "path": str(config)},
    ] + [
        {"action": "install_skill", "host": t["id"], "path": str(t["skills_dir"] / SKILL_NAME)}
        for t in targets
    ]
    result = {
        "schema": SCHEMA_VERSION,
        "ok": True,
        "dry_run": bool(args.dry_run),
        "repository": str(repository),
        "config": str(config),
        "actions": actions,
    }
    if args.dry_run:
        return result

    repository.mkdir(parents=True, exist_ok=True)
    shutil.copytree(TEMPLATE, repository, dirs_exist_ok=True)
    projects = repository / "projects"
    (projects / "__PROJECT__").rename(projects / args.project)
    replacements = {
        "__PROJECT__": args.project,
        "__IDENTITY__": args.identity,
        "__DATE__": datetime.date.today().isoformat(),
    }
    for name in ("README.md", "state.md"):
        fill_placeholders(projects / args.project / name, replacements)
    for target in targets:
        install_skill(target)
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        json.dumps(
            {
                "repository": str(repository),
                "identity": args.identity,
                "default_project": args.project,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    index = run_script(repository, "index.py")
    result["index"] = "written" if index.returncode == 0 else "failed"
    return result


def do_upgrade(args):
    if args.repository:
        repository = home_path(args.repository).resolve()
    else:
        config, _ = read_config()
        if config is None:
            raise CairnError("not_enabled", "no Cairn configuration found; run install first")
        repository = home_path(config["repository"]).resolve()
    if not (repository / "projects").is_dir():
        raise CairnError("repository_unreadable", "no projects/ directory found in %s" % repository)
    for name in MANAGED_FILES:
        check_destination(repository, repository / name)
    changes = managed_changes(repository)
    skills = []
    for target in resolve_targets(args):
        skills_root = target["skills_dir"].resolve()
        installed = skills_root / SKILL_NAME
        check_destination(skills_root, installed)
        if not installed.is_dir():
            continue
        for name in skill_files(target):
            check_destination(skills_root, installed / name)
        if any(
            not (installed / name).is_file() or sha(installed / name) != sha(ROOT / name)
            for name in skill_files(target)
        ):
            skills.append({"host": target["id"], "path": str(installed), "target": target})
    result = {
        "schema": SCHEMA_VERSION,
        "ok": True,
        "dry_run": bool(args.dry_run),
        "repository": str(repository),
        "actions": changes
        + [{"action": "update_skill", "host": s["host"], "path": s["path"]} for s in skills],
    }
    if args.dry_run:
        return result
    for change in changes:
        destination = repository / change["file"]
        copy_managed(TEMPLATE / change["file"], repository, destination)
    for item in skills:
        install_skill(item["target"])
    return result


def do_status(args):
    reasons = []
    state = "ready"
    repository = None
    config_data = None
    try:
        config_data, reason = read_config()
        if config_data is None:
            state = "not_enabled"
            reasons.append("no configuration at %s" % config_path())
    except CairnError as exc:
        state = "error"
        reasons.append(str(exc))
    if args.repository:
        repository = home_path(args.repository).resolve()
        if state == "not_enabled":
            state = "ready"
            reasons = []
    elif config_data:
        repository = home_path(config_data["repository"])

    status = {
        "schema": SCHEMA_VERSION,
        "state": state,
        "config": str(config_path()),
        "repository": str(repository) if repository else None,
        "identity": (config_data or {}).get("identity"),
        "default_project": (config_data or {}).get("default_project"),
        "protocol_version": None,
        "current_protocol_version": current_protocol_version(),
        "upgrade_available": False,
        "projects": [],
        "stale_indexes": [],
        "validation": None,
        "hosts": [],
        "reasons": reasons,
    }
    detect = argparse.Namespace(
        claude_code=True, codex=True, detect=False, skills_dir=args.skills_dir
    )
    for target in resolve_targets(detect):
        base = host_dirs(target["id"])[0] if target["id"] != "custom" else None
        status["hosts"].append(
            {
                "id": target["id"],
                "skills_dir": str(target["skills_dir"]),
                "host_configured": bool(base and base.is_dir()),
                "skill_installed": (target["skills_dir"] / SKILL_NAME / "SKILL.md").is_file(),
            }
        )

    if repository is not None and state != "not_enabled":
        projects_dir = repository / "projects"
        if not projects_dir.is_dir():
            status["state"] = "error"
            reasons.append("no projects/ directory found in %s" % repository)
        else:
            status["projects"] = sorted(
                p.name for p in projects_dir.iterdir() if p.is_dir() and not p.name.startswith("_")
            )
            status["protocol_version"] = protocol_version(repository)
            status["upgrade_available"] = (
                status["protocol_version"] < status["current_protocol_version"]
                or bool(managed_changes(repository))
            )
            default = status["default_project"]
            if default and default not in status["projects"]:
                status["state"] = "error"
                reasons.append("default project %r has no directory under projects/" % default)
            if (repository / "scripts" / "validate.py").is_file():
                check = run_script(repository, "validate.py", "--json")
                try:
                    data = json.loads(check.stdout)
                    status["validation"] = {
                        "errors": len(data.get("errors", [])),
                        "warnings": len(data.get("warnings", [])),
                    }
                except ValueError:
                    reasons.append("validate.py output could not be read")
            if (repository / "scripts" / "index.py").is_file():
                stale = run_script(repository, "index.py", "--check")
                status["stale_indexes"] = [
                    line.split(" is ")[0] for line in stale.stdout.splitlines() if " is " in line
                ]
    return status


def build_parser():
    parser = argparse.ArgumentParser(description="Install, upgrade, and inspect Cairn.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("install", "upgrade", "status"):
        p = sub.add_parser(name)
        p.add_argument("--repository")
        p.add_argument("--claude-code", action="store_true")
        p.add_argument("--codex", action="store_true")
        p.add_argument("--detect", action="store_true")
        p.add_argument("--skills-dir", action="append", default=[])
        p.add_argument("--json", action="store_true")
        if name != "status":
            p.add_argument("--dry-run", action="store_true")
        if name == "install":
            p.add_argument("--identity")
            p.add_argument("--project")
            p.add_argument("--replace-config", action="store_true")
    return parser


def render_text(result):
    lines = []
    if "state" in result:
        lines.append("state: %s" % result["state"])
        for key in ("repository", "config", "protocol_version", "upgrade_available"):
            lines.append("%s: %s" % (key, result.get(key)))
        lines.append("projects: %s" % (", ".join(result["projects"]) or "none"))
        for host in result["hosts"]:
            lines.append(
                "%s: skill %s (%s)"
                % (host["id"], "installed" if host["skill_installed"] else "not installed", host["skills_dir"])
            )
        for reason in result["reasons"]:
            lines.append("problem: %s" % reason)
        return "\n".join(lines)
    prefix = "Would " if result.get("dry_run") else ""
    for action in result["actions"]:
        detail = action.get("path") or action.get("file")
        lines.append("%s%s: %s" % (prefix, action["action"], detail))
    if not result["actions"]:
        lines.append("Nothing to change.")
    return "\n".join(lines)


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        result = {"install": do_install, "upgrade": do_upgrade, "status": do_status}[args.command](args)
    except (CairnError, OSError, RuntimeError) as exc:
        code = exc.code if isinstance(exc, CairnError) else "io_error"
        if args.json:
            print(
                json.dumps(
                    {"schema": SCHEMA_VERSION, "ok": False, "code": code, "error": str(exc)},
                    ensure_ascii=True,
                )
            )
        else:
            print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=True, indent=2) if args.json else render_text(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
