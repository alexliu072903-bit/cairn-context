"""Runs read.py against the shared conformance cases.

Another implementation (a TypeScript reader, a web service) is correct when it
produces the same result for every case in tests/conformance/cases/. Message text
is informational and is not compared; errors and warnings are compared by level and path.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
READ = ROOT / "template" / "scripts" / "read.py"
CONFORMANCE = ROOT / "tests" / "conformance"


def comparable(result):
    """Reduce a read.py result to the parts every implementation must agree on."""
    result = json.loads(json.dumps(result))
    for key in ("errors", "warnings"):
        result[key] = sorted((p["level"], p["path"]) for p in result[key])
    return result


class ConformanceTests(unittest.TestCase):
    def test_every_case_matches(self):
        cases = sorted((CONFORMANCE / "cases").glob("*.json"))
        self.assertGreaterEqual(len(cases), 10)
        for case_file in cases:
            with self.subTest(case=case_file.stem):
                case = json.loads(case_file.read_text(encoding="utf-8"))
                command = [sys.executable, str(READ), str(CONFORMANCE / case["repository"])]
                for project in case["args"].get("projects", []):
                    command += ["--project", project]
                if case["args"].get("since"):
                    command += ["--since", case["args"]["since"]]
                if case["args"].get("statuses"):
                    command += ["--status", ",".join(case["args"]["statuses"])]
                result = subprocess.run(command, capture_output=True, text=True)
                self.assertEqual(result.returncode, case["exit_code"])
                self.assertEqual(
                    comparable(json.loads(result.stdout)), comparable(case["expected"])
                )


if __name__ == "__main__":
    unittest.main()
