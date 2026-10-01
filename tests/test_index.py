"""Tests for template/scripts/index.py. Run with: python3 -m unittest discover -s tests"""

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "template" / "scripts"
INDEX = SCRIPTS / "index.py"
VALIDATE = SCRIPTS / "validate.py"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


index_module = load(INDEX, "cairn_index_under_test")
validate_module = load(VALIDATE, "cairn_validate_for_index_tests")

EN_BODY = """
# Use plain Markdown

## Decision
Decisions are stored as plain Markdown files. Nothing else is required.

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
# 使用普通 Markdown

## 结论
决定保存为普通 Markdown 文件。不需要其他东西。

## 为什么
因为。

## 适用范围
这里。

## 明确不做
不做那个。

## 推翻条件
如果 X。
"""


def decision(decision_id, status="valid", date="2026-09-01", body=EN_BODY, supersedes=None):
    lines = [
        "---",
        "project: demo",
        "decision: %s" % decision_id,
        "status: %s" % status,
        "decided_by: Test User",
        "decided_at: %s" % date,
    ]
    if supersedes:
        lines.append("supersedes: %s" % supersedes)
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

    def render(self):
        text, skipped, counts = index_module.render_project(validate_module, self.project)
        return text, skipped, counts

    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, str(INDEX), str(self.root)] + list(args),
            capture_output=True,
            text=True,
        )

    @property
    def index_file(self):
        return self.project / "decisions-index.md"


class Content(RepositoryCase):
    def test_only_valid_decisions_are_listed(self):
        self.write("old", decision("old", status="superseded"))
        self.write("gone", decision("gone", status="revoked"))
        self.write("current", decision("current", supersedes="old"))
        text, _, counts = self.render()
        self.assertIn(" current:", text)
        self.assertNotIn(" old:", text)
        self.assertNotIn(" gone:", text)
        self.assertEqual(counts, {"listed": 1, "omitted": 2})
        self.assertIn("2 superseded or revoked decision(s) are not listed", text)

    def test_newest_first_then_by_id(self):
        self.write("b-second", decision("b-second", date="2026-09-02"))
        self.write("a-first", decision("a-first", date="2026-09-01"))
        self.write("c-same-day", decision("c-same-day", date="2026-09-02"))
        text, _, _ = self.render()
        order = [line.split()[2].rstrip(":") for line in text.split("\n") if line.startswith("- ")]
        self.assertEqual(order, ["b-second", "c-same-day", "a-first"])

    def test_line_has_date_id_title_and_first_sentence(self):
        self.write("plain", decision("plain"))
        text, _, _ = self.render()
        self.assertIn(
            "- 2026-09-01 plain: Use plain Markdown — Decisions are stored as plain Markdown files.",
            text,
        )

    def test_chinese_decision(self):
        self.write("zh", decision("zh", body=ZH_BODY))
        text, _, _ = self.render()
        self.assertIn("- 2026-09-01 zh: 使用普通 Markdown — 决定保存为普通 Markdown 文件。", text)

    def test_multi_line_paragraph_is_joined(self):
        body = EN_BODY.replace(
            "Decisions are stored as plain Markdown files. Nothing else is required.",
            "Decisions are stored\nas plain Markdown files. Nothing else.",
        )
        self.write("wrapped", decision("wrapped", body=body))
        text, _, _ = self.render()
        self.assertIn("— Decisions are stored as plain Markdown files.", text)

    def test_long_sentence_is_shortened(self):
        long_text = "word " * 100
        body = EN_BODY.replace("Decisions are stored as plain Markdown files. Nothing else is required.", long_text)
        self.write("long", decision("long", body=body))
        text, _, _ = self.render()
        line = [l for l in text.split("\n") if " long:" in l][0]
        self.assertTrue(line.endswith("…"))
        self.assertLess(len(line), 250)

    def test_placeholder_decision_has_no_summary(self):
        body = EN_BODY.replace(
            "Decisions are stored as plain Markdown files. Nothing else is required.",
            "To be validated",
        )
        self.write("tbv", decision("tbv", body=body))
        text, _, _ = self.render()
        line = [l for l in text.split("\n") if " tbv:" in l][0]
        self.assertNotIn("—", line)

    def test_missing_decision_section_has_no_summary(self):
        self.write("nosec", decision("nosec", body="\n# Only a title\n"))
        text, _, _ = self.render()
        line = [l for l in text.split("\n") if " nosec:" in l][0]
        self.assertTrue(line.endswith("Only a title"))

    def test_missing_title_falls_back_to_id(self):
        self.write("untitled", decision("untitled", body="\n## Decision\nDo it.\n"))
        text, _, _ = self.render()
        self.assertIn("- 2026-09-01 untitled: untitled — Do it.", text)

    def test_empty_project(self):
        text, _, counts = self.render()
        self.assertIn("No valid decisions yet.", text)
        self.assertEqual(counts["listed"], 0)

    def test_unparseable_file_is_skipped_not_fatal(self):
        self.write("good", decision("good"))
        self.write("broken", "no frontmatter here")
        text, skipped, _ = self.render()
        self.assertIn(" good:", text)
        self.assertEqual([p.stem for p in skipped], ["broken"])


