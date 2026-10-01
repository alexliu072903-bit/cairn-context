"""Tests for template/scripts/validate.py. Run with: python3 -m unittest discover -s tests"""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "template" / "scripts" / "validate.py"

spec = importlib.util.spec_from_file_location("cairn_validate", SCRIPT)
validate_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validate_module)

GOOD_BODY = """
# Title

## Decision
Do the thing.

## Rationale
Because.

## Scope
Here.

## Explicitly excluded
Not that.

## Overturn signal
If X.
"""


ZH_BODY = """
# 标题

## 结论
做这件事。

## 为什么
因为。

## 适用范围
这里。

## 明确不做
不做那个。

## 推翻条件
如果 X。
"""


def decision_text(decision, project="demo", status="valid", supersedes=None, body=GOOD_BODY, extra=""):
    lines = [
        "---",
        "project: %s" % project,
        "decision: %s" % decision,
        "status: %s" % status,
        "decided_by: Test User",
        "decided_at: 2026-09-01",
    ]
    if isinstance(supersedes, (list, tuple)):
        lines.append("supersedes:")
        lines.extend("  - %s" % item for item in supersedes)
    elif supersedes:
        lines.append("supersedes: %s" % supersedes)
    if extra:
        lines.append(extra)
    lines.append("---")
    return "\n".join(lines) + "\n" + body


class RepositoryCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.project = self.root / "projects" / "demo"
        (self.project / "decisions").mkdir(parents=True)
        (self.project / "README.md").write_text("# demo\n")
        (self.project / "state.md").write_text("# state\n")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, text):
        (self.project / "decisions" / (name + ".md")).write_text(text, encoding="utf-8")

    def run_validate(self):
        report, counts = validate_module.validate(self.root)
        self.assertIsNotNone(report)
        return report

    def messages(self, level):
        report = self.run_validate()
        items = report.errors if level == "error" else report.warnings
        return [i["message"] for i in items]

    def assertHasError(self, fragment):
        messages = self.messages("error")
        self.assertTrue(any(fragment in m for m in messages), "no error containing %r in %r" % (fragment, messages))


class ValidDecisions(RepositoryCase):
    def test_clean_repository_has_no_errors_or_warnings(self):
        self.write("first", decision_text("first", status="superseded"))
        self.write("second", decision_text("second", supersedes="first"))
        report = self.run_validate()
        self.assertEqual(report.errors, [])
        self.assertEqual(report.warnings, [])

    def test_empty_decisions_directory_is_fine(self):
        report = self.run_validate()
        self.assertEqual(report.errors, [])

    def test_crlf_and_bom_are_accepted(self):
        text = decision_text("first").replace("\n", "\r\n")
        (self.project / "decisions" / "first.md").write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))
        self.assertEqual(self.messages("error"), [])

    def test_quoted_values_are_accepted(self):
        self.write("first", decision_text("first").replace("decided_by: Test User", 'decided_by: "Test User"'))
        self.assertEqual(self.messages("error"), [])

    def test_revoked_without_successor_is_fine(self):
        self.write("first", decision_text("first", status="revoked"))
        report = self.run_validate()
        self.assertEqual(report.errors, [])
        self.assertEqual(report.warnings, [])


