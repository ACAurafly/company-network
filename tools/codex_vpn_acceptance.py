"""Offline descriptive LAN/VPN screening; never operates a VPN or sends requests.

Inputs are codex_latency.py reports, optional network_probe.py reports, and
hash-bound reviewed observation JSON (see 04-vpn-maintenance.md).
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import statistics

from codex_latency import TASKS


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def utc(value):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result if result.utcoffset() is not None else None
    except (AttributeError, TypeError, ValueError):
        return None


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def good(row):
    turns = row.get("turns", [])
    return (row.get("accepted") is True and row.get("status") == "completed"
            and row.get("task") in TASKS and len(turns) == len(TASKS[row["task"]])
            and number(row.get("elapsed_ms")) and all(
                t.get("accepted") is True and t.get("quality_pass") is True
                and t.get("status") == "completed" and number(t.get("first_visible_ms"))
                and number(t.get("completion_ms")) and t["first_visible_ms"] <= t["completion_ms"]
                for t in turns))


def describe(rows):
    valid = [r for r in rows if good(r)]
    def metric(values):
        return {"n": len(values), "median": statistics.median(values) if values else None,
                "min": min(values) if values else None, "max": max(values) if values else None}
    return {"denominator": len(rows), "correct_complete": len(valid),
            "statuses": dict(Counter(str(r.get("status", "unknown")) for r in rows)),
            "retry_count": sum(t.get("retry_count", 0) for r in rows for t in r.get("turns", [])
                               if isinstance(t.get("retry_count", 0), int) and not isinstance(t.get("retry_count", 0), bool)),
            "retry_scope": "observed app-server signals only; gateway attempts may be unknown",
            "task_elapsed_ms": metric([r["elapsed_ms"] for r in valid]),
            "first_visible_ms": metric([r["turns"][0]["first_visible_ms"] for r in valid])}


def describe_groups(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[(row.get("task"), row.get("effort"))].append(row)
    return [{"task": task, "effort": effort, **describe(group)}
            for (task, effort), group in sorted(groups.items(), key=lambda item: str(item[0]))]


def observations(manifest, base):
    """Only accept hash-matched captures; never copy their raw contents to output."""
    result, errors = {}, []
    for side in ("company_lan", "external_vpn"):
        item = manifest.get(side, {})
        try:
            path = base / item["path"]
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != item["sha256"]:
                raise ValueError("hash")
            value = json.loads(raw.decode("utf-8-sig"))
            # Reviewed observations are evidence supplied by the operator, not
            # facts independently measured by this offline comparator.
            if value.get("schema_version") != 1 or value.get("reviewed") is not True:
                raise ValueError("review")
            if not value.get("source_refs") or not isinstance(value.get("samples"), dict):
                raise ValueError("sources")
            for ref in value["source_refs"]:
                source = path.parent / ref["path"]
                if hashlib.sha256(source.read_bytes()).hexdigest() != ref["sha256"]:
                    raise ValueError("source hash")
            result[side] = value
        except (OSError, ValueError, KeyError, TypeError):
            errors.append(side + ": missing, unreviewed or hash-invalid observation/source")
    return result, errors


def evidence_for(observation, row, external):
    reasons = []
    sample = observation.get("samples", {}).get(row.get("sample_id"), {})
    captured, started = utc(sample.get("captured_utc")), utc(row.get("started_utc"))
    if not captured or not started or abs((captured-started).total_seconds()) > 900:
        reasons.append("missing or stale sample-bound observation")
    if sample.get("location") != ("outside_company" if external else "company_lan"):
        reasons.append("physical network location not evidenced")
    if external:
        if sample.get("access_type") not in ("cellular", "residential", "other_external"):
            reasons.append("real external access not evidenced")
        for field in ("outer_active", "inner_active", "route_ready", "certificate_pin_match", "vpn_entry_direct"):
            if sample.get(field) is not True:
                reasons.append(field + " not evidenced")
    return sample, reasons


def network_summary(report):
    output = {}
    for name, target in report.get("targets", {}).items():
        groups = {}
        for kind in ("cold", "warm"):
            group = target.get(kind, {})
            rows = group.get("samples", [])
            failures = sum(r.get("ok") is not True for r in rows)
            connection = all((r.get("num_connects") == 1 and r.get("connection_reused") is False)
                             if kind == "cold" else (r.get("connection_reused") is True and r.get("num_connects") == 0)
                             for r in rows)
            timing = all(r.get("timing_valid") is True and number(r.get("https_ready_s" if kind == "cold" else "ttfb_s")) for r in rows)
            warmup = kind == "cold" or group.get("warmup", {}).get("ok") is True
            groups[kind] = {"denominator": len(rows), "failures": failures,
                            "connection_evidence_complete": connection,
                            "status": "sampling_complete" if len(rows) >= 20 and not failures and connection and timing and warmup else "not_accepted"}
        output[name] = groups
    return {"targets": output, "dns_cache_hit": report.get("condition_observation", {}).get("dns_cache_hit", "unknown"),
            "performance_acceptance": "not_accepted",
            "reason": "HTTPS sampling is auxiliary; DNS/environment comparability and model business acceptance are separate"}


def compare(lan, vpn, evidence=None, network=None):
    evidence = evidence or {}
    reasons = []
    if lan.get("schema_version") != 1 or vpn.get("schema_version") != 1:
        reasons.append("unsupported sampler schema")
    for field in ("runtime_version", "model"):
        if not lan.get(field) or lan.get(field) != vpn.get(field):
            reasons.append(field + " unknown or mismatched")
    for field in ("device_id", "account_id", "egress_id"):
        a, b = (evidence.get(s, {}).get(field) for s in ("company_lan", "external_vpn"))
        if not a or a != b:
            reasons.append(field + " unknown or mismatched; comparability limited")
    indexes = []
    for side, report, label in (("company_lan", lan, "company-lan"), ("external_vpn", vpn, "external-vpn")):
        index = defaultdict(list)
        ids = [r.get("sample_id") for r in report.get("samples", [])]
        if any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
            reasons.append(side + " missing or duplicate sample identity")
        for row in report.get("samples", []):
            index[(row.get("task"), row.get("effort"), row.get("pair"))].append(row)
            if row.get("network") != label:
                reasons.append(side + " sample label mismatch")
        indexes.append(index)
    a_index, b_index = indexes
    paired, triggers, stage_slow = [], [], Counter()
    counts = Counter()
    for key in sorted(set(a_index) | set(b_index), key=str):
        task, effort, pair_id = key
        issues = list(reasons)
        left, right = a_index.get(key, []), b_index.get(key, [])
        if len(left) != 1 or len(right) != 1:
            paired.append({"task": task, "effort": effort, "pair": pair_id, "comparable": False,
                           "vpn_minus_lan_ms": None, "limitations": ["missing or duplicate pair"]})
            continue
        a, b = left[0], right[0]
        if task not in TASKS or effort not in ("max", "medium") or not isinstance(pair_id, int) or isinstance(pair_id, bool) or pair_id < 1:
            issues.append("unknown task/effort/pair")
        for r in (a, b):
            if r.get("model") != lan.get("model"):
                issues.append("sample model mismatch")
        ta, tb = utc(a.get("started_utc")), utc(b.get("started_utc"))
        if not ta or not tb or abs((ta-tb).total_seconds()) > 900:
            issues.append("pair outside 15-minute window or timestamp missing")
        ea, ia = evidence_for(evidence.get("company_lan", {}), a, False)
        eb, ib = evidence_for(evidence.get("external_vpn", {}), b, True)
        issues.extend(ia + ib)
        # Context/cache/workload differences need an explicit source-backed review.
        if eb.get("workload_comparable") is not True or ea.get("workload_comparable") is not True:
            issues.append("context/cache/input-output comparability unreviewed")
        comparable = not issues
        correct = good(a) and good(b)
        delta = b["elapsed_ms"]-a["elapsed_ms"] if comparable and correct else None
        if comparable:
            counts[(task, effort)] += 1
        if good(a) and not good(b):
            triggers.append({"task": task, "effort": effort, "pair": pair_id, "reason": "VPN-side-only failure; investigate even if conditions limited"})
        stages = {}
        for stage in ("vpn_ready_ms", "nas_connect_ms", "upstream_wait_ms"):
            va, vb = ea.get("stages_ms", {}).get(stage), eb.get("stages_ms", {}).get(stage)
            measured = (comparable and ea.get("stage_clock") == eb.get("stage_clock") == "local_monotonic_duration" and number(va) and number(vb))
            stages[stage] = vb-va if measured else None
            if stage != "upstream_wait_ms" and measured and vb > va:
                stage_slow[(task, effort, stage)] += 1
        if delta is not None and delta != 0 and eb.get("difference_explained") is not True:
            triggers.append({"task": task, "effort": effort, "pair": pair_id, "reason": "unexplained task difference; inspect context and upstream"})
        paired.append({"task": task, "effort": effort, "pair": pair_id, "comparable": comparable,
                       "both_correct_complete": correct, "vpn_minus_lan_ms": delta,
                       "stage_vpn_minus_lan_ms": stages, "limitations": issues})
    for (task, effort, stage), count in stage_slow.items():
        if count >= 3:
            triggers.append({"task": task, "effort": effort, "stage": stage, "pairs": count,
                             "reason": "at least three pairs slower in the same access stage"})
    groups = [{"task": task, "effort": effort, "comparable_pairs": n,
               "status": "descriptive_screening_complete" if n >= 5 else "not_accepted"}
              for (task, effort), n in sorted(counts.items())]
    complete = bool(paired) and all(p.get("comparable") and p.get("both_correct_complete") for p in paired) and bool(groups) and all(g["comparable_pairs"] >= 5 for g in groups)
    return {"schema_version": 1, "remote_business_status": "descriptive_screening_complete" if complete else "not_accepted",
            "company_lan": describe(lan.get("samples", [])), "external_vpn": describe(vpn.get("samples", [])),
            "company_lan_groups": describe_groups(lan.get("samples", [])),
            "external_vpn_groups": describe_groups(vpn.get("samples", [])),
            "runtime_version": lan.get("runtime_version"), "model": lan.get("model"),
            "groups": groups, "pairs": paired, "retest_triggers": triggers,
            "network": {s: network_summary((network or {})[s]) if s in (network or {}) else
                        {"status": "not_accepted", "reason": "network_probe report not supplied"}
                        for s in ("company_lan", "external_vpn")},
            "interpretation": "Descriptive screening only; no stable P95, causal VPN claim or network change recommendation. Observations are operator-reviewed evidence, not independently measured by this offline tool. Missing stage durations remain null."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lan", type=Path, required=True)
    parser.add_argument("--vpn", type=Path, required=True)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--lan-network", type=Path)
    parser.add_argument("--vpn-network", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        evidence, errors = observations(load(args.evidence), args.evidence.parent) if args.evidence else ({}, ["no reviewed observation manifest"])
        network = {s: load(p) for s, p in (("company_lan", args.lan_network), ("external_vpn", args.vpn_network)) if p}
        result = compare(load(args.lan), load(args.vpn), evidence, network)
        result["evidence_limitations"] = errors
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        parser.error("unreadable or invalid input/output; no acceptance produced")
    print(json.dumps({"remote_business_status": result["remote_business_status"], "retest_triggers": len(result["retest_triggers"])}))
    return 0 if result["remote_business_status"] == "descriptive_screening_complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