class CommandLine(RepositoryCase):
    def test_writes_index_and_second_run_is_unchanged(self):
        self.write("first", decision("first"))
        first = self.run_cli()
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn("Wrote", first.stdout)
        self.assertTrue(self.index_file.is_file())
        before = self.index_file.read_text(encoding="utf-8")
        second = self.run_cli()
        self.assertIn("Unchanged", second.stdout)
        self.assertEqual(before, self.index_file.read_text(encoding="utf-8"))

    def test_check_passes_when_fresh_and_fails_when_stale_or_missing(self):
        self.write("first", decision("first"))
        missing = self.run_cli("--check")
        self.assertEqual(missing.returncode, 1)
        self.assertIn("missing", missing.stdout)
        self.run_cli()
        self.assertEqual(self.run_cli("--check").returncode, 0)
        self.write("second", decision("second", date="2026-09-05"))
        stale = self.run_cli("--check")
        self.assertEqual(stale.returncode, 1)
        self.assertIn("out of date", stale.stdout)

    def test_check_does_not_write(self):
        self.write("first", decision("first"))
        self.run_cli("--check")
        self.assertFalse(self.index_file.exists())

    def test_stdout_does_not_write(self):
        self.write("first", decision("first"))
        result = self.run_cli("--stdout")
        self.assertIn("Decision index: demo", result.stdout)
        self.assertFalse(self.index_file.exists())

    def test_underscore_projects_are_skipped(self):
        template = self.root / "projects" / "_template" / "decisions"
        template.mkdir(parents=True)
        self.run_cli()
        self.assertFalse((self.root / "projects" / "_template" / "decisions-index.md").exists())

    def test_exit_two_without_projects_directory(self):
        empty = tempfile.mkdtemp()
        result = subprocess.run([sys.executable, str(INDEX), empty], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)

    def test_removing_a_decision_removes_its_line(self):
        self.write("first", decision("first"))
        self.write("second", decision("second"))
        self.run_cli()
        (self.project / "decisions" / "second.md").unlink()
        self.run_cli()
        self.assertNotIn(" second:", self.index_file.read_text(encoding="utf-8"))


class WithValidator(RepositoryCase):
    def validate(self):
        report, _ = validate_module.validate(self.root)
        return report

    def test_validator_does_not_treat_the_index_as_a_decision(self):
        self.write("first", decision("first"))
        self.run_cli()
        report = self.validate()
        self.assertEqual(report.errors, [])
        self.assertEqual(report.warnings, [])

    def test_validator_warns_when_the_index_is_stale(self):
        self.write("first", decision("first"))
        self.run_cli()
        self.write("second", decision("second", date="2026-09-05"))
        warnings = [w["message"] for w in self.validate().warnings]
        self.assertTrue(any("index is out of date" in w for w in warnings), warnings)

    def test_validator_is_silent_when_there_is_no_index(self):
        self.write("first", decision("first"))
        self.assertEqual(self.validate().warnings, [])


class Installer(unittest.TestCase):
    def test_fresh_repository_has_an_index_and_validates_clean(self):
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
            index_file = Path(repository) / "projects" / "demo" / "decisions-index.md"
            self.assertTrue(index_file.is_file())
            self.assertIn("No valid decisions yet.", index_file.read_text(encoding="utf-8"))
            check = subprocess.run(
                [sys.executable, os.path.join(repository, "scripts", "index.py"), repository, "--check"],
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
            validate = subprocess.run(
                [sys.executable, os.path.join(repository, "scripts", "validate.py"), repository],
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(validate.returncode, 0, validate.stdout)
            self.assertIn("0 error(s), 0 warning(s)", validate.stdout)


if __name__ == "__main__":
    unittest.main()
