"""Sanitized external stream fixtures and isolated subprocess boundary tests."""
import json
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from codex_latency import AppServer, SampleError, Turn, summarize


def notification(method, **params):
    return {"method": method, "params": {"threadId": "thread-public", "turnId": "turn-public", **params}}


class StreamTests(unittest.TestCase):
    def turn(self):
        t = Turn("thread-public", 7, 10)
        t.turn_id = "turn-public"
        return t

    def complete(self, t):
        t.observe(11, notification("item/agentMessage/delta", delta="OK"))
        t.observe(12, notification("item/completed", item={"type": "agentMessage", "text": "OK"}))
        t.observe(13, notification("turn/completed", turn={"id": "turn-public", "status": "completed"}))
        return t.record("OK", False)

    def test_visible_delta_is_required_even_when_final_text_exists(self):
        t = self.turn()
        t.observe(11, notification("item/completed", item={"type": "agentMessage", "text": "OK"}))
        t.observe(12, notification("turn/completed", turn={"id": "turn-public", "status": "completed"}))
        r = t.record("OK", False)
        self.assertTrue(r["quality_pass"])
        self.assertFalse(r["accepted"])
        self.assertIn("first_visible_ms", r["missing"])

    def test_missing_terminal_is_not_success(self):
        t = self.turn()
        t.observe(11, notification("item/agentMessage/delta", delta="OK"))
        t.observe(12, notification("item/completed", item={"type": "agentMessage", "text": "OK"}))
        r = t.record("OK", False)
        self.assertIsNone(r["completion_ms"])
        self.assertFalse(r["accepted"])

    def test_foreign_turn_early_and_duplicate_terminal_cannot_change_timing(self):
        t = self.turn()
        t.observe(9, notification("item/agentMessage/delta", delta="early"))
        t.observe(10.2, notification("item/agentMessage/delta", turnId="old-turn", delta="stale"))
        self.complete(t)
        t.observe(100, notification("turn/completed", turn={"id": "turn-public", "status": "failed"}))
        t.observe(101, notification("item/agentMessage/delta", delta="duplicate"))
        r = t.record("OK", False)
        self.assertEqual(r["completion_ms"], 3000)
        self.assertEqual(r["first_visible_ms"], 1000)
        self.assertEqual(r["status"], "completed")
        self.assertEqual(r["anomalies"], {"before_submit": 1, "foreign_turn": 1, "after_terminal": 2})

    def test_retry_signals_and_sensitive_values_are_not_persisted(self):
        t = self.turn()
        t.observe(10.1, notification("error", willRetry=True, error={"message": "SECRET_BEARER"}))
        t.observe(10.2, notification("thread/tokenUsage/updated", tokenUsage={"last": {"inputTokens": 20, "outputTokens": 2, "secret": "SECRET_CONFIG"}}))
        r = self.complete(t)
        self.assertEqual(r["retry_count"], 1)
        self.assertEqual(r["observed_attempts"], 2)
        self.assertEqual(r["usage"], {"inputTokens": 20, "outputTokens": 2})
        self.assertNotIn("SECRET", json.dumps(r))
        self.assertNotIn('"OK"', json.dumps(r))

    def test_cancelled_and_failed_samples_remain_in_denominator(self):
        good = {"task": "fixed", "effort": "max", "pair": 1, "accepted": True, "status": "completed", "elapsed_ms": 4000, "turns": [self.complete(self.turn())]}
        rows = [good]
        for status in ("cancelled", "timeout", "disconnected"):
            rows.append({**good, "accepted": False, "status": status, "turns": []})
        summary = summarize(rows)
        group = summary["groups"][0]
        self.assertEqual(group["denominator"], 4)
        self.assertEqual(group["accepted"], 1)
        self.assertEqual(group["metrics_correct_complete_only"]["task_elapsed_ms"]["n"], 1)
        self.assertFalse(summary["pairs"][0]["both_accepted"])


