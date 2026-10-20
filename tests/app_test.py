from __future__ import annotations

import subprocess
import sys
import unittest
import argparse
import copy
import json
import pathlib

from app import reduce_jobs


def _run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "app.py", *arguments], capture_output=True, text=True, check=False)


class StarterTests(unittest.TestCase):
    def testCli_whenHelpRequested_returnsUsage(self) -> None:
        result = _run_cli("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("--input", result.stdout)

    def testCli_whenInputMissing_reportsReadableError(self) -> None:
        result = _run_cli("--input", "inputs/does-not-exist.json")
        self.assertEqual(result.returncode, 2)
        self.assertIn("error:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def testCli_whenJsonMalformed_reportsReadableError(self) -> None:
        result = _run_cli("--input", "inputs/malformed-input.txt")
        self.assertEqual(result.returncode, 2)
        self.assertIn("error:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def testCli_primary(self) -> None:
        result = _run_cli("--input", "inputs/primary.json")
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["summary"], {"accepted_events": 7, "rejected_events": 6})
        self.assertEqual(output["jobs"], [
            dict(job_id="j1", state="failed", attempts=2, next_start_at=None),
            dict(job_id="j2", state="succeeded", attempts=1, next_start_at=None),
            dict(job_id="j3", state="cancelled", attempts=0, next_start_at=None),
        ])
        self.assertEqual([item["row"] for item in output["audit"] if not item["accepted"]],
                         [4, 6, 9, 10, 12, 13])


class ReducerTests(unittest.TestCase):
    def run_events(self, events, maximum=2, backoff=5):
        return reduce_jobs(dict(policy=dict(max_attempts=maximum, backoff_seconds=backoff),
                                jobs=[dict(job_id="x")], events=events), argparse.Namespace())

    def event(self, identity, at, kind, job="x"):
        return dict(event_id=identity, at=at, type=kind, job_id=job)

    def test_retry_boundary_and_terminal_immutability(self):
        result = self.run_events([
            self.event("a", 0, "start"), self.event("b", 1, "fail"),
            self.event("c", 5, "start"), self.event("d", 6, "start"),
            self.event("e", 7, "fail"), self.event("f", 8, "success"),
        ])
        self.assertEqual([a["accepted"] for a in result["audit"]], [True, True, False, True, True, False])
        self.assertEqual(result["audit"][1]["job"]["next_start_at"], 6)
        self.assertEqual(result["jobs"][0]["state"], "failed")
        self.assertEqual(result["jobs"][0]["attempts"], 2)
        self.assertEqual(result["audit"][4]["job"], result["audit"][5]["job"])

    def test_rejected_unknown_job_advances_clock_and_reserves_id(self):
        result = self.run_events([
            self.event("a", 10, "start", "missing"),
            self.event("b", 9, "start"), self.event("a", 10, "start"),
            self.event("c", 10, "start"),
        ])
        self.assertEqual([a["accepted"] for a in result["audit"]], [False, False, False, True])
        self.assertIn("watermark", result["audit"][1]["reason"])
        self.assertIn("duplicate", result["audit"][2]["reason"])

    def test_malformed_events_do_not_crash_or_discard_work(self):
        result = self.run_events([
            self.event("a", 0, "start"), None, [], {},
            self.event("b", True, "success"),
            dict(event_id=[], at=1, job_id={}, type=[]),
            self.event("c", 2, "success"),
        ])
        self.assertEqual(len(result["audit"]), 7)
        self.assertEqual(result["summary"], dict(accepted_events=2, rejected_events=5))
        self.assertEqual(result["jobs"][0]["state"], "succeeded")

    def test_zero_backoff_equal_times(self):
        result = self.run_events([
            self.event("a", 0, "start"), self.event("b", 0, "fail"),
            self.event("c", 0, "start"), self.event("d", 0, "success"),
        ], backoff=0)
        self.assertEqual(result["summary"]["accepted_events"], 4)
        self.assertEqual(result["jobs"][0]["state"], "succeeded")

    def test_secondary_and_purity(self):
        payload = json.loads(pathlib.Path("inputs/secondary.json").read_text())
        original = copy.deepcopy(payload)
        first = reduce_jobs(payload, argparse.Namespace())
        self.assertEqual(first, reduce_jobs(payload, argparse.Namespace()))
        self.assertEqual(payload, original)
        self.assertEqual(first["summary"], dict(accepted_events=4, rejected_events=1))
        self.assertEqual(first["jobs"], [dict(job_id="x", state="succeeded", attempts=2, next_start_at=None)])

    def test_invalid_definitions(self):
        valid = dict(policy=dict(max_attempts=2, backoff_seconds=0), jobs=[], events=[])
        for field, value in [("max_attempts", True), ("max_attempts", 0),
                             ("backoff_seconds", False), ("backoff_seconds", -1)]:
            payload = copy.deepcopy(valid)
            payload["policy"][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                reduce_jobs(payload, argparse.Namespace())
        for jobs in [[{}], [dict(job_id="")], [dict(job_id="x"), dict(job_id="x")]]:
            with self.subTest(jobs=jobs), self.assertRaises(ValueError):
                reduce_jobs(dict(valid, jobs=jobs), argparse.Namespace())
        for field in ["jobs", "events", "policy"]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                reduce_jobs(dict(valid, **{field: None}), argparse.Namespace())

    def test_empty_and_sorted_jobs(self):
        payload = dict(policy=dict(max_attempts=1, backoff_seconds=0), jobs=[], events=[])
        self.assertEqual(reduce_jobs(payload, argparse.Namespace()),
                         dict(jobs=[], audit=[], summary=dict(accepted_events=0, rejected_events=0)))
        payload["jobs"] = [dict(job_id="z"), dict(job_id="a")]
        self.assertEqual([job["job_id"] for job in reduce_jobs(payload, argparse.Namespace())["jobs"]], ["a", "z"])

    def test_cancel_and_invalid_transitions(self):
        result = self.run_events([self.event("a", 0, "success"), self.event("b", 0, "fail"),
                                  self.event("c", 0, "cancel"), self.event("d", 1, "start")])
        self.assertEqual([a["accepted"] for a in result["audit"]], [False, False, True, False])
        self.assertEqual(result["jobs"][0], dict(job_id="x", state="cancelled", attempts=0, next_start_at=None))


if __name__ == "__main__":
    unittest.main()
