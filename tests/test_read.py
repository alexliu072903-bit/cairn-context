"""Tests for template/scripts/read.py. Run with: python3 -m unittest discover -s tests"""

import json
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import schema_check  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
READ = ROOT / "template" / "scripts" / "read.py"
SCHEMA = json.loads((ROOT / "docs" / "schema" / "read-output.schema.json").read_text(encoding="utf-8"))

EN = "# T\n\n## Decision\nDo it.\n\n## Rationale\nBecause.\n\n## Scope\nAll.\n"


def decision(project, id_, status="valid", at="2026-10-01", extra="", body=EN, by="Pat"):
    return "---\nproject: %s\ndecision: %s\nstatus: %s\ndecided_by: %s\ndecided_at: %s\n%s---\n%s" % (
        project, id_, status, by, at, extra, body)


def run_read(repository, *args, env=None):
    result = subprocess.run(
        [sys.executable, str(READ), str(repository)] + list(args),
        capture_output=True, text=True, env=env,
    )
    return result.returncode, json.loads(result.stdout) if result.stdout.strip() else None, result


class ReadTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def add(self, project, id_, **kwargs):
        directory = self.root / "projects" / project / "decisions"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / (id_ + ".md")).write_text(decision(project, id_, **kwargs), encoding="utf-8")

    def test_output_matches_the_published_schema(self):
        self.add("demo", "one")
        code, data, _ = run_read(self.root)
        self.assertEqual(code, 0)
        self.assertEqual(schema_check.check(data, SCHEMA, SCHEMA), [])

    def test_output_contains_no_absolute_paths(self):
        self.add("demo", "one")
        _, data, result = run_read(self.root)
        self.assertNotIn(str(self.root), result.stdout)
        self.assertEqual(data["projects"][0]["decisions"][0]["file"], "projects/demo/decisions/one.md")

    def test_sections_are_normalized_across_languages(self):
        self.add("demo", "zh", body="# 标题\n\n## 结论\n做。\n\n## 为什么\n因为。\n\n## 适用范围\n全部。\n")
        _, data, _ = run_read(self.root)
        record = data["projects"][0]["decisions"][0]
        self.assertEqual(record["language"], "zh")
        self.assertEqual(
            (record["sections"]["decision"], record["sections"]["rationale"], record["sections"]["scope"]),
            ("做。", "因为。", "全部。"),
        )

    def test_missing_sections_are_empty_strings(self):
        self.add("demo", "short", body="# T\n\n## Decision\nOnly.\n")
        _, data, _ = run_read(self.root)
        sections = data["projects"][0]["decisions"][0]["sections"]
        self.assertEqual(sections["rationale"], "")
        self.assertEqual(sections["decision"], "Only.")

    def test_untrusted_files_are_reported_not_returned(self):
        self.add("demo", "good")
        self.add("demo", "bad-status", status="active")
        (self.root / "projects" / "demo" / "decisions" / "broken.md").write_text("nope", encoding="utf-8")
        code, data, _ = run_read(self.root)
        self.assertEqual(code, 0)
        self.assertEqual([d["id"] for d in data["projects"][0]["decisions"]], ["good"])
        self.assertEqual(
            sorted(Path(e["path"]).name for e in data["errors"]), ["bad-status.md", "broken.md"]
        )

    def test_timestamp_is_reduced_to_authored_date_with_a_warning(self):
        self.add("demo", "stamp", at="2026-10-11T23:30:00-05:00")
        _, data, _ = run_read(self.root)
        self.assertEqual(data["projects"][0]["decisions"][0]["decided_at"], "2026-10-11")
        self.assertTrue(any("calendar date" in w["message"] for w in data["warnings"]))

    def test_since_project_and_status_filters_combine(self):
        self.add("a", "old", at="2026-01-01")
        self.add("a", "new", at="2026-10-01")
        self.add("a", "gone", at="2026-10-02", status="revoked")
        self.add("b", "other", at="2026-10-01")
        _, data, _ = run_read(
            self.root, "--project", "a", "--since", "2026-06-01", "--status", "valid"
        )
        self.assertEqual([p["id"] for p in data["projects"]], ["a"])
        self.assertEqual([d["id"] for d in data["projects"][0]["decisions"]], ["new"])

    def test_authorization_unit_excludes_other_projects_entirely(self):
        self.add("shared", "ok")
        self.add("private", "secret")
        _, data, result = run_read(self.root, "--project", "shared")
        self.assertNotIn("private", result.stdout)
        self.assertNotIn("secret", result.stdout)
        self.assertEqual(data["available_projects"], ["shared"])

    def test_missing_project_exits_1_and_still_returns_the_rest(self):
        self.add("a", "one")
        code, data, _ = run_read(self.root, "--project", "a", "--project", "zzz")
        self.assertEqual(code, 1)
        self.assertFalse(data["ok"])
        self.assertEqual([p["id"] for p in data["projects"]], ["a"])

    def test_unreadable_repository_exits_2(self):
        code, data, _ = run_read(self.root / "missing")
        self.assertEqual(code, 2)
        self.assertFalse(data["ok"])

    def test_invalid_arguments_are_rejected(self):
        for args in (["--since", "last week"], ["--status", "maybe"]):
            code, _, result = run_read(self.root, *args)
            self.assertEqual(code, 2, args)
            self.assertIn("error", result.stderr)

    def test_source_files_are_never_modified(self):
        self.add("demo", "one")
        file = self.root / "projects" / "demo" / "decisions" / "one.md"
        before = file.read_bytes()
        run_read(self.root)
        self.assertEqual(file.read_bytes(), before)
        self.assertEqual(sorted(p.name for p in file.parent.iterdir()), ["one.md"])