class ProcessBoundaryTests(unittest.TestCase):
    def test_real_local_subprocess_stream_and_cleanup_without_network(self):
        # A real child process emits a sanitized app-server-shaped stream.
        # Launch interception only replaces the executable; pipes, deadlines,
        # framing, turn parsing and Windows Job cleanup remain real.
        program = '''
import json,sys
for line in sys.stdin:
 d=json.loads(line)
 if d.get("method")=="initialize":
  print(json.dumps({"id":d["id"],"result":{}}),flush=True)
 if d.get("method")=="turn/start":
  print(json.dumps({"id":d["id"],"result":{"turn":{"id":"turn-public"}}}),flush=True)
  for method,extra in [("item/agentMessage/delta",{"delta":"OK"}),("item/completed",{"item":{"type":"agentMessage","text":"OK"}}),("turn/completed",{"turn":{"id":"turn-public","status":"completed"}})]:
   print(json.dumps({"method":method,"params":{"threadId":"thread-public","turnId":"turn-public",**extra}}),flush=True)
'''
        real_popen = subprocess.Popen
        def local_process(*args, **kwargs):
            return real_popen([sys.executable, "-u", "-c", program], **kwargs)
        with patch("codex_latency.subprocess.Popen", side_effect=local_process):
            app = AppServer("unused", Path("unused"))
        try:
            self.assertEqual(app.rpc("initialize", {}, timeout=5), {})
            result = app.run_turn("thread-public", "medium", "public test", "OK", False, 5)
            self.assertTrue(result["accepted"])
        finally:
            app.close()
        self.assertIsNotNone(app.p.poll())

    def test_start_error_is_sanitized(self):
        with patch("codex_latency.subprocess.Popen", side_effect=OSError("SECRET_PATH")):
            with self.assertRaisesRegex(SampleError, "^subprocess_start_failed$"):
                AppServer("private", Path("fixture"))

    def bare_server(self):
        app = AppServer.__new__(AppServer)
        app.q = queue.Queue()
        return app

    def test_disconnect_and_timeout_have_bounded_public_categories(self):
        app = self.bare_server()
        app.q.put((time.perf_counter(), {"_closed": True}))
        with self.assertRaisesRegex(SampleError, "^disconnected$"):
            app.receive(time.perf_counter()+1)
        with self.assertRaisesRegex(SampleError, "^timeout$"):
            app.receive(time.perf_counter()+0.001)

    def test_server_approval_request_is_rejected_without_waiting(self):
        app = self.bare_server()
        sent = []
        app.write = sent.append
        with self.assertRaisesRegex(SampleError, "^server_request_denied$"):
            app.server_request({"id": 88, "method": "item/commandExecution/requestApproval", "params": {"command": "SECRET_COMMAND"}})
        self.assertEqual(sent[0]["id"], 88)
        self.assertNotIn("SECRET", json.dumps(sent))

    def test_dynamic_tool_only_serves_explicit_fixture(self):
        app = self.bare_server()
        sent = []
        app.write = sent.append
        turn = Turn("thread-public", 7, 0)
        turn.turn_id = "turn-public"
        with tempfile.TemporaryDirectory() as directory:
            app.fixture = Path(directory)/"numbers.txt"
            app.fixture.write_text("17\n23\n41\n", encoding="utf-8")
            event = {"id": 22, "method": "item/tool/call", "params": {"threadId": "thread-public", "turnId": "turn-public", "tool": "read_fixture", "arguments": {"key": "numbers"}}}
            app.server_request(event, turn)
            self.assertTrue(sent[-1]["result"]["success"])
            self.assertEqual(sent[-1]["result"]["contentItems"][0]["text"], "17\n23\n41\n")
            event["params"]["arguments"] = {"path": "../../secret"}
            app.server_request(event, turn)
            self.assertFalse(sent[-1]["result"]["success"])
            self.assertNotIn("secret", json.dumps(sent))


if __name__ == "__main__":
    unittest.main()
