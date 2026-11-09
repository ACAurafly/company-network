"""Offline contract tests: synthetic metadata, no VPN/NAS/model calls."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import subprocess
import sys
from unittest.mock import patch

import codex_latency
import unittest

from codex_vpn_acceptance import compare, main, network_summary, observations


def fixture():
    reports, evidence = [], {}
    for side, label in (("company_lan", "company-lan"), ("external_vpn", "external-vpn")):
        rows, observations_by_id = [], {}
        for pair in range(1, 6):
            sample_id = side + str(pair)
            time = f"2026-11-09T10:0{pair}:00+00:00"
            rows.append({"sample_id": sample_id, "task": "fixed", "effort": "max", "pair": pair,
                         "model": "gpt-6.1-sol", "network": label, "started_utc": time,
                         "status": "completed", "accepted": True, "elapsed_ms": 100 if side == "company_lan" else 120,
                         "turns": [{"accepted": True, "quality_pass": True, "status": "completed",
                                    "first_visible_ms": 20, "completion_ms": 100, "retry_count": 0}]})
            observations_by_id[sample_id] = {"captured_utc": time, "location": "company_lan" if side == "company_lan" else "outside_company",
                "access_type": "cellular", "outer_active": True, "inner_active": True,
                "route_ready": True, "certificate_pin_match": True, "vpn_entry_direct": True,
                "workload_comparable": True, "difference_explained": True,
                "stage_clock": "local_monotonic_duration", "stages_ms": {"nas_connect_ms": 3 if side == "company_lan" else 5}}
        reports.append({"schema_version": 2, "provenance": codex_latency.provenance(), "runtime_version": "0.99.0", "model": "gpt-6.1-sol", "samples": rows})
        evidence[side] = {"device_id": "device-a", "account_id": "account-a", "egress_id": "egress-a", "samples": observations_by_id}
    return reports[0], reports[1], evidence


class AcceptanceTests(unittest.TestCase):
    def test_current_producer_reports_flow_through_consumer_with_real_stream(self):
        # Replace only external executable/version discovery. Real sampler main,
        # sample, subprocess pipes, stream parser and report serialization run.
        program = """
import json,sys
for line in sys.stdin:
 d=json.loads(line)
 method=d.get('method')
 if method=='initialize':
  print(json.dumps({'id':d['id'],'result':{}}),flush=True)
 if method=='thread/start':
  print(json.dumps({'id':d['id'],'result':{'thread':{'id':'thread-public'}}}),flush=True)
 if method=='turn/start':
  print(json.dumps({'id':d['id'],'result':{'turn':{'id':'turn-public'}}}),flush=True)
  for method,extra in [('item/agentMessage/delta',{'delta':'CODEX_LATENCY_OK'}),('item/completed',{'item':{'type':'agentMessage','text':'CODEX_LATENCY_OK'}}),('turn/completed',{'turn':{'id':'turn-public','status':'completed'}})]:
   print(json.dumps({'method':method,'params':{'threadId':'thread-public','turnId':'turn-public',**extra}}),flush=True)
