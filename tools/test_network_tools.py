import json
import subprocess
import tempfile
import unittest
from pathlib import Path
import gateway_policy as policy
import network_probe as probe


class ProbeTests(unittest.TestCase):
    def runner(self, commands):
        def run(command, **unused):
            commands.append(command)
            transfers = command.count("--write-out")
            rows = []
            for i in range(transfers):
                rows.append(probe.MARKER + json.dumps({"exitcode": 0, "http_code": 204,
                    "time_namelookup": .1, "time_connect": .3, "time_appconnect": .6,
                    "time_starttransfer": .7, "time_total": .8, "num_connects": 1 if i == 0 else 0,
                    "url_effective": "https://user:secret@host/doc?token=private",
                    "errormsg": "Authorization: secret"}))
            return subprocess.CompletedProcess(command, 0, "\n".join(rows), "")
        return run

    def test_cold_process_and_warm_connection_cache_boundary(self):
        commands = []
        cold = probe.run_group(probe.GOOGLE, 3, False, runner=self.runner(commands))
        self.assertEqual(len(commands), 3)
        self.assertTrue(all("--fresh-connect" in command and "--no-sessionid" in command for command in commands))
        commands.clear()
        warm = probe.run_group(probe.GOOGLE, 3, True, runner=self.runner(commands))
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0].count("--next"), 3)
        self.assertEqual(len(warm["samples"]), 3)
        self.assertTrue(all(row["tls_s"] is None and row["https_ready_s"] is None for row in warm["samples"]))
        self.assertNotIn("secret", json.dumps([cold, warm]))

    def test_failure_is_retained_and_blocks_speed_acceptance(self):
        good = probe.sample({"exitcode": 0, "http_code": 204, "num_connects": 1, "time_appconnect": 1})
        bad = probe.sample({"exitcode": 28, "http_code": 0})
        old = {"measurement_policy": {}, "targets": {"google204": {"url": probe.GOOGLE,
               "cold": {"samples": [good] * 20}, "warm": {"samples": [good] * 20}}}}
        new = json.loads(json.dumps(old))
        new["targets"]["google204"]["cold"]["samples"][0] = bad
        result = probe.compare(old, new)[0]
        self.assertEqual(result["new"]["failures"], 1)
        self.assertEqual(result["new"]["success_rate"], .95)
        self.assertFalse(result["acceptance_pass"])

    def test_process_failure_keeps_requested_samples(self):
        def fail(*args, **kwargs):
            raise OSError("private details")
        group = probe.run_group(probe.GOOGLE, 2, True, runner=fail)
        self.assertEqual(len(group["samples"]), 2)
        self.assertTrue(all(not row["ok"] for row in group["samples"]))
        self.assertNotIn("private", json.dumps(group))
        self.assertFalse(probe.summarize(group)["warmup_ok"])

    def test_target_rejects_login_query_and_document(self):
        for target in ("https://u:p@tenant.feishu.cn/", "https://tenant.feishu.cn/?token=x", "https://tenant.feishu.cn/docx/id"):
            with self.assertRaises(ValueError):
                probe.targets(target)


class PolicyTests(unittest.TestCase):
    def test_preserves_rules_secrets_and_is_idempotent(self):
        source = 'secret: keep-private\r\nrules:\r\n  - DOMAIN,feishu.cn,DIRECT\r\n  - MATCH,NAS-AI\r\n'
        output = policy.candidate(source)
        self.assertEqual(policy.candidate(output), output)
        self.assertIn('secret: keep-private\r\n', output)
        self.assertTrue(output.endswith('  - DOMAIN,feishu.cn,DIRECT\r\n  - MATCH,NAS-AI\r\n'))
        self.assertLess(output.index(policy.RULE), output.index('DOMAIN,feishu'))

    def test_existing_exact_rule_promoted_before_match(self):
        source = 'rules:\n- MATCH,NAS-AI\n- "' + policy.RULE + '"\n'
        output = policy.candidate(source)
        self.assertEqual(output.count(policy.RULE), 1)
        self.assertLess(output.index(policy.RULE), output.index('MATCH'))
        self.assertEqual(policy.candidate('rules:'), 'rules:\n  - ' + policy.RULE + '\n')

    def test_conflict_and_ambiguous_syntax_refused(self):
        for text in ('rules:\n- DOMAIN,' + policy.DOMAIN + ',PROXY\n', 'rules: [MATCH,DIRECT]\n', 'rules:\n- MATCH,DIRECT\nrules:\n'):
            with self.assertRaises(ValueError):
                policy.candidate(text)

    def test_source_not_overwritten_and_hash_only_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.yaml'
            target = Path(directory) / 'candidate.yaml'
            raw = b'secret: private-value\nrules:\n- MATCH,NAS-AI\n'
            source.write_bytes(raw)
            metadata = policy.generate(source, target)
            self.assertEqual(source.read_bytes(), raw)
            self.assertNotIn('private-value', json.dumps(metadata))
            self.assertEqual(len(metadata['candidate_sha256']), 64)
            with self.assertRaises(FileExistsError):
                policy.generate(source, target)
            with self.assertRaises(ValueError):
                policy.generate(source, source)


if __name__ == '__main__':
    unittest.main()
