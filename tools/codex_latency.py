"""Installed Codex app-server latency sampler. Python 3.11+, standard library.

Only allowlisted metadata is persisted; prompts, config, raw events and stderr
stay in memory. All test conversations are ephemeral and use existing auth.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import queue
import signal
import statistics
import subprocess
import tempfile
import threading
import time
import uuid

MODEL = "gpt-6.1-sol"
FIXTURE = "17\n23\n41\n"
TASKS = {
    "fixed": [("Reply exactly CODEX_LATENCY_OK and nothing else. Do not use tools.", "CODEX_LATENCY_OK", False)],
    "calculate": [("Call read_fixture with key numbers. Sum its three integers. Reply only SUM=<sum>, substituting the computed integer for <sum>.", "SUM=81", True)],
    "multi": [
        ("Call read_fixture with key numbers. Remember its three integers. Reply only FIRST=<first integer>, substituting the actual first integer.", "FIRST=17", True),
        ("Using the earlier tool result, reply only SECOND=<second integer>, substituting the actual second integer. Do not call tools.", "SECOND=23", False),
        ("Using the earlier tool result, reply only SUM=<sum>, substituting the computed sum of all three integers. Do not call tools.", "SUM=81", False),
    ],
}
USAGE = ("inputTokens", "cachedInputTokens", "cacheWriteInputTokens", "outputTokens", "reasoningOutputTokens", "totalTokens")


class SampleError(Exception):
    """Public category only; never include subprocess/server text."""


class WindowsJob:
    """Own descendants even if the app-server root exits before cleanup."""
    def __init__(self, process):
        import ctypes as c
        from ctypes import wintypes as w
        class Basic(c.Structure):
            _fields_ = [("per_process", c.c_int64), ("per_job", c.c_int64), ("flags", w.DWORD),
                        ("min_ws", c.c_size_t), ("max_ws", c.c_size_t), ("active", w.DWORD),
                        ("affinity", c.c_size_t), ("priority", w.DWORD), ("scheduling", w.DWORD)]
        class IO(c.Structure):
            _fields_ = [(name, c.c_uint64) for name in ("read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]
        class Extended(c.Structure):
            _fields_ = [("basic", Basic), ("io", IO), ("process_memory", c.c_size_t),
                        ("job_memory", c.c_size_t), ("peak_process", c.c_size_t), ("peak_job", c.c_size_t)]
        self.api = c.WinDLL("kernel32", use_last_error=True)
        self.api.CreateJobObjectW.argtypes = (c.c_void_p, w.LPCWSTR)
        self.api.CreateJobObjectW.restype = w.HANDLE
        self.api.SetInformationJobObject.argtypes = (w.HANDLE, c.c_int, c.c_void_p, w.DWORD)
        self.api.AssignProcessToJobObject.argtypes = (w.HANDLE, w.HANDLE)
        self.api.CloseHandle.argtypes = (w.HANDLE,)
        self.handle = self.api.CreateJobObjectW(None, None)
        info = Extended()
        info.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.handle or not self.api.SetInformationJobObject(self.handle, 9, c.byref(info), c.sizeof(info)) or not self.api.AssignProcessToJobObject(self.handle, w.HANDLE(int(process._handle))):
            if self.handle:
                self.api.CloseHandle(self.handle)
            raise SampleError("owned_process_job_unavailable")

    def close(self):
        self.api.CloseHandle(self.handle)


class Turn:
    def __init__(self, thread_id, request_id, start):
        self.thread_id, self.request_id, self.start = thread_id, request_id, start
        self.turn_id = None
        self.first = self.end = None
        self.status = "pending"
        self.text = ""
        self.final = None
        self.retry_count = 0
        self.error_count = 0
        self.error_categories = Counter()
        self.http_statuses = Counter()
        self.tools = []
        self.tool_items = []
        self.usage = None
        self.anomalies = Counter()

    def observe(self, at, event):
        """Consume external notifications, rejecting unrelated/corrupt sequences."""
        p = event.get("params", {})
        method = event.get("method")
        if p.get("threadId") != self.thread_id:
            return
        turn_id = p.get("turnId") or p.get("turn", {}).get("id")
        if not turn_id:
            return
        if self.turn_id is None:
            self.turn_id = turn_id
        if turn_id != self.turn_id:
            self.anomalies["foreign_turn"] += 1
            return
        if at < self.start:
            self.anomalies["before_submit"] += 1
            return
        if self.end is not None:
            self.anomalies["after_terminal"] += 1
            return
        elapsed = (at - self.start) * 1000
        if method == "item/agentMessage/delta":
            delta = p.get("delta", "")
            if isinstance(delta, str) and delta:
                if self.first is None:
                    self.first = elapsed
                self.text += delta
        elif method == "item/completed":
            item = p.get("item", {})
            if item.get("type") == "agentMessage":
                self.final = item.get("text", "")
            elif item.get("type") in ("commandExecution", "fileChange", "mcpToolCall", "dynamicToolCall", "webSearch"):
                status = item.get("status")
                self.tool_items.append({"type": item["type"], "status": status if status in ("completed", "failed", "declined", "inProgress") else "unknown"})
        elif method == "thread/tokenUsage/updated":
            raw = p.get("tokenUsage", {}).get("last", {})
            self.usage = {k: raw[k] for k in USAGE if isinstance(raw.get(k), int) and not isinstance(raw[k], bool)}
        elif method == "error":
            self.error_count += 1
            info = p.get("error", {}).get("codexErrorInfo")
            known = ("httpConnectionFailed", "responseStreamConnectionFailed", "responseStreamDisconnected", "responseTooManyFailedAttempts", "contextWindowExceeded", "usageLimitExceeded", "unauthorized")
            category = next((k for k in known if (isinstance(info, dict) and k in info) or info == k), "other")
            self.error_categories[category] += 1
            detail = info.get(category, {}) if isinstance(info, dict) else {}
            code = detail.get("httpStatusCode") if isinstance(detail, dict) else None
            if isinstance(code, int) and 100 <= code <= 599:
                self.http_statuses[str(code)] += 1
            if p.get("willRetry") is True:
                self.retry_count += 1
        elif method == "turn/completed":
            status = p.get("turn", {}).get("status")
            self.status = status if status in ("completed", "failed", "interrupted", "cancelled") else "unknown_terminal"
            self.end = elapsed

    def record(self, expected, requires_tool):
        missing = {}
        if self.first is None:
            missing["first_visible_ms"] = "no nonempty item/agentMessage/delta observed"
        if self.end is None:
            missing["completion_ms"] = "no matching turn/completed observed"
        if self.usage is None:
            missing["usage"] = "no matching token usage notification observed"
        missing["upstream_request_id"] = "not exposed by installed app-server stream; correlate gateway separately"
        quality = self.final is not None and self.final.strip() == expected
        if requires_tool:
            quality = quality and any(t["success"] for t in self.tools)
        else:
            quality = quality and not self.tools and not self.tool_items
        quality = quality and not any(t["type"] != "dynamicToolCall" for t in self.tool_items)
        accepted = self.status == "completed" and self.first is not None and self.end is not None and quality
        return {
            "thread_id": self.thread_id, "turn_id": self.turn_id,
            "rpc_request_id": self.request_id, "upstream_request_id": None,
            "submit_event": "turn/start", "end_event": "turn/completed" if self.end is not None else None,
            "status": self.status, "first_visible_ms": self.first, "completion_ms": self.end,
            "retry_count": self.retry_count, "observed_attempts": self.retry_count + 1,
            "attempts_scope": "app-server error willRetry signals only; upstream attempts unknown",
            "error_count": self.error_count, "error_categories": dict(self.error_categories),
            "http_statuses": dict(self.http_statuses), "usage": self.usage, "tools": self.tools,
            "tool_items": self.tool_items,
            "quality_pass": bool(quality), "accepted": accepted,
            "anomalies": dict(self.anomalies), "missing": missing,
        }


class AppServer:
    def __init__(self, codex, fixture):
        self.fixture = fixture
        self.q = queue.Queue()
        self.stderr = Counter()
        self.serial = 0
        self.p = None
        self.job = None
        try:
            self.p = subprocess.Popen([codex, "app-server", "--stdio"],
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      text=True, encoding="utf-8", errors="replace", bufsize=1,
                                      start_new_session=os.name != "nt")
        except OSError:
            raise SampleError("subprocess_start_failed") from None
        if os.name == "nt":
            try:
                self.job = WindowsJob(self.p)
            except SampleError:
                self.p.kill()
                self.p.wait(timeout=5)
                raise
        threading.Thread(target=self._stdout, daemon=True).start()
        threading.Thread(target=self._stderr, daemon=True).start()

    def _stdout(self):
        try:
            for line in self.p.stdout:
                try:
                    event = json.loads(line)
                    if isinstance(event, dict):
                        self.q.put((time.perf_counter(), event))
                except (ValueError, TypeError):
                    self.stderr["invalid_json"] += 1
        finally:
            self.q.put((time.perf_counter(), {"_closed": True}))

    def _stderr(self):
        for line in self.p.stderr:
            for token, category in (("falling back to HTTP", "http_fallback"), ("websocket closed", "websocket_closed"), ("ERROR", "error"), ("WARN", "warning")):
                if token in line:
                    self.stderr[category] += 1

    def send(self, method, params, request=True):
        self.serial += 1
        data = {"jsonrpc": "2.0", "method": method, "params": params}
        if request:
            data["id"] = self.serial
        self.write(data)
        return self.serial

    def write(self, data):
        try:
            self.p.stdin.write(json.dumps(data) + "\n")
            self.p.stdin.flush()
        except (OSError, ValueError):
            raise SampleError("subprocess_write_failed") from None

    def receive(self, deadline):
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            raise SampleError("timeout")
        try:
            at, event = self.q.get(timeout=remaining)
        except queue.Empty:
            raise SampleError("timeout") from None
        if event.get("_closed"):
            raise SampleError("disconnected")
        return at, event

    def server_request(self, event, turn=None):
        if "method" not in event or "id" not in event:
            return False
        p = event.get("params", {})
        if event["method"] == "item/tool/call":
            started = time.perf_counter()
            valid = (turn is not None and p.get("threadId") == turn.thread_id
                     and p.get("turnId") == turn.turn_id and p.get("tool") == "read_fixture"
                     and p.get("arguments") == {"key": "numbers"})
            content = self.fixture.read_text(encoding="utf-8") if valid else "Tool request refused."
            valid = valid and content == FIXTURE
            if not valid:
                content = "Tool request refused."
            self.write({"id": event["id"], "result": {"success": valid, "contentItems": [{"type": "inputText", "text": content}]}})
            if turn:
                turn.tools.append({"name": "read_fixture", "success": valid, "elapsed_ms": (time.perf_counter()-started)*1000})
        else:
            # Never wait for a UI approval. Unknown requests are rejected too.
            self.write({"id": event["id"], "error": {"code": -32601, "message": "Benchmark denies interactive requests"}})
            raise SampleError("server_request_denied")
        return True

    def rpc(self, method, params, timeout=30):
        rid = self.send(method, params)
        deadline = time.perf_counter() + timeout
        while True:
            _, event = self.receive(deadline)
            if self.server_request(event):
                continue
            if event.get("id") == rid and "method" not in event:
                if "error" in event:
                    raise SampleError("rpc_error")
                return event.get("result", {})

    def run_turn(self, thread_id, effort, prompt, expected, requires_tool, timeout):
        submitted_utc = datetime.now(timezone.utc).isoformat()
        started = time.perf_counter()
        rid = self.send("turn/start", {"threadId": thread_id, "effort": effort,
                                      "input": [{"type": "text", "text": prompt}]})
        turn = Turn(thread_id, rid, started)
        deadline = started + timeout
        try:
            while turn.end is None:
                at, event = self.receive(deadline)
                if event.get("id") == rid and "method" not in event:
                    if "error" in event:
                        raise SampleError("turn_start_rpc_error")
                    tid = event.get("result", {}).get("turn", {}).get("id")
                    if turn.turn_id and tid != turn.turn_id:
                        raise SampleError("turn_id_mismatch")
                    turn.turn_id = tid
                # Tool request may precede a delta, but normally follows turn/started.
                if self.server_request(event, turn):
                    continue
                turn.observe(at, event)
        except SampleError as error:
            turn.status = str(error)
            if turn.turn_id:
                try:
                    self.send("turn/interrupt", {"threadId": thread_id, "turnId": turn.turn_id})
                except SampleError:
                    pass
        except KeyboardInterrupt:
            turn.status = "cancelled"
        result = turn.record(expected, requires_tool)
        result["submitted_utc"] = submitted_utc
        result["observed_elapsed_ms"] = (time.perf_counter()-started)*1000
        return result

    def close(self):
        if not self.p:
            return
        # Kill ONLY the newly created server's process tree, before its root can
        # exit and orphan descendants. Never enumerate/kill all Codex processes.
        if self.job:
            self.job.close()
        elif os.name != "nt":
            try:
                os.killpg(self.p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            self.p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.p.kill()
            self.p.wait(timeout=5)
        for pipe in (self.p.stdin, self.p.stdout, self.p.stderr):
            pipe.close()


def sample(args, task, effort, pair, sequence, fixture):
    result = {"sample_id": str(uuid.uuid4()), "task": task, "effort": effort,
              "pair": pair, "sequence": sequence, "model": MODEL,
              "network": args.network, "connection": "fresh_app_server_and_thread",
              "warmup": False, "context": "new ephemeral thread; multi retains exactly three turns",
              "turns": [], "status": "pending", "accepted": False,
              "started_utc": datetime.now(timezone.utc).isoformat(), "elapsed_ms": None}
    result["client_request_id"] = result["sample_id"]
    app = None
    started = time.perf_counter()
    try:
        app = AppServer(args.codex, fixture)
        app.rpc("initialize", {"clientInfo": {"name": "company-latency", "version": "1.0"}, "capabilities": {"experimentalApi": True}})
        app.send("initialized", {}, request=False)
        thread = app.rpc("thread/start", {
            "cwd": str(fixture.parent), "model": MODEL, "ephemeral": True,
            "approvalPolicy": "never", "sandbox": "read-only",
            "config": {"model_providers.OpenAI.http_headers.X-Client-Request-ID": result["client_request_id"]},
            "dynamicTools": [{"type": "function", "name": "read_fixture", "description": "Read the frozen benchmark numbers fixture.",
                              "inputSchema": {"type": "object", "properties": {"key": {"type": "string", "enum": ["numbers"]}}, "required": ["key"], "additionalProperties": False}}],
        })
        thread_id = thread["thread"]["id"]
        task_started = time.perf_counter()
        result["initialization_ms"] = (task_started-started)*1000
        for prompt, expected, tool in TASKS[task]:
            record = app.run_turn(thread_id, effort, prompt, expected, tool, args.timeout)
            result["turns"].append(record)
            if record["status"] != "completed":
                break
        result["elapsed_ms"] = (time.perf_counter()-task_started)*1000
        result["accepted"] = len(result["turns"]) == len(TASKS[task]) and all(t["accepted"] for t in result["turns"])
        result["status"] = "completed" if result["accepted"] else "not_accepted"
    except SampleError as error:
        result["status"] = str(error)
    except KeyboardInterrupt:
        result["status"] = "cancelled"
    except (OSError, KeyError, TypeError, ValueError):
        result["status"] = "local_or_protocol_error"
    finally:
        if app:
            app.close()
            result["stderr_categories"] = dict(app.stderr)
        result["app_server_lifetime_ms"] = (time.perf_counter()-started)*1000
    return result


def summarize(records):
    groups = defaultdict(list)
    for row in records:
        groups[(row["task"], row["effort"])].append(row)
    output = []
    for (task, effort), rows in sorted(groups.items()):
        accepted = [r for r in rows if r["accepted"]]
        metrics = {}
        for name, values in (
            ("task_elapsed_ms", [r["elapsed_ms"] for r in accepted]),
            ("first_visible_ms", [r["turns"][0]["first_visible_ms"] for r in accepted]),
            ("turn_completion_ms", [sum(t["completion_ms"] for t in r["turns"]) for r in accepted]),
        ):
            metrics[name] = {"n": len(values), "median": statistics.median(values) if values else None,
                             "min": min(values) if values else None, "max": max(values) if values else None}
        output.append({"task": task, "effort": effort, "denominator": len(rows), "accepted": len(accepted),
                       "all_quality_pass": len(accepted) == len(rows), "statuses": dict(Counter(r["status"] for r in rows)),
                       "metrics_correct_complete_only": metrics})
    pairs = []
    grouped = defaultdict(dict)
    for r in records:
        grouped[(r["task"], r["pair"])][r["effort"]] = r
    for (task, pair), sides in sorted(grouped.items()):
        a, b = sides.get("max"), sides.get("medium")
        valid = bool(a and b and a["accepted"] and b["accepted"])
        pairs.append({"task": task, "pair": pair, "both_accepted": valid,
                      "medium_minus_max_task_ms": b["elapsed_ms"]-a["elapsed_ms"] if valid else None})
    return {"groups": output, "pairs": pairs, "interpretation": "Small-sample descriptive results only; no P95 or cross-task causal claim. Failed samples remain in denominator."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex", required=True)
    parser.add_argument("--workdir", type=Path, required=True, help="Existing scratch parent; temporary fixture subdirectory is automatically removed")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--efforts", nargs="+", choices=("max", "medium"), default=["max", "medium"])
    parser.add_argument("--pairs", type=int, default=5)
    parser.add_argument("--task", choices=tuple(TASKS), help="Default: all three frozen tasks")
    parser.add_argument("--smoke", action="store_true", help="Fixed short task only; still respects pairs/efforts")
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--network", choices=("company-lan", "external-vpn", "unknown"), default="unknown")
    args = parser.parse_args(argv)
    if args.pairs < 1 or args.timeout <= 0 or len(args.efforts) != len(set(args.efforts)):
        parser.error("pairs/timeout must be positive and efforts unique")
    try:
        runtime = subprocess.run([args.codex, "--version"], capture_output=True, text=True, timeout=10)
        # Runtime output is untrusted; retain only a version-shaped token.
        import re
        match = re.search(r"\b\d+\.\d+\.\d+(?:-[A-Za-z0-9.]+)?\b", runtime.stdout)
        version = match.group() if runtime.returncode == 0 and match else None
    except (OSError, subprocess.TimeoutExpired):
        version = None
    records = []
    tasks = ["fixed"] if args.smoke else [args.task] if args.task else list(TASKS)
    with tempfile.TemporaryDirectory(prefix="codex-latency-", dir=args.workdir) as temp:
        fixture = Path(temp) / "numbers.txt"
        fixture.write_text(FIXTURE, encoding="utf-8")
        cancelled = False
        for task in tasks:
            for pair in range(1, args.pairs+1):
                order = args.efforts if pair % 2 else list(reversed(args.efforts))
                for effort in order:
                    row = sample(args, task, effort, pair, len(records)+1, fixture)
                    records.append(row)
                    report = {"schema_version": 1, "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                              "runtime_version": version, "model": MODEL, "samples": records, "summary": summarize(records),
                              "safety": {"ephemeral": True, "sandbox": "read-only", "approval_policy": "never", "existing_auth": True, "persistent_config_changed": False, "raw_content_saved": False},
                              "missing": {"gateway_stages": "join separate gateway logs by time and IDs; not available in app-server stream", "wire_protocol": "not inferred from missing stderr warnings; requires gateway/client log evidence"}}
                    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                    print(json.dumps({"sequence": row["sequence"], "task": task, "effort": effort, "status": row["status"], "accepted": row["accepted"]}), flush=True)
                    if row["status"] == "cancelled" or any(t["status"] == "cancelled" for t in row["turns"]):
                        cancelled = True
                        break
                if cancelled:
                    break
            if cancelled:
                break
    return 0 if records and all(r["accepted"] for r in records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
