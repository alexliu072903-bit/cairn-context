"""Tests for install.py (install, upgrade, status). Run with: python3 -m unittest discover -s tests"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import schema_check  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
INSTALL = ROOT / "install.py"
STATUS_SCHEMA = json.loads(
    (ROOT / "docs" / "schema" / "status-output.schema.json").read_text(encoding="utf-8")
)
ISOLATED = (
    "CAIRN_CONFIG", "CAIRN_CONFIG_ROOT", "CAIRN_SKILLS_ROOT", "CODEX_SKILLS_ROOT",
    "CLAUDE_SKILLS_ROOT", "CLAUDE_CONFIG_DIR", "CODEX_HOME",
)


def tree_hash(path):
    digest = hashlib.sha256()
    for item in sorted(Path(path).rglob("*")):
        if item.is_file():
            digest.update(item.relative_to(path).as_posix().encode())
            digest.update(item.read_bytes())
    return digest.hexdigest()


class InstallCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name) / "home"
        self.home.mkdir()
        self.env = {k: v for k, v in os.environ.items() if k not in ISOLATED}
        self.env["HOME"] = str(self.home)
        self.env["USERPROFILE"] = str(self.home)
        self.repo = (Path(self._tmp.name) / "cairn").resolve()
        self.config = self.home / ".cairn" / "config.json"

    def run_install(self, *args, expect=0):
        result = subprocess.run(
            [sys.executable, str(INSTALL)] + list(args),
            capture_output=True, text=True, env=self.env,
        )
        self.assertEqual(result.returncode, expect, result.stdout + result.stderr)
        return result

    def install(self, *extra, expect=0, repo=None):
        return self.run_install(
            "install", "--identity", "Pat Example", "--project", "demo",
            "--repository", str(repo or self.repo), "--json", *extra, expect=expect,
        )

    def status(self, *extra):
        result = self.run_install("status", "--json", *extra)
        data = json.loads(result.stdout)
        self.assertEqual(schema_check.check(data, STATUS_SCHEMA, STATUS_SCHEMA), [])
        return data

    def skill(self, host=".claude"):
        return self.home / host / "skills" / "cairn-context"


class InstallTests(InstallCase):
    def test_creates_repository_config_skill_and_index(self):
        self.install("--claude-code")
        project = self.repo / "projects" / "demo"
        self.assertTrue((project / "decisions").is_dir())
        self.assertFalse((self.repo / "projects" / "__PROJECT__").exists())
        for name in ("README.md", "state.md"):
            text = (project / name).read_text(encoding="utf-8")
            self.assertNotIn("__", text)
            self.assertIn("demo", text)
        self.assertTrue((project / "decisions-index.md").is_file())
        self.assertTrue((self.skill() / "SKILL.md").is_file())
        self.assertFalse((self.skill() / "agents").exists())
        self.assertEqual(
            json.loads(self.config.read_text(encoding="utf-8")),
            {"repository": str(self.repo), "identity": "Pat Example", "default_project": "demo"},
        )

    def test_the_generated_repository_validates_cleanly(self):
        self.install("--claude-code")
        result = subprocess.run(
            [sys.executable, str(self.repo / "scripts" / "validate.py"), str(self.repo), "--json", "--strict"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_codex_target_also_gets_its_agent_manifest(self):
        self.install("--codex")
        self.assertTrue((self.skill(".codex") / "agents" / "openai.yaml").is_file())

    def test_template_is_not_modified_by_installing(self):
        before = tree_hash(ROOT / "template")
        self.install("--claude-code")
        self.assertEqual(tree_hash(ROOT / "template"), before)

    def test_dry_run_reports_actions_and_writes_nothing(self):
        result = self.install("--claude-code", "--dry-run")
        data = json.loads(result.stdout)
        self.assertTrue(data["dry_run"])
        self.assertEqual(
            [a["action"] for a in data["actions"]],
            ["create_repository", "write_config", "install_skill"],
        )
        self.assertFalse(self.repo.exists())
        self.assertFalse(self.config.exists())
        self.assertFalse(self.skill().exists())

    def test_refuses_a_non_empty_repository_and_writes_nothing_else(self):
        self.repo.mkdir()
        (self.repo / "keep.txt").write_text("mine", encoding="utf-8")
        data = json.loads(self.install("--claude-code", expect=1).stdout)
        self.assertEqual(data["code"], "repository_not_empty")
        self.assertEqual([p.name for p in self.repo.iterdir()], ["keep.txt"])
        self.assertFalse(self.config.exists())
        self.assertFalse(self.skill().exists())

    def test_refuses_an_existing_skill_before_creating_anything(self):
        self.skill().mkdir(parents=True)
        (self.skill() / "SKILL.md").write_text("theirs", encoding="utf-8")
        data = json.loads(self.install("--claude-code", expect=1).stdout)
        self.assertEqual(data["code"], "skill_exists")
        self.assertFalse(self.repo.exists())
        self.assertEqual((self.skill() / "SKILL.md").read_text(encoding="utf-8"), "theirs")

    def test_one_conflicting_target_blocks_all_targets(self):
        (self.home / ".codex" / "skills" / "cairn-context").mkdir(parents=True)
        self.install("--claude-code", "--codex", expect=1)
        self.assertFalse(self.skill().exists())
        self.assertFalse(self.repo.exists())

    def test_does_not_replace_a_config_pointing_elsewhere(self):
        self.config.parent.mkdir(parents=True)
        original = json.dumps({"repository": "/somewhere/else", "default_project": "x"})
        self.config.write_text(original, encoding="utf-8")
        data = json.loads(self.install("--claude-code", expect=1).stdout)
        self.assertEqual(data["code"], "config_exists")
        self.assertEqual(self.config.read_text(encoding="utf-8"), original)
        self.assertFalse(self.repo.exists())
        self.install("--claude-code", "--replace-config")
        self.assertEqual(json.loads(self.config.read_text(encoding="utf-8"))["repository"], str(self.repo))

    def test_rejects_invalid_project_and_missing_arguments(self):
        result = self.run_install(
            "install", "--identity", "A", "--project", "Bad_Name",
            "--repository", str(self.repo), "--json", expect=1,
        )
        self.assertEqual(json.loads(result.stdout)["code"], "invalid_project")
        result = self.run_install("install", "--json", expect=1)
        self.assertEqual(json.loads(result.stdout)["code"], "missing_argument")

    def test_detect_installs_only_where_the_host_exists(self):
        (self.home / ".claude").mkdir()
        self.install("--detect")
        self.assertTrue((self.skill() / "SKILL.md").is_file())
        self.assertFalse((self.home / ".codex").exists())

    def test_custom_skills_dir_and_environment_overrides(self):
        custom = Path(self._tmp.name) / "elsewhere"
        self.env["CODEX_HOME"] = str(Path(self._tmp.name) / "codex-home")
        self.install("--skills-dir", str(custom), "--codex")
        self.assertTrue((custom / "cairn-context" / "SKILL.md").is_file())
        self.assertTrue(
            (Path(self._tmp.name) / "codex-home" / "skills" / "cairn-context" / "SKILL.md").is_file()
        )

    @unittest.skipIf(os.name == "nt", "install.sh is a POSIX wrapper")
    def test_install_sh_keeps_the_original_command_line(self):
        result = subprocess.run(
            ["bash", str(ROOT / "install.sh"), "--identity", "Pat", "--project", "demo",
             "--repository", str(self.repo), "--claude-code"],
            capture_output=True, text=True, env=self.env,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.skill() / "SKILL.md").is_file())
        self.assertTrue(self.config.is_file())


class StatusTests(InstallCase):
    def test_not_enabled_without_a_configuration(self):
        data = self.status()
        self.assertEqual(data["state"], "not_enabled")
        self.assertIsNone(data["repository"])

    def test_ready_after_install(self):
        self.install("--claude-code")
        data = self.status()
        self.assertEqual(data["state"], "ready")
        self.assertEqual(data["projects"], ["demo"])
        self.assertEqual(data["default_project"], "demo")
        self.assertFalse(data["upgrade_available"])
        self.assertEqual(data["validation"], {"errors": 0, "warnings": 0})
        claude = next(h for h in data["hosts"] if h["id"] == "claude-code")
        self.assertTrue(claude["skill_installed"])

    def test_reports_each_failure_with_a_reason(self):
        self.config.parent.mkdir(parents=True)
        self.config.write_text("{not json", encoding="utf-8")
        data = self.status()
        self.assertEqual(data["state"], "error")
        self.assertTrue(data["reasons"])

        self.config.write_text(
            json.dumps({"repository": str(self.repo / "gone"), "default_project": "demo"}),
            encoding="utf-8",
        )
        self.assertEqual(self.status()["state"], "error")

    def test_default_project_without_a_directory_is_an_error(self):
        self.install("--claude-code")
        shutil.rmtree(self.repo / "projects" / "demo")
        (self.repo / "projects" / "other").mkdir()
        data = self.status()
        self.assertEqual(data["state"], "error")
        self.assertIn("demo", " ".join(data["reasons"]))

    def test_detects_stale_index_and_validation_errors(self):
        self.install("--claude-code")
        decisions = self.repo / "projects" / "demo" / "decisions"
        (decisions / "broken.md").write_text("nope", encoding="utf-8")
        (decisions / "fine.md").write_text(
            "---\nproject: demo\ndecision: fine\nstatus: valid\ndecided_by: Pat\n"
            "decided_at: 2026-10-01\n---\n# Fine\n\n## Decision\nYes.\n",
            encoding="utf-8",
        )
        data = self.status()
        self.assertEqual(data["validation"]["errors"], 1)
        self.assertEqual(data["stale_indexes"], ["projects/demo/decisions-index.md"])

    def test_status_with_an_explicit_repository_and_no_configuration(self):
        self.install("--claude-code")
        self.config.unlink()
        data = self.status("--repository", str(self.repo))
        self.assertEqual(data["state"], "ready")
        self.assertEqual(data["projects"], ["demo"])


class UpgradeTests(InstallCase):
    def legacy(self):
        """Make the repository look like one created before read.py and the version file existed."""
        (self.repo / "scripts" / "read.py").unlink()
        (self.repo / "protocol" / "VERSION").unlink()
        (self.repo / "scripts" / "validate.py").write_text("# old\n", encoding="utf-8")

    def test_legacy_repository_reports_an_available_upgrade(self):
        self.install("--claude-code")
        self.legacy()
        data = self.status()
        self.assertTrue(data["upgrade_available"])
        self.assertEqual(data["protocol_version"], 0)

    def test_upgrade_restores_managed_files_and_leaves_everything_else(self):
        self.install("--claude-code")
        decision = self.repo / "projects" / "demo" / "decisions" / "mine.md"
        decision.write_text(
            "---\nproject: demo\ndecision: mine\nstatus: valid\ndecided_by: Pat\n"
            "decided_at: 2026-10-01\n---\n# Mine\n\n## Decision\nKeep me.\n",
            encoding="utf-8",
        )
        protocol = self.repo / "protocol" / "README.md"
        protocol.write_text("customised protocol", encoding="utf-8")
        self.legacy()
        untouched = {
            p: p.read_bytes() for p in (decision, protocol, self.repo / "AGENTS.md")
        }
        self.run_install("upgrade", "--repository", str(self.repo), "--json")
        for path, content in untouched.items():
            self.assertEqual(path.read_bytes(), content)
        self.assertTrue((self.repo / "scripts" / "read.py").is_file())
        self.assertEqual((self.repo / "protocol" / "VERSION").read_text().strip(), "1")
        self.assertFalse(self.status()["upgrade_available"])

    def test_dry_run_changes_nothing(self):
        self.install("--claude-code")
        self.legacy()
        before = tree_hash(self.repo)
        data = json.loads(
            self.run_install("upgrade", "--repository", str(self.repo), "--dry-run", "--json").stdout
        )
        self.assertTrue(data["actions"])
        self.assertEqual(tree_hash(self.repo), before)

    def test_upgrade_refreshes_only_an_installed_skill(self):
        self.install("--claude-code")
        (self.skill() / "SKILL.md").write_text("stale", encoding="utf-8")
        self.run_install(
            "upgrade", "--repository", str(self.repo), "--claude-code", "--codex", "--json"
        )
        self.assertEqual(
            (self.skill() / "SKILL.md").read_text(encoding="utf-8"),
            (ROOT / "SKILL.md").read_text(encoding="utf-8"),
        )
        self.assertFalse((self.home / ".codex").exists())

    def test_upgrade_requires_a_readable_repository(self):
        result = self.run_install("upgrade", "--repository", str(self.repo), "--json", expect=1)
        self.assertEqual(json.loads(result.stdout)["code"], "repository_unreadable")


class IntegrationBoundaryTests(InstallCase):
    def link(self, destination, source):
        try:
            destination.symlink_to(source, target_is_directory=source.is_dir())
        except (OSError, NotImplementedError) as exc:
            self.skipTest("symlinks unavailable: %s" % exc)

    def test_config_root_is_shared_by_install_and_installed_reader(self):
        self.env["CAIRN_CONFIG_ROOT"] = str(self.home / "custom-config")
        self.install("--claude-code")
        self.assertFalse(self.config.exists())
        result = subprocess.run([sys.executable, str(self.repo / "scripts/read.py")],
                                capture_output=True, text=True, env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["available_projects"], ["demo"])
        self.assertEqual(self.status()["state"], "ready")

    def test_explicit_config_expands_tilde_and_overrides_config_root(self):
        self.env["CAIRN_CONFIG"] = "~/explicit.json"
        self.env["CAIRN_CONFIG_ROOT"] = str(self.home / "unused")
        self.install("--claude-code")
        self.assertTrue((self.home / "explicit.json").is_file())
        self.assertFalse((self.home / "unused").exists())
        self.assertEqual(self.status()["state"], "ready")

    def test_upgrade_refuses_linked_managed_file_before_any_write(self):
        self.install("--claude-code")
        victim = self.repo / "projects/demo/decisions/mine.md"
        victim.write_text("keep this decision", encoding="utf-8")
        target = self.repo / "protocol/VERSION"
        target.unlink()
        self.link(target, victim)
        (self.repo / "scripts/index.py").write_text("# stale", encoding="utf-8")
        before = tree_hash(self.repo)
        result = self.run_install("upgrade", "--repository", str(self.repo), "--json", expect=1)
        self.assertEqual(json.loads(result.stdout)["code"], "unsafe_path")
        self.assertEqual(tree_hash(self.repo), before)
        self.assertEqual(victim.read_text(encoding="utf-8"), "keep this decision")

    def test_upgrade_refuses_linked_scripts_directory(self):
        self.install("--claude-code")
        shutil.rmtree(self.repo / "scripts")
        victim = self.repo / "projects/demo/decisions"
        self.link(self.repo / "scripts", victim)
        before = tree_hash(self.repo)
        self.run_install("upgrade", "--repository", str(self.repo), "--json", expect=1)
        self.assertEqual(tree_hash(self.repo), before)
        self.assertEqual([p.name for p in victim.iterdir()], [".gitkeep"])

    def test_upgrade_refuses_linked_skill_before_updating_scripts(self):
        self.install("--codex")
        victim = self.repo / "projects/demo/decisions/mine.md"
        victim.write_text("keep this decision", encoding="utf-8")
        manifest = self.skill(".codex") / "agents/openai.yaml"
        manifest.unlink()
        self.link(manifest, victim)
        (self.repo / "scripts/read.py").write_text("# stale", encoding="utf-8")
        before = tree_hash(self.repo)
        result = self.run_install("upgrade", "--repository", str(self.repo), "--codex", "--json", expect=1)
        self.assertEqual(json.loads(result.stdout)["code"], "unsafe_path")
        self.assertEqual(tree_hash(self.repo), before)
        self.assertEqual(victim.read_text(encoding="utf-8"), "keep this decision")

    def test_upgrade_refuses_hardlinked_managed_file(self):
        self.install("--claude-code")
        victim = self.repo / "projects/demo/decisions/mine.md"
        victim.write_text("keep this decision", encoding="utf-8")
        target = self.repo / "scripts/read.py"
        target.unlink()
        try:
            os.link(victim, target)
        except OSError as exc:
            self.skipTest("hardlinks unavailable: %s" % exc)
        before = tree_hash(self.repo)
        self.run_install("upgrade", "--repository", str(self.repo), "--json", expect=1)
        self.assertEqual(tree_hash(self.repo), before)

    def test_upgrade_refreshes_a_stale_codex_manifest(self):
        self.install("--codex")
        manifest = self.skill(".codex") / "agents/openai.yaml"
        manifest.write_text("stale", encoding="utf-8")
        self.run_install("upgrade", "--repository", str(self.repo), "--codex", "--json")
        self.assertEqual(manifest.read_bytes(), (ROOT / "agents/openai.yaml").read_bytes())

    def test_upgrade_only_changes_allowlisted_repository_files(self):
        self.install("--claude-code")
        before = {p.relative_to(self.repo).as_posix(): p.read_bytes()
                  for p in self.repo.rglob("*") if p.is_file()}
        for name in ("scripts/index.py", "scripts/validate.py", "scripts/read.py", "protocol/VERSION"):
            (self.repo / name).write_text("stale", encoding="utf-8")
        self.run_install("upgrade", "--repository", str(self.repo), "--json")
        after = {p.relative_to(self.repo).as_posix(): p.read_bytes()
                 for p in self.repo.rglob("*") if p.is_file()}
        self.assertEqual(after, before)

    def test_json_status_is_portable_to_a_non_utf8_pipe(self):
        self.install("--claude-code")
        data = json.loads(self.config.read_text(encoding="utf-8"))
        data["identity"] = "测试者"
        self.config.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        self.env["PYTHONIOENCODING"] = "cp1252"
        self.assertEqual(self.status()["identity"], "测试者")

    def test_malformed_config_field_types_report_error_state(self):
        self.config.parent.mkdir(parents=True)
        self.config.write_text(json.dumps({"repository": ["wrong"], "default_project": "demo"}), encoding="utf-8")
        self.assertEqual(self.status()["state"], "error")



if __name__ == "__main__":
    unittest.main()