class RealWorldShapes(RepositoryCase):
    def test_supersedes_block_list_merging_two_decisions(self):
        self.write("a", decision_text("a", status="superseded"))
        self.write("b", decision_text("b", status="superseded"))
        self.write("c", decision_text("c", supersedes=["a", "b"]))
        report = self.run_validate()
        self.assertEqual(report.errors, [])
        self.assertEqual(report.warnings, [])

    def test_supersedes_inline_list(self):
        self.write("a", decision_text("a", status="superseded"))
        self.write("b", decision_text("b", status="superseded"))
        self.write("c", decision_text("c", extra="supersedes: [a, b]"))
        report = self.run_validate()
        self.assertEqual(report.errors, [])
        self.assertEqual(report.warnings, [])

    def test_splitting_one_decision_into_two_is_a_warning_not_an_error(self):
        self.write("a", decision_text("a", status="superseded"))
        self.write("b", decision_text("b", supersedes="a"))
        self.write("c", decision_text("c", supersedes="a"))
        self.assertEqual(self.messages("error"), [])
        self.assertTrue(any("more than one decision (b, c)" in m for m in self.messages("warning")))

    def test_superseded_by_agreeing_with_supersedes(self):
        self.write("a", decision_text("a", status="superseded", extra="superseded_by: b"))
        self.write("b", decision_text("b", supersedes="a"))
        report = self.run_validate()
        self.assertEqual(report.errors, [])
        self.assertEqual(report.warnings, [])

    def test_superseded_by_without_matching_supersedes_is_a_warning(self):
        self.write("a", decision_text("a", status="superseded", extra="superseded_by: b"))
        self.write("b", decision_text("b"))
        self.assertEqual(self.messages("error"), [])
        self.assertTrue(any("does not list 'a' in supersedes" in m for m in self.messages("warning")))

    def test_superseded_by_on_a_valid_decision_is_a_warning(self):
        self.write("a", decision_text("a", status="valid", extra="superseded_by: b"))
        self.write("b", decision_text("b", supersedes="a"))
        self.assertTrue(any("still valid" in m for m in self.messages("warning")))

    def test_chinese_sections_are_accepted(self):
        self.write("first", decision_text("first", body=ZH_BODY))
        report = self.run_validate()
        self.assertEqual(report.errors, [])
        self.assertEqual(report.warnings, [])

    def test_missing_chinese_section_is_named_in_chinese(self):
        body = ZH_BODY.replace("## 推翻条件\n如果 X。\n", "")
        self.write("first", decision_text("first", body=body))
        self.assertTrue(any("推翻条件" in m for m in self.messages("warning")))
        self.assertFalse(any("Overturn signal" in m for m in self.messages("warning")))

    def test_unrecognised_sections(self):
        self.write("first", decision_text("first", body="\n# T\n\n## Something else\ntext\n"))
        self.assertTrue(any("none of the expected sections" in m for m in self.messages("warning")))


class FrontmatterErrors(RepositoryCase):
    def test_missing_frontmatter(self):
        self.write("first", GOOD_BODY)
        self.assertHasError("missing frontmatter")

    def test_unterminated_frontmatter(self):
        self.write("first", "---\nproject: demo\n")
        self.assertHasError("unterminated frontmatter")

    def test_missing_required_field(self):
        text = decision_text("first").replace("decided_by: Test User\n", "")
        self.write("first", text)
        self.assertHasError("missing required field 'decided_by'")

    def test_bad_status(self):
        self.write("first", decision_text("first", status="pending"))
        self.assertHasError("is not one of")

    def test_bad_date(self):
        self.write("first", decision_text("first").replace("2026-09-01", "2026-13-40"))
        self.assertHasError("not a date")

    def test_project_mismatch(self):
        self.write("first", decision_text("first", project="other"))
        self.assertHasError("but the file is under projects/demo/")

    def test_decision_does_not_match_file_name(self):
        self.write("first", decision_text("renamed"))
        self.assertHasError("but the file name is 'first'")

    def test_duplicate_key(self):
        self.write("first", decision_text("first", extra="status: valid"))
        self.assertHasError("appears more than once")

    def test_unparseable_line(self):
        self.write("first", decision_text("first", extra="this is not a key value line"))
        self.assertHasError("is not 'key: value'")

    def test_self_supersede(self):
        self.write("first", decision_text("first", supersedes="first"))
        self.assertHasError("cannot be listed in its own supersedes")