"""
        real_popen = subprocess.Popen
        def local_process(*args, **kwargs):
            return real_popen([sys.executable, '-u', '-c', program], **kwargs)
        reports, evidence = [], {}
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            for side, label in (('company_lan', 'company-lan'), ('external_vpn', 'external-vpn')):
                output = base / (side + '.json')
                with patch('codex_latency.subprocess.run', return_value=subprocess.CompletedProcess([], 0, 'codex 0.99.0')), patch('codex_latency.subprocess.Popen', side_effect=local_process):
                    self.assertEqual(codex_latency.main(['--codex', 'offline-fixture', '--workdir', directory, '--output', str(output), '--smoke', '--efforts', 'max', '--pairs', '5', '--network', label]), 0)
                report = json.loads(output.read_text(encoding='utf-8'))
                reports.append(report)
                _, _, template = fixture()
                observation = copy.deepcopy(template[side])
                observation['samples'] = {}
                for row in report['samples']:
                    item = copy.deepcopy(template[side]['samples'][side + '1'])
                    item['captured_utc'] = row['started_utc']
                    observation['samples'][row['sample_id']] = item
                evidence[side] = observation
        result = compare(*reports, evidence)
        self.assertEqual(result['remote_business_status'], 'descriptive_screening_complete')
        self.assertEqual(result['external_vpn']['correct_complete'], 5)
        # Real producer metadata alone still cannot attest physical access.
        self.assertEqual(compare(*reports)['remote_business_status'], 'not_accepted')
        evidence['external_vpn']['samples'][reports[1]['samples'][0]['sample_id']]['captured_utc'] = '2000-01-01T00:00:00Z'
        self.assertEqual(compare(*reports, evidence)['remote_business_status'], 'not_accepted')

    def test_schema_and_manifest_gaps_do_not_claim_comparability(self):
        for change in ('legacy', 'mixed', 'future', 'missing', 'manifest', 'fixture', 'source'):
            with self.subTest(change=change):
                lan, vpn, evidence = fixture()
                if change == 'legacy':
                    lan['schema_version'] = vpn['schema_version'] = 1
                elif change in ('mixed', 'future'):
                    vpn['schema_version'] = 1 if change == 'mixed' else 99
                elif change == 'missing':
                    vpn.pop('provenance')
                else:
                    vpn['provenance'][{'manifest': 'task_manifest_sha256', 'fixture': 'fixture_sha256', 'source': 'source_sha256'}[change]] = '0' * 64
                result = compare(lan, vpn, evidence)
                self.assertEqual(result['remote_business_status'], 'not_accepted')
                self.assertTrue(all(p['vpn_minus_lan_ms'] is None for p in result['pairs']))

    def test_five_pairs_descriptive_only_and_three_stage_trigger(self):
        result = compare(*fixture())
        self.assertEqual(result["remote_business_status"], "descriptive_screening_complete")
        self.assertEqual(result["pairs"][0]["vpn_minus_lan_ms"], 20)
        self.assertIsNone(result["pairs"][0]["stage_vpn_minus_lan_ms"]["vpn_ready_ms"])
        self.assertEqual(result["retest_triggers"][0]["pairs"], 5)
        self.assertNotIn("p95", result["external_vpn"]["task_elapsed_ms"])

    def test_label_alone_is_not_external_evidence(self):
        lan, vpn, _ = fixture()
        result = compare(lan, vpn)
        self.assertEqual(result["remote_business_status"], "not_accepted")
        self.assertTrue(all(p["vpn_minus_lan_ms"] is None for p in result["pairs"]))

    def test_failures_retry_denominator_and_quality_are_retained(self):
        lan, vpn, evidence = fixture()
        bad = vpn["samples"][1]
        bad.update(status="cancelled", accepted=False, elapsed_ms=None)
        bad["turns"][0].update(retry_count=5, completion_ms=None, accepted=False)
        result = compare(lan, vpn, evidence)
        self.assertEqual(result["external_vpn"]["denominator"], 5)
        self.assertEqual(result["external_vpn"]["correct_complete"], 4)
        self.assertEqual(result["external_vpn"]["retry_count"], 5)
        self.assertEqual(result["remote_business_status"], "not_accepted")
        self.assertIsNone(result["pairs"][1]["vpn_minus_lan_ms"])
        self.assertTrue(any("only failure" in t["reason"] for t in result["retest_triggers"]))

    def test_unknown_first_visible_and_nonfinite_elapsed_not_success(self):
        for field, value in (("first_visible_ms", None), ("first_visible_ms", float("nan")), ("quality_pass", False)):
            lan, vpn, evidence = fixture()
            vpn["samples"][0]["turns"][0][field] = value
            result = compare(lan, vpn, evidence)
            self.assertEqual(result["external_vpn"]["correct_complete"], 4)
            self.assertIsNone(result["pairs"][0]["vpn_minus_lan_ms"])

    def test_comparability_conditions(self):
        for change in ("runtime", "model", "device", "account", "egress", "effort", "task", "window", "missing_pair", "duplicate", "vpn", "route", "location", "source_time", "context"):
            with self.subTest(change=change):
                lan, vpn, evidence = fixture()
                ob = evidence["external_vpn"]["samples"]["external_vpn1"]
                if change in ("runtime", "model"):
                    vpn["runtime_version" if change == "runtime" else "model"] = "different"
                elif change in ("device", "account", "egress"):
                    evidence["external_vpn"][change + "_id"] = "different"
                elif change in ("effort", "task"):
                    vpn["samples"][0][change] = "different"
                elif change == "window":
                    vpn["samples"][0]["started_utc"] = "2026-11-09T11:01:00+00:00"
                elif change == "missing_pair":
                    vpn["samples"].pop()
                elif change == "duplicate":
                    vpn["samples"].append(copy.deepcopy(vpn["samples"][0]))
                elif change == "vpn":
                    ob["inner_active"] = False
                elif change == "route":
                    ob["route_ready"] = False
                elif change == "location":
                    ob["location"] = "company_lan"
                elif change == "source_time":
                    ob["captured_utc"] = None
                else:
                    ob["workload_comparable"] = False
                result = compare(lan, vpn, evidence)
                self.assertEqual(result["remote_business_status"], "not_accepted")

    def test_unexplained_difference_triggers_retest(self):
        lan, vpn, evidence = fixture()
        evidence["external_vpn"]["samples"]["external_vpn1"]["difference_explained"] = False
        result = compare(lan, vpn, evidence)
        self.assertTrue(any("unexplained" in t["reason"] for t in result["retest_triggers"]))

    def test_network_20_each_actual_reuse_and_failure_denominator(self):
        cold = {"ok": True, "num_connects": 1, "connection_reused": False, "timing_valid": True, "https_ready_s": 1}
        warm = {"ok": True, "num_connects": 0, "connection_reused": True, "timing_valid": True, "ttfb_s": .2}
        report = {"targets": {"google204": {"cold": {"samples": [copy.deepcopy(cold) for _ in range(20)]},
                    "warm": {"warmup": {"ok": True}, "samples": [copy.deepcopy(warm) for _ in range(20)]}}}}
        result = network_summary(report)
        self.assertEqual(result["targets"]["google204"]["warm"]["status"], "sampling_complete")
        self.assertEqual(result["performance_acceptance"], "not_accepted")
        report["targets"]["google204"]["warm"]["samples"][0].update(connection_reused=False, num_connects=1)
        self.assertEqual(network_summary(report)["targets"]["google204"]["warm"]["status"], "not_accepted")
        report["targets"]["google204"]["cold"]["samples"][0]["ok"] = False
        result = network_summary(report)["targets"]["google204"]["cold"]
        self.assertEqual(result["denominator"], 20)
        self.assertEqual(result["failures"], 1)
        self.assertEqual(result["status"], "not_accepted")

    def test_cli_hash_bound_sources_no_raw_content_export(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            lan, vpn, evidence = fixture()
            manifest = {}
            source = base / "source.json"
            source.write_text('{"private":"never-copy-this"}', encoding="utf-8")
            for side, value in evidence.items():
                value.update(schema_version=1, reviewed=True, source_refs=[{"path": source.name, "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}])
                path = base / (side + ".json")
                path.write_text(json.dumps(value), encoding="utf-8")
                manifest[side] = {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for name, value in (("lan", lan), ("vpn", vpn), ("evidence", manifest)):
                (base / (name + ".json")).write_text(json.dumps(value), encoding="utf-8")
            args = ["--lan", str(base/"lan.json"), "--vpn", str(base/"vpn.json"), "--evidence", str(base/"evidence.json"), "--output", str(base/"out.json")]
            self.assertEqual(main(args), 0)
            self.assertNotIn("never-copy-this", (base/"out.json").read_text())
            source.write_text("changed", encoding="utf-8")
            self.assertEqual(main(args), 1)
            self.assertEqual(observations(manifest, base)[0], {})


if __name__ == "__main__":
    unittest.main()
