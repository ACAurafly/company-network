"""Capacity decisions against externally observable evidence scenarios."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from codex_capacity import assess

NOW = 2000000000


def at(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


def slots(end=NOW, peak=4):
    return {"source": "redacted-slot-log", "reliable": True,
            "samples": [{"at": at(end - 300 + i * 30), "used": peak, "limit": 20} for i in range(11)]}


def fixture():
    e = {"schema_version": 1, "captured_at": at(NOW),
         "configuration": {"source": "config-snapshot", "upstream_limit": 20, "admin_limit": 30},
         "baseline": slots(), "groups": [], "pilots": []}
    report = {"samples": []}

    def group(phase, number, start):
        gid = phase + str(number)
        requests = []
        for lane in range(2):
            tid = gid + "-" + str(lane)
            report["samples"].append({"sample_id": tid, "accepted": True, "turns": [{
                "turn_id": tid, "accepted": True, "quality_pass": True, "status": "completed",
                "end_event": "turn/completed", "retry_count": 0, "error_count": 0, "anomalies": {}}]})
            serial = phase == "controlled_1" and lane == 1
            requests.append({"task_id": tid, "turn_id": tid, "gateway_request_id": tid,
                             "correlation_verified": True, "http_status": 200, "errors": [],
                             "upstream_started_at": at(start + (10 if serial else lane)),
                             "upstream_ended_at": at(start + (20 if serial else 10 + lane)),
                             "user_wait_started_at": at(start + 1) if serial else None,
                             "user_wait_ended_at": at(start + 10) if serial else None})
        e["groups"].append({"group_id": gid, "phase": phase, "user_id": "controlled" if phase.startswith("controlled") else phase[6:],
                            "limit": 1 if phase == "controlled_1" else 2,
                            "source": "access-log", "complete_logs": True, "requests": requests})

    for phase in ("controlled_1", "controlled_2"):
        for n in range(3):
            group(phase, n, NOW - 5000 + (200 if phase == "controlled_2" else 0) + n * 30)
    return e, report, group


class CapacityScenarios(unittest.TestCase):
    def test_controlled_and_admission_are_distinct_from_production(self):
        e, report, _ = fixture()
        r = assess(e, [report], NOW)
        self.assertTrue(r["controlled_verified"])
        self.assertTrue(r["pilot_eligible"])
        self.assertFalse(r["pilot_verified"])

    def test_missing_stale_and_incomplete_slots_cannot_admit(self):
        for change in (lambda e: e.update(baseline={}),
                       lambda e: e.update(baseline=slots(NOW - 61)),
                       lambda e: e["baseline"]["samples"].pop(5)):
            e, report, _ = fixture()
            change(e)
            r = assess(e, [report], NOW)
            self.assertFalse(r["pilot_eligible"])
            self.assertTrue(r["controlled_verified"])

    def test_peak_consumption_blocks_admission_even_if_average_is_low(self):
        e, report, _ = fixture()
        e["baseline"]["samples"][5]["used"] = 17
        r = assess(e, [report], NOW)
        self.assertTrue(r["capacity_assessment_complete"])
        self.assertEqual(r["baseline"]["minimum_free_slots"], 3)
        self.assertFalse(r["pilot_eligible"])

    def test_two_successful_sequential_requests_are_not_concurrent(self):
        e, report, _ = fixture()
        lane = e["groups"][-1]["requests"][1]
        lane["upstream_started_at"] = at(NOW - 4800)
        lane["upstream_ended_at"] = at(NOW - 4790)
        self.assertFalse(assess(e, [report], NOW)["controlled_verified"])

    def test_limit_one_requires_actual_user_queue_evidence(self):
        e, report, _ = fixture()
        e["groups"][0]["requests"][1]["user_wait_started_at"] = None
        self.assertFalse(assess(e, [report], NOW)["controlled_verified"])

    def test_unmatched_or_reused_turn_cannot_pass(self):
        e, report, _ = fixture()
        e["groups"][-1]["requests"][0]["turn_id"] = "missing"
        self.assertFalse(assess(e, [report], NOW)["controlled_verified"])
        e, report, _ = fixture()
        e["groups"][-1]["requests"] = deepcopy(e["groups"][0]["requests"])
        with self.assertRaises(ValueError):
            assess(e, [report], NOW)

    def pilots(self):
        e, report, group = fixture()
        for uid, start in (("5", NOW - 4000), ("2", NOW - 2000)):
            e["pilots"].append({"user_id": uid, "original_limit": 1, "candidate_limit": 2,
                                "changed_at": at(start), "observed_until": at(start + 1800),
                                "source": "change-and-monitor-log", "complete_logs": True,
                                "errors": [], "baseline": slots(start), "rollback_completed": False})
            for n in range(3):
                group("pilot_" + uid, n, start + 50 + n * 30)
        return e, report

    def test_two_users_pass_only_after_sequential_observation(self):
        e, report = self.pilots()
        self.assertTrue(assess(e, [report], NOW)["pilot_verified"])
        e["pilots"][1]["changed_at"] = at(NOW - 3000)
        self.assertFalse(assess(e, [report], NOW)["pilot_verified"])

    def test_controlled_validation_cannot_retroactively_admit_pilots(self):
        for offset in (1001, 4500):
            with self.subTest(offset=offset):
                e, report = self.pilots()
                for group in e['groups']:
                    if group['phase'].startswith('controlled'):
                        for request in group['requests']:
                            for field in ('upstream_started_at', 'upstream_ended_at', 'user_wait_started_at', 'user_wait_ended_at'):
                                if request[field] is not None:
                                    request[field] = at(datetime.fromisoformat(request[field]).timestamp() + offset)
                result = assess(e, [report], NOW)
                self.assertFalse(result['pilot_verified'])
                self.assertIn('controlled_validation_must_precede_change', result['pilots'][0]['reasons'])

    def test_controlled_groups_after_both_observations_do_not_validate_pilots(self):
        e, report = self.pilots()
        for n, group in enumerate(e['groups'][:6]):
            first = datetime.fromisoformat(group['requests'][0]['upstream_started_at']).timestamp()
            shift = NOW - 180 + n * 25 - first
            for request in group['requests']:
                for field in ('upstream_started_at', 'upstream_ended_at', 'user_wait_started_at', 'user_wait_ended_at'):
                    if request[field] is not None:
                        request[field] = at(datetime.fromisoformat(request[field]).timestamp() + shift)
        result = assess(e, [report], NOW)
        self.assertTrue(result['controlled_verified'])
        self.assertFalse(result['pilot_verified'])
        self.assertTrue(all('controlled_validation_must_precede_change' in p['reasons'] for p in result['pilots']))

    def test_user_two_cannot_be_validated_before_user_five(self):
        e, report = self.pilots()
        e['pilots'].reverse()
        result = assess(e, [report], NOW)
        self.assertFalse(result['pilot_verified'])
        self.assertIn('user5_must_pass_before_user2', result['pilots'][0]['reasons'])

    def test_controlled_limit_one_must_finish_before_limit_two(self):
        e, report, _ = fixture()
        for group in e['groups']:
            if group['phase'] == 'controlled_2':
                for request in group['requests']:
                    for field in ('upstream_started_at', 'upstream_ended_at'):
                        request[field] = at(datetime.fromisoformat(request[field]).timestamp() - 200)
        self.assertFalse(assess(e, [report], NOW)['controlled_verified'])

    def test_pilot_stream_fault_rolls_back_even_without_error_labels(self):
        for fault in ('timeout', 'disconnected', 'failed', 'missing_terminal', 'sample_timeout'):
            with self.subTest(fault=fault):
                e, report = self.pilots()
                sample = report['samples'][-1]
                turn = sample['turns'][0]
                sample['accepted'] = turn['accepted'] = False
                if fault == 'sample_timeout':
                    sample['status'] = 'timeout'
                elif fault == 'missing_terminal':
                    turn['end_event'] = None
                else:
                    turn.update(status=fault, end_event=None)
                result = assess(e, [report], NOW)
                self.assertTrue(result['rollback_required'])
                self.assertEqual(result['rollback_pending_users'], ['2'])
                self.assertFalse(result['pilot_verified'])
                e['pilots'][1]['rollback_completed'] = True
                result = assess(e, [report], NOW)
                self.assertTrue(result['rollback_required'])
                self.assertEqual(result['rollback_pending_users'], [])

    def test_quality_failure_and_explicit_cancellation_are_not_stream_faults(self):
        for status in ('completed', 'cancelled'):
            e, report = self.pilots()
            sample = report['samples'][-1]
            sample['accepted'] = False
            sample['status'] = 'not_accepted' if status == 'completed' else status
            sample['turns'][0].update(accepted=False, quality_pass=False, status=status,
                                      end_event='turn/completed' if status == 'completed' else None)
            result = assess(e, [report], NOW)
            self.assertFalse(result['pilot_verified'])
            self.assertFalse(result['rollback_required'])

    def test_short_observation_and_unrepresentative_workload_do_not_pass(self):
        for change in (lambda e: e["pilots"][0].update(observed_until=at(NOW - 2300)),
                       lambda e: e["groups"].pop()):
            e, report = self.pilots()
            change(e)
            self.assertFalse(assess(e, [report], NOW)["pilot_verified"])

    def test_all_safety_triggers_survive_later_success_and_rollback(self):
        for error in ("account_wait_timeout", "new_429", "authentication", "stream_completion"):
            e, report = self.pilots()
            e["pilots"][0]["errors"] = [error]
            r = assess(e, [report], NOW)
            self.assertTrue(r["rollback_required"])
            self.assertEqual(r["rollback_pending_users"], ["5"])
            self.assertFalse(r["pilot_verified"])
            e["pilots"][0]["rollback_completed"] = True
            r = assess(e, [report], NOW)
            self.assertTrue(r["rollback_required"])
            self.assertEqual(r["rollback_pending_users"], [])

    def test_raw_auth_or_rate_limit_status_triggers_rollback_without_error_label(self):
        for status in (401, 403, 429):
            e, report = self.pilots()
            e["groups"][-1]["requests"][0]["http_status"] = status
            r = assess(e, [report], NOW)
            self.assertTrue(r["rollback_required"])
            self.assertEqual(r["rollback_pending_users"], ["2"])
            self.assertEqual(len(r["failure_samples"]), 1)

    def test_failed_client_turn_is_counted_and_not_hidden_by_gateway_success(self):
        e, report, _ = fixture()
        report["samples"][-1]["turns"][0]["accepted"] = False
        report["samples"][-1]["turns"][0]["status"] = "cancelled"
        r = assess(e, [report], NOW)
        self.assertFalse(r["controlled_verified"])
        self.assertEqual(r["completion"]["controlled_2"]["referenced_tasks"], 6)
        self.assertEqual(r["completion"]["controlled_2"]["accepted_turns"], 5)

    def test_cli_missing_evidence_stays_unverified_and_records_reference(self):
        e, _, _ = fixture()
        e["groups"] = []
        e["baseline"] = {}
        with tempfile.TemporaryDirectory() as directory:
            src, dst = Path(directory) / "e.json", Path(directory) / "r.json"
            src.write_text(json.dumps(e), encoding="utf-8")
            proc = subprocess.run([sys.executable, str(Path(__file__).with_name("codex_capacity.py")),
                                   "--evidence", str(src), "--output", str(dst), "--now", at(NOW)], capture_output=True)
            self.assertEqual(proc.returncode, 2)
            result = json.loads(dst.read_text(encoding="utf-8"))
            self.assertFalse(result["controlled_verified"])
            self.assertFalse(result["capacity_assessment_complete"])
            self.assertEqual(result["assessed_at"], at(NOW))


if __name__ == "__main__":
    unittest.main()