class HistoryErrors(RepositoryCase):
    def test_supersedes_missing_target(self):
        self.write("second", decision_text("second", supersedes="ghost"))
        self.assertHasError("does not exist")

    def test_supersedes_target_still_valid(self):
        self.write("first", decision_text("first", status="valid"))
        self.write("second", decision_text("second", supersedes="first"))
        self.assertHasError("still marked valid")

    def test_dangling_superseded_by(self):
        self.write("first", decision_text("first", status="superseded", extra="superseded_by: ghost"))
        self.assertHasError("superseded_by 'ghost'")

    def test_cycle_through_a_list(self):
        self.write("first", decision_text("first", status="superseded", supersedes=["second"]))
        self.write("second", decision_text("second", status="superseded", supersedes=["first"]))
        self.assertHasError("cycle")

    def test_self_in_supersedes_list(self):
        self.write("first", decision_text("first", supersedes=["first"]))
        self.assertHasError("cannot be listed in its own supersedes")

    def test_list_item_under_a_scalar_key(self):
        text = decision_text("first").replace("status: valid", "status: valid\n  - stray")
        self.write("first", text)
        self.assertHasError("is not 'key: value'")

    def test_cycle(self):
        self.write("first", decision_text("first", status="superseded", supersedes="second"))
        self.write("second", decision_text("second", status="superseded", supersedes="first"))
        self.assertHasError("cycle")

    def test_supersedes_in_another_project_is_not_found(self):
        other = self.root / "projects" / "other" / "decisions"
        other.mkdir(parents=True)
        (self.root / "projects" / "other" / "README.md").write_text("# other\n")
        (self.root / "projects" / "other" / "state.md").write_text("# state\n")
        (other / "elsewhere.md").write_text(decision_text("elsewhere", project="other", status="superseded"))
        self.write("second", decision_text("second", supersedes="elsewhere"))
        self.assertHasError("does not exist")


class Warnings(RepositoryCase):
    def test_missing_section(self):
        body = GOOD_BODY.replace("## Overturn signal\nIf X.\n", "")
        self.write("first", decision_text("first", body=body))
        self.assertTrue(any("Overturn signal" in m for m in self.messages("warning")))
        self.assertEqual(self.messages("error"), [])

    def test_unknown_field(self):
        self.write("first", decision_text("first", extra="aliases: a, b"))
        self.assertTrue(any("unknown frontmatter field 'aliases'" in m for m in self.messages("warning")))

    def test_superseded_without_successor(self):
        self.write("first", decision_text("first", status="superseded"))
        self.assertTrue(any("no decision supersedes it" in m for m in self.messages("warning")))

    def test_missing_project_files(self):
        (self.project / "state.md").unlink()
        self.assertTrue(any("missing state.md" in m for m in self.messages("warning")))

    def test_bad_id_shape(self):
        self.write("Bad_Id", decision_text("Bad_Id"))
        self.assertTrue(any("lowercase letters" in m for m in self.messages("warning")))


class CommandLine(RepositoryCase):
    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPT), str(self.root)] + list(args),
            capture_output=True,
            text=True,
        )

    def test_exit_zero_when_clean(self):
        self.write("first", decision_text("first"))
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("0 error(s)", result.stdout)

    def test_exit_one_on_error(self):
        self.write("first", decision_text("first", status="pending"))
        self.assertEqual(self.run_cli().returncode, 1)

    def test_strict_fails_on_warning(self):
        self.write("first", decision_text("first", extra="aliases: a"))
        self.assertEqual(self.run_cli().returncode, 0)
        self.assertEqual(self.run_cli("--strict").returncode, 1)

    def test_json_output(self):
        self.write("first", decision_text("first", status="pending"))
        result = self.run_cli("--json")
        data = json.loads(result.stdout)
        self.assertFalse(data["ok"])
        self.assertEqual(data["decisions"], 1)
        self.assertEqual(len(data["errors"]), 1)

    def test_exit_two_without_projects_directory(self):
        empty = tempfile.mkdtemp()
        result = subprocess.run([sys.executable, str(SCRIPT), empty], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)


class Installer(unittest.TestCase):
    def test_new_repository_from_installer_validates_clean(self):
        with tempfile.TemporaryDirectory() as home:
            repository = os.path.join(home, "cairn")
            env = dict(os.environ, HOME=home)
            install = subprocess.run(
                [
                    "bash",
                    str(ROOT / "install.sh"),
                    "--identity",
                    "Test User",
                    "--project",
                    "demo",
                    "--repository",
                    repository,
                    "--skills-dir",
                    os.path.join(home, "skills"),
                ],
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(install.returncode, 0, install.stderr)
            result = subprocess.run(
                [sys.executable, os.path.join(repository, "scripts", "validate.py")],
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("0 error(s), 0 warning(s)", result.stdout)


if __name__ == "__main__":
    unittest.main()
