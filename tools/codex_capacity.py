"""Offline capacity evidence review. Standard library; never calls production."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

TRIGGERS = {"account_wait_timeout", "new_429", "authentication", "stream_completion"}


def instant(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timezone required")
    return result.timestamp()


def baseline(record, reference):
    """A peak, not an average, governs admission."""
    if not record.get("source") or record.get("reliable") is not True:
        return False, None, "unreliable_or_missing_slots"
    rows = record.get("samples", [])
    if len(rows) < 2:
        return False, None, "baseline_missing"
    times = [instant(r["at"]) for r in rows]
    if any(b <= a or b - a > 30 for a, b in zip(times, times[1:])):
        return False, None, "baseline_gaps"
    if times[-1] - times[0] < 300:
        return False, None, "baseline_under_five_minutes"
    if any(r.get("limit") != 20 or type(r.get("used")) is not int or not 0 <= r["used"] <= 20 for r in rows):
        return False, None, "invalid_slot_counts"
    free = min(20 - r["used"] for r in rows)
    if not 0 <= reference - times[-1] <= 60:
        return False, free, "baseline_stale_or_future"
    return True, free, None


def interval(record, prefix):
    start, end = record.get(prefix + "_started_at"), record.get(prefix + "_ended_at")
    if start is None or end is None:
        return None
    result = instant(start), instant(end)
    return result if result[1] > result[0] else None


def overlaps(a, b):
    return a is not None and b is not None and max(a[0], b[0]) < min(a[1], b[1])


def assess(evidence, reports, now):
    if evidence.get("schema_version") != 1:
        raise ValueError("unsupported schema")
    captured = instant(evidence["captured_at"])
    if captured > now:
        raise ValueError("capture time is in the future")
    config = evidence.get("configuration", {})
    config_ok = bool(config.get("source")) and config.get("upstream_limit") == 20 and config.get("admin_limit") == 30
    samples = {}
    for report in reports:
        for sample in report.get("samples", []):
            for turn in sample.get("turns", []):
                key = (sample["sample_id"], turn["turn_id"])
                if key in samples:
                    raise ValueError("duplicate sampler task/turn")
                samples[key] = (sample, turn)
    groups = evidence.get("groups", [])
    identities, group_ids = set(), set()
    for group in groups:
        gid = group["group_id"]
        if gid in group_ids:
            raise ValueError("duplicate group id")
        group_ids.add(gid)
        for request in group.get("requests", []):
            ids = (("turn", request.get("task_id"), request.get("turn_id")),
                   ("gateway", request.get("gateway_request_id")))
            for identity in ids:
                if identity in identities:
                    raise ValueError("reused request evidence")
                identities.add(identity)
    outcomes = []
    rollback = set()
    failures = []
    for group in groups:
        phase = group.get("phase")
        expected_user = {"controlled_1": "controlled", "controlled_2": "controlled", "pilot_5": "5", "pilot_2": "2"}.get(phase)
        requests = group.get("requests", [])
        reasons, spans = [], []
        expected_limit = 1 if phase == "controlled_1" else 2
        if expected_user is None or str(group.get("user_id")) != expected_user or group.get("limit") != expected_limit:
            reasons.append("phase_user_or_limit_mismatch")
        if not group.get("source") or group.get("complete_logs") is not True or len(requests) != 2:
            reasons.append("incomplete_gateway_evidence")
        if len({r.get("task_id") for r in requests}) != 2:
            reasons.append("two_independent_tasks_required")
        for request in requests:
            errors = request.get("errors")
            if not isinstance(errors, list):
                reasons.append("missing_error_coverage")
                errors = []
            if TRIGGERS.intersection(errors) and phase in ("pilot_5", "pilot_2"):
                rollback.add(expected_user)
            if phase in ("pilot_5", "pilot_2") and request.get("http_status") in (401, 403, 429):
                rollback.add(expected_user)
            linked = samples.get((request.get("task_id"), request.get("turn_id")))
            if not linked or request.get("correlation_verified") is not True or not request.get("gateway_request_id"):
                reasons.append("missing_verified_sampler_join")
            else:
                sample, turn = linked
                if sample.get("accepted") is not True or turn.get("accepted") is not True or turn.get("quality_pass") is not True or turn.get("status") != "completed" or turn.get("end_event") != "turn/completed":
                    reasons.append("client_completion_or_quality_failed")
                if turn.get("error_count") != 0 or turn.get("retry_count") != 0 or turn.get("anomalies"):
                    reasons.append("client_errors_or_retries")
                # Quality rejection and an explicit operator cancellation are
                # distinct from an abnormal/missing stream completion. A final
                # gateway 200 or empty classifier arrays cannot clear a fault.
                stream_fault = (turn.get("status") != "cancelled" and (
                    turn.get("status") != "completed" or turn.get("end_event") != "turn/completed"))
                sample_fault = sample.get("status", "completed") not in ("completed", "not_accepted", "cancelled")
                if phase in ("pilot_5", "pilot_2") and (
                    stream_fault or sample_fault
                    or any(turn.get("error_categories", {}).get(k, 0) for k in (
                        "unauthorized", "responseStreamConnectionFailed", "responseStreamDisconnected"))
                    or any(turn.get("http_statuses", {}).get(k, 0) for k in ("401", "403", "429"))
                ):
                    rollback.add(expected_user)
            if request.get("http_status") != 200 or errors:
                reasons.append("gateway_errors")
                failures.append({"group_id": group["group_id"], "http_status": request.get("http_status"), "errors": errors})
            span = interval(request, "upstream")
            if span is None or span[1] > captured:
                reasons.append("missing_or_future_upstream_interval")
            spans.append(span)
        if len(spans) == 2:
            if phase == "controlled_1":
                waits = [interval(r, "user_wait") for r in requests]
                if overlaps(*spans) or not any(overlaps(waits[i], spans[1-i]) and spans[i] and waits[i][1] <= spans[i][0] for i in range(2)):
                    reasons.append("user_slot_contention_not_proven")
            else:
                if not overlaps(*spans):
                    reasons.append("upstream_overlap_not_proven")
                if any(r.get("user_wait_started_at") is not None or r.get("user_wait_ended_at") is not None for r in requests):
                    reasons.append("candidate_still_waiting_for_user_slot")
        outcomes.append({"group_id": group["group_id"], "phase": phase, "passed": not reasons,
                         "reasons": sorted(set(reasons)), "spans": spans})
    counts = {phase: sum(o["phase"] == phase and o["passed"] for o in outcomes)
              for phase in ("controlled_1", "controlled_2", "pilot_5", "pilot_2")}
    controlled = config_ok and counts["controlled_1"] >= 3 and counts["controlled_2"] >= 3
    # Any failed controlled group remains visible and prevents a clean verification.
    controlled = controlled and all(o["passed"] for o in outcomes if o["phase"] in ("controlled_1", "controlled_2"))
    controlled_spans = {phase: [span for o in outcomes if o["phase"] == phase
                               for span in o["spans"] if span is not None]
                        for phase in ("controlled_1", "controlled_2")}
    controlled_end = max((span[1] for spans in controlled_spans.values() for span in spans), default=None)
    if controlled:
        controlled = (max(span[1] for span in controlled_spans["controlled_1"])
                      <= min(span[0] for span in controlled_spans["controlled_2"]))
    base_ok, free, base_reason = baseline(evidence.get("baseline", {}), now)
    if base_ok and instant(evidence["baseline"]["samples"][-1]["at"]) > captured:
        base_ok, base_reason = False, "slots_after_capture"
    pilots, pilot_results = evidence.get("pilots", []), []
    prior_end = None
    pilot_ids = set()
    for p in pilots:
        uid = str(p["user_id"])
        if uid in pilot_ids or uid not in ("5", "2"):
            raise ValueError("invalid or duplicate pilot user")
        pilot_ids.add(uid)
        start, end = instant(p["changed_at"]), instant(p["observed_until"])
        reasons = []
        if controlled_end is None or controlled_end > start:
            reasons.append("controlled_validation_must_precede_change")
        valid_base, pilot_free, why = baseline(p.get("baseline", {}), start)
        if not valid_base or pilot_free < 4:
            reasons.append(why or "insufficient_headroom")
        if p.get("original_limit") != 1 or p.get("candidate_limit") != 2 or not p.get("source") or p.get("complete_logs") is not True or not isinstance(p.get("errors"), list):
            reasons.append("incomplete_change_or_observation_evidence")
        if end - start < 1800 or end > captured or start > end:
            reasons.append("insufficient_or_future_observation")
        if uid == "2" and (prior_end is None or start < prior_end):
            reasons.append("user5_must_pass_before_user2")
        if uid == "5" and pilot_results:
            reasons.append("user5_must_be_first")
        if TRIGGERS.intersection(p.get("errors", [])):
            rollback.add(uid)
        if p.get("errors"):
            reasons.append("observation_errors")
        observed_groups = [o for o in outcomes if o["phase"] == "pilot_" + uid]
        good = [o for o in observed_groups if o["passed"] and all(span and start <= span[0] < span[1] <= end for span in o["spans"])]
        if len(good) < 3 or len(good) != len(observed_groups):
            reasons.append("three_representative_groups_required")
        if not controlled or not config_ok or uid in rollback or p.get("rollback_completed") is True:
            reasons.append("controlled_or_safety_gate_failed")
        passed = not reasons
        pilot_results.append({"user_id": uid, "passed": passed, "reasons": sorted(set(reasons))})
        if uid == "5" and passed:
            prior_end = end
    pending = sorted(uid for uid in rollback if not any(str(p["user_id"]) == uid and p.get("rollback_completed") is True for p in pilots))
    # A recorded production group without its change/monitoring window cannot pass.
    orphan_pilot = any(o["phase"] in ("pilot_5", "pilot_2") and o["phase"][6:] not in pilot_ids for o in outcomes)
    completion = {}
    for phase in counts:
        requests = [r for g in groups if g.get("phase") == phase for r in g.get("requests", [])]
        completed = sum(bool(samples.get((r.get("task_id"), r.get("turn_id")))) and
                        samples[(r.get("task_id"), r.get("turn_id"))][1].get("accepted") is True for r in requests)
        completion[phase] = {"referenced_tasks": len(requests), "accepted_turns": completed,
                             "completion_rate": completed / len(requests) if requests else None}
    return {"schema_version": 1, "assessed_at": datetime.fromtimestamp(now, timezone.utc).isoformat(),
            "capacity_assessment_complete": config_ok and base_ok,
            "controlled_verified": controlled,
            "pilot_eligible": controlled and base_ok and free >= 4 and not rollback and not pilots and not orphan_pilot,
            "pilot_verified": len(pilot_results) == 2 and all(p["passed"] for p in pilot_results) and not orphan_pilot and not rollback,
            "rollback_required": bool(rollback), "rollback_pending_users": pending,
            "baseline": {"valid": base_ok, "minimum_free_slots": free, "reason": base_reason,
                         "peak_used_slots": 20 - free if free is not None else None,
                         "traffic_scope": "all existing upstream traffic, including other users"},
            "configuration_verified": config_ok, "group_counts": counts,
            "completion": completion,
            "groups": [{k: v for k, v in o.items() if k != "spans"} for o in outcomes],
            "pilots": pilot_results, "failure_samples": failures,
            "limitations": ["Offline review trusts supplied source completeness and correlation attestations; no production changes or requests are made."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--samples", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--now", help="Explicit historical UTC reference; omission uses actual current time")
    args = parser.parse_args()
    try:
        result = assess(json.loads(args.evidence.read_text(encoding="utf-8-sig")),
                        [json.loads(p.read_text(encoding="utf-8-sig")) for p in args.samples],
                        instant(args.now) if args.now else datetime.now(timezone.utc).timestamp())
    except (ValueError, TypeError, KeyError, OSError, AttributeError):
        result = {"error": "invalid_or_unreadable_evidence", "capacity_assessment_complete": False,
                  "controlled_verified": False, "pilot_eligible": False, "pilot_verified": False, "rollback_required": False}
        code = 1
    else:
        code = 3 if result["rollback_required"] else (0 if result["capacity_assessment_complete"] or result["controlled_verified"] else 2)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if isinstance(v, bool) or k == "error"}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
