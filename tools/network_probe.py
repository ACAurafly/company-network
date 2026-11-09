"""Read-only HTTPS timing probe. No DNS flushing, proxy edits or VPN commands."""
import argparse
import datetime as dt
import json
import math
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

GOOGLE = "https://www.google.com/generate_204"
MARKER = "COMPANY_PROBE:"


def targets(feishu=None):
    result = {"google204": GOOGLE}
    if feishu:
        parts = urlsplit(feishu)
        if (parts.scheme != "https" or not parts.hostname or parts.username or
                parts.password or parts.query or parts.fragment or parts.path not in ("", "/") or
                parts.port not in (None, 443)):
            raise ValueError("Feishu target must be an HTTPS tenant root without credentials or query")
        result["feishu_root"] = "https://" + parts.hostname + "/"
    return result


def curl_args(url, curl):
    return [curl, "--silent", "--show-error", "--output", "NUL", "--connect-timeout", "15",
            "--max-time", "30", "--retry", "0", "--http1.1", "--write-out", MARKER + "%{json}\n", url]


def decode(output):
    rows = []
    for line in output.splitlines():
        if line.startswith(MARKER):
            try:
                rows.append(json.loads(line[len(MARKER):]))
            except json.JSONDecodeError:
                rows.append({"exitcode": -1})
    return rows


def sample(raw, fallback=0):
    # Explicit allowlist: curl's url_effective, errormsg, headers and body never leave this boundary.
    code = int(raw.get("exitcode", fallback))
    status = int(raw.get("http_code", 0))
    reused = int(raw.get("num_connects", -1)) == 0 and code == 0 and status > 0
    def timing(key):
        return float(raw.get(key, 0))
    return {
        "ok": code == 0 and 200 <= status < 400,
        "curl_exitcode": code, "http_status": status,
        "attempts": 1, "retry_count": 0,
        "local_ip": raw.get("local_ip", ""), "remote_ip": raw.get("remote_ip", ""),
        "num_connects": raw.get("num_connects"), "connection_reused": reused,
        "dns_s": None if reused else timing("time_namelookup"),
        "tcp_s": None if reused else max(0, timing("time_connect") - timing("time_namelookup")),
        "tls_s": None if reused else max(0, timing("time_appconnect") - timing("time_connect")),
        "https_ready_s": None if reused else timing("time_appconnect"),
        "ttfb_s": timing("time_starttransfer"), "total_s": timing("time_total"),
        "timing_valid": code == 0 and status > 0,
    }


def run_group(url, count, warm, curl="curl.exe", runner=subprocess.run):
    # --next retains curl's connection cache. Every cold request is a new process.
    def invoke(command, expected):
        try:
            result = runner(command, capture_output=True, text=True, timeout=35 * expected + 5)
            rows = decode(result.stdout)
            return [sample(rows[i], result.returncode) if i < len(rows) else sample({}, result.returncode or -1)
                    for i in range(expected)]
        except (OSError, subprocess.TimeoutExpired):
            return [sample({}, -1) for _ in range(expected)]
    if warm:
        command = curl_args(url, curl)
        for _ in range(count):
            command += ["--next"] + curl_args(url, curl)[1:]
        rows = invoke(command, count + 1)
        return {"warmup": rows[0], "samples": rows[1:]}
    return {"samples": [invoke(curl_args(url, curl) + ["--no-sessionid"], 1)[0]
                        for _ in range(count)]}


def percentile(values, fraction):
    if not values:
        return None
    values = sorted(values)
    return values[max(0, math.ceil(len(values) * fraction) - 1)]


def summarize(group):
    rows = group["samples"]
    result = {"count": len(rows), "successes": sum(row["ok"] for row in rows),
              "success_rate": sum(row["ok"] for row in rows) / len(rows) if rows else 0,
              "failures": sum(not row["ok"] for row in rows),
              "warmup_ok": group.get("warmup", {"ok": True})["ok"],
              "note": "Timing quantiles describe completed transfers only; failures remain in samples and success_rate. No pass if any failure."}
    for key in ("dns_s", "tcp_s", "tls_s", "https_ready_s", "ttfb_s", "total_s"):
        values = [row[key] for row in rows if row["timing_valid"] and row[key] is not None]
        result[key] = {"measured_count": len(values), "p50": percentile(values, .5), "p95": percentile(values, .95)}
    return result


def compare(old, new):
    comparisons = []
    for name, target in new["targets"].items():
        previous = old.get("targets", {}).get(name)
        if previous is None or previous["url"] != target["url"]:
            comparisons.append({"target": name, "comparable": False})
            continue
        for kind in ("cold", "warm"):
            a, b = summarize(previous[kind]), summarize(target[kind])
            metric = "https_ready_s" if kind == "cold" else "ttfb_s"
            before, after = a[metric]["p95"], b[metric]["p95"]
            enough = a["count"] >= 20 and b["count"] >= 20
            no_failures = a["failures"] == 0 and b["failures"] == 0 and a["warmup_ok"] and b["warmup_ok"]
            change = after / before - 1 if before and after is not None else None
            numeric = enough and no_failures and change is not None and change <= (-.30 if kind == "cold" else .10)
            # Policy text is a sampling recipe, not evidence of matching DNS/environment.
            # This collector cannot observe Windows/upstream DNS cache hits.
            comparable = False
            comparisons.append({"target": name, "group": kind, "comparable": comparable,
                                "old": a, "new": b, "p95_change_fraction": change,
                                "numeric_threshold_met": numeric,
                                "condition_status": "unknown",
                                "condition_reason": "DNS cache hits and matching device/account/network/proxy conditions are not measured; overall acceptance requires external evidence",
                                "acceptance_pass": False})
    return comparisons


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feishu-root")
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--compare", nargs=2, type=Path, metavar=("OLD", "NEW"))
    args = parser.parse_args()
    if args.compare:
        print(json.dumps(compare(*(json.loads(p.read_text(encoding="utf-8-sig")) for p in args.compare)), ensure_ascii=False, indent=2))
        return
    if not args.output or args.count < 1:
        parser.error("--output and a positive --count are required")
    try:
        selected = targets(args.feishu_root)
    except ValueError as error:
        parser.error(str(error))
    result = {"schema_version": 1, "utc": dt.datetime.now(dt.timezone.utc).isoformat(),
              "local_time": dt.datetime.now().astimezone().isoformat(),
              "condition_observation": {"dns_cache_hit": "unknown", "environment_match": "unknown"},
              "measurement_policy": {"dns_cache": "not flushed; OS and upstream cache uncontrolled; not DNS cold start",
                                     "cold": "independent curl processes; fresh TCP; TLS session cache disabled",
                                     "warm": "one curl process per target; one retained warmup; connection cache preserved",
                                     "http": "HTTP/1.1 GET; body discarded; redirects not followed",
                                     "retries": "disabled; every failed attempt retained; repeated sampling is not hidden retry"},
              "business_validation": "Not accepted: Google 204 and tenant root 302 do not validate Feishu documents or messages",
              "targets": {}}
    for name, url in selected.items():
        target = {"url": url}
        for warm in (False, True):
            group = run_group(url, args.count, warm)
            group["summary"] = summarize(group)
            target["warm" if warm else "cold"] = group
        result["targets"][name] = target
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