class ReadBoundaryTests(unittest.TestCase):
    setUp = ReadTests.setUp
    add = ReadTests.add
    def link(self, destination, source):
        try:
            destination.symlink_to(source, target_is_directory=source.is_dir())
        except (OSError, NotImplementedError) as exc:
            self.skipTest("symlinks unavailable: %s" % exc)

    def test_config_root_and_explicit_config_precedence(self):
        self.add("configured", "one")
        config_root = self.root / "config-root"
        config_root.mkdir()
        (config_root / "config.json").write_text(json.dumps({"repository": str(self.root)}), encoding="utf-8")
        env = dict(os.environ, HOME=str(self.root), USERPROFILE=str(self.root), CAIRN_CONFIG_ROOT=str(config_root))
        env.pop("CAIRN_CONFIG", None)
        result = subprocess.run([sys.executable, str(READ)], capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["available_projects"], ["configured"])
        explicit = self.root / "explicit.json"
        explicit.write_text(json.dumps({"repository": str(self.root / "missing")}), encoding="utf-8")
        env["CAIRN_CONFIG"] = "~/explicit.json"
        result = subprocess.run([sys.executable, str(READ)], capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 2)
        self.assertFalse(json.loads(result.stdout)["ok"])

    def test_linked_file_cannot_export_an_external_absolute_path(self):
        self.add("shared", "one")
        with tempfile.TemporaryDirectory() as external:
            source = Path(external) / "one.md"
            source.write_text(decision("shared", "one", body="# External secret\n"), encoding="utf-8")
            target = self.root / "projects/shared/decisions/one.md"
            target.unlink()
            self.link(target, source)
            code, data, result = run_read(self.root, "--project", "shared")
            self.assertEqual(code, 0)
            self.assertEqual(data["projects"][0]["decisions"], [])
            self.assertNotIn(external, result.stdout)
            self.assertNotIn("External secret", result.stdout)
            self.assertEqual(data["errors"][0]["path"], "projects/shared/decisions/one.md")

    def test_linked_file_cannot_expose_another_project(self):
        self.add("shared", "one")
        self.add("private", "secret")
        target = self.root / "projects/shared/decisions/one.md"
        target.unlink()
        self.link(target, self.root / "projects/private/decisions/secret.md")
        _, data, result = run_read(self.root, "--project", "shared")
        self.assertNotIn("private", result.stdout)
        self.assertNotIn("secret", result.stdout)
        self.assertEqual(data["projects"][0]["decisions"], [])

    def test_linked_project_directory_cannot_expose_another_project(self):
        self.add("private", "secret")
        self.link(self.root / "projects/shared", self.root / "projects/private")
        _, data, result = run_read(self.root, "--project", "shared")
        self.assertNotIn("private", result.stdout)
        self.assertNotIn("secret", result.stdout)
        self.assertTrue(data["errors"])

    def test_linked_decisions_directory_is_rejected(self):
        self.add("private", "secret")
        shared = self.root / "projects/shared"
        shared.mkdir()
        self.link(shared / "decisions", self.root / "projects/private/decisions")
        _, data, result = run_read(self.root, "--project", "shared")
        self.assertEqual(data["projects"][0]["decisions"], [])
        self.assertNotIn("private", result.stdout)

    def test_mismatched_project_diagnostic_does_not_echo_other_name(self):
        self.add("shared", "one")
        path = self.root / "projects/shared/decisions/one.md"
        path.write_text(decision("private", "one"), encoding="utf-8")
        _, data, result = run_read(self.root, "--project", "shared")
        self.assertTrue(data["errors"])
        self.assertNotIn("private", result.stdout)

    def test_file_read_error_diagnostic_omits_os_paths(self):
        self.add("shared", "one")
        spec = importlib.util.spec_from_file_location("test_reader", READ)
        reader = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(reader)
        validator = reader.load_validate()
        with mock.patch.object(Path, "read_text", side_effect=PermissionError("denied /private/secret")):
            data, _ = reader.read_repository(validator, self.root, ["shared"])
        self.assertNotIn("/private/secret", json.dumps(data))
        self.assertEqual(data["errors"][0]["path"], "projects/shared/decisions/one.md")

    def test_repository_error_matches_the_published_schema(self):
        code, data, _ = run_read(self.root / "missing")
        self.assertEqual(code, 2)
        self.assertEqual(schema_check.check(data, SCHEMA, SCHEMA), [])

    def test_repository_permission_error_is_json_and_exit_two(self):
        (self.root / "projects").mkdir()
        spec = importlib.util.spec_from_file_location("test_reader", READ)
        reader = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(reader)
        import contextlib
        import io
        output = io.StringIO()
        with mock.patch.object(Path, "iterdir", side_effect=PermissionError("/private/secret")):
            with contextlib.redirect_stdout(output):
                code = reader.main([str(self.root)])
        self.assertEqual(code, 2)
        data = json.loads(output.getvalue())
        self.assertEqual(schema_check.check(data, SCHEMA, SCHEMA), [])
        self.assertNotIn("/private/secret", output.getvalue())

    def test_dangling_history_is_reported_and_omitted(self):
        self.add("demo", "good")
        self.add("demo", "bad", extra="supersedes: ghost\n")
        _, data, _ = run_read(self.root)
        self.assertEqual([d["id"] for d in data["projects"][0]["decisions"]], ["good"])
        self.assertEqual(data["errors"][0]["path"], "projects/demo/decisions/bad.md")

    def test_history_cycles_are_omitted(self):
        self.add("demo", "a", status="superseded", extra="supersedes: b\n")
        self.add("demo", "b", status="superseded", extra="supersedes: a\n")
        _, data, _ = run_read(self.root)
        self.assertEqual(data["projects"][0]["decisions"], [])
        self.assertEqual(len(data["errors"]), 2)

    def test_history_is_checked_before_export_filters(self):
        self.add("demo", "old", status="superseded", at="2026-01-01")
        self.add("demo", "new", at="2026-10-01", extra="supersedes: old\n")
        _, data, _ = run_read(self.root, "--since", "2026-09-01", "--status", "valid")
        self.assertEqual(data["errors"], [])
        self.assertEqual([d["id"] for d in data["projects"][0]["decisions"]], ["new"])

    def test_non_padded_decision_date_is_rejected(self):
        self.add("demo", "one", at="2026-1-1")
        _, data, _ = run_read(self.root, "--since", "2026-02-01")
        self.assertEqual(data["projects"][0]["decisions"], [])
        self.assertTrue(data["errors"])
        self.assertEqual(schema_check.check(data, SCHEMA, SCHEMA), [])

    def test_non_padded_since_date_is_rejected(self):
        self.add("demo", "one")
        code, _, _ = run_read(self.root, "--since", "2026-1-1")
        self.assertEqual(code, 2)

    def test_json_is_portable_to_a_non_utf8_pipe(self):
        self.add("demo", "one", body="# 中文标题\n\n## 结论\n做。\n", by="测试者")
        env = dict(os.environ, PYTHONIOENCODING="cp1252")
        code, data, result = run_read(self.root, env=env)
        self.assertEqual(code, 0, result.stderr)
        record = data["projects"][0]["decisions"][0]
        self.assertEqual(record["title"], "中文标题")
        self.assertEqual(record["decided_by"], "测试者")



if __name__ == "__main__":
    unittest.main()
