"""Run report (the D-098 contract; register 6.10, 7.1, 7.4, 7.6).

`build_report(run)` turns a finished, verified run into one dict. The STATUS comes only from the run's
`verifier_result` event (never from the agent's own words); everything else comes from runtime artifacts in the
event log and the approval store:

- `questions` and `refusal`: the `ask_user` / `declare_infeasible` calls that ended the run;
- `security_findings`: the scanner's ORG-006 findings (excerpts already masked);
- `evidence`: every tool result, with a one-line summary;
- `action_approvals`: each held call with its predicted outcome (`predicted.to`, `.subject`, ... plus `request`,
  `side_effect`, `effect`) and the human's decision;
- `side_effects`: every audit row since the run started (from the verifier's layer 3), plus each write the run
  claimed that Acme never stored (D-156);
- `failures`: every failed result with its class and next step (agent/failures.py);
- `recovered`: every call that succeeded only after a failed attempt inside the tool (its `data.attempts`): the
  error, its class, how many attempts failed and what settled it. It never changes the status (register 7.2);
- `narrative` and `stops`: the agent's own final words and why its work stopped early, if it did (never the status);
- `verifier`: what each check found.

The event log is already redacted (D-104), so the report never holds a secret; transport args (the idempotency
key) are left out of the evidence and `recovered` copies no args at all (7.6). `write_report` saves
`runs/<run_id>/report.json` and a one-screen `report.md`.
"""

import json
from pathlib import Path
from typing import Any

from agent.failures import classify
from agent.tools.registry import ERROR_TYPES, ToolResult


def _pairs(events: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any], int]]:
    """(tool_call payload, tool_result payload, the result's seq), in order."""
    pairs, call = [], None
    for event in events:
        if event["type"] == "tool_call":
            call = event["payload"]
        elif event["type"] == "tool_result" and call is not None:
            pairs.append((call, event["payload"], event["seq"]))
            call = None
    return pairs


def _clip(text: str, limit: int) -> str:
    """Cut at a word boundary and say so, never mid-word or mid-markup (found by the README capture)."""
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0].rstrip(" `*_,;:") + " ..."


def _summary(result: dict[str, Any]) -> str:
    data = result.get("data") or {}
    if not result.get("ok"):
        return f"{result.get('error_type')}: {str(result.get('detail', ''))[:120]}"
    if isinstance(data.get("items"), list):
        return f"{len(data['items'])} item(s)"
    if "id" in data:
        return f"row {data['id']}" + (f", status {data['status']}" if "status" in data else "")
    return str(result.get("detail", ""))[:120] or "ok"


def _business_args(run, call: dict[str, Any]) -> dict[str, Any]:
    spec = run.registry.get(call["tool"])
    hidden = spec.transport_args if spec else ()
    return {k: v for k, v in (call.get("args") or {}).items() if k not in hidden}


def _failure(call: dict[str, Any], result: dict[str, Any], seq: int) -> dict[str, Any]:
    typed = ToolResult.model_validate({k: v for k, v in result.items() if k in ToolResult.model_fields})
    return {"seq": seq, "tool": call["tool"], "error_type": result.get("error_type"), **classify(typed).model_dump(),
            "detail": str(result.get("detail", ""))[:200]}


def _recovered(call: dict[str, Any], result: dict[str, Any], seq: int) -> dict[str, Any] | None:
    """A call that succeeded after a failed attempt inside the tool (D-108's one retry), or None."""
    attempts = (result.get("data") or {}).get("attempts") or []
    failed = [a.split(": ", 1)[1] for a in attempts
              if a.startswith("attempt ") and a.split(": ", 1)[1] not in ("ok", "replayed by Acme")]
    if not result.get("ok") or not failed:
        return None
    last = attempts[-1]
    settled = (last.removeprefix("read-back ") if last.startswith("read-back found")
               else "read back: not written, so retried once" if "read-back: not written; retrying" in attempts
               else "logged in again and retried once" if "logged in again" in attempts
               else "replayed by Acme: stored once" if last.endswith("replayed by Acme") else "retried once")
    kind = classify(ToolResult.fail(failed[0], "")).kind if failed[0] in ERROR_TYPES else "escalate"
    return {"seq": seq, "tool": call["tool"], "error_type": failed[0], "kind": kind, "count": len(failed),
            "read_back": settled}


def build_report(run) -> dict[str, Any]:
    store, catalog = run.ctx.store, run.client.catalog
    events = store.events(run.run_id)
    verdict = next((e["payload"] for e in reversed(events) if e["type"] == "verifier_result"),
                   {"status": "unverified", "reasons": ["the verifier never ran"], "notes": []})
    pairs = _pairs(events)
    plans = [e["payload"] for e in events if e["type"] == "plan" and e["payload"].get("plan")
             and not e["payload"]["problems"]]  # the accepted plans only
    ok_calls = [(call, result) for call, result, _ in pairs if result.get("ok")]
    tables = catalog.session.entity_tables
    effects = verdict.get("side_effects") or {}
    refusal = next(({"reason": c["args"]["reason"], "evidence": c["args"].get("evidence", [])}
                    for c, _ in ok_calls if c["tool"] == "declare_infeasible"), None)
    findings: dict[tuple[str, str], dict[str, Any]] = {}
    for e in events:
        if e["type"] == "security_finding":
            f = e["payload"]
            findings.setdefault((f["kind"], f["excerpt"]), {
                "policy_id": f["policy_id"], "kind": f["kind"], "origin": f["origin"], "excerpt": f["excerpt"],
                "detail": f"{f['kind'].replace('_', ' ')} in {f['origin']}: {f['excerpt']}"})
    return {
        "run_id": run.run_id,
        "request": store.run(run.run_id)["request"],
        "status": verdict["status"],
        "status_reasons": verdict.get("reasons", []),
        "judge_flags": verdict.get("judge_flags", []),  # unmet fuzzy criteria the status does not show
        "notes": verdict.get("notes", []),
        "questions": [{"text": c["args"]["question"], "candidates": c["args"].get("candidates", [])}
                      for c, _ in ok_calls if c["tool"] == "ask_user"],
        "refusal": refusal,
        "security_findings": list(findings.values()),
        "evidence": [{"seq": seq, "tool": c["tool"], "args": _business_args(run, c), "ok": bool(r.get("ok")),
                      "summary": _summary(r)} for c, r, seq in pairs],
        "action_approvals": [{
            "approval_id": a.approval_id, "tool": a.predicted.get("tool"),
            "predicted": {**a.predicted.get("args", {}), "request": a.predicted.get("request"),
                          "side_effect": a.predicted.get("side_effect"), "effect": a.predicted.get("effect"),
                          "sources": a.predicted.get("sources", {})},
            "policy_ids": a.policy_ids, "reason": a.reason, "decision": a.status, "decided_by": a.decided_by,
            "used": a.consumed} for a in run.approvals.for_run(run.run_id)],
        "side_effects": [
            *({"table": tables.get(r["entity_type"], r["entity_type"]), "entity_id": r["entity_id"],
               "action": r["action"], "actor": r["actor"], "channel": r["channel"],
               "unexplained": r["unexplained"]} for r in effects.get("rows", [])),
            *({"table": tables.get(w["entity"] or "", w["entity"]), "entity_id": w["id"],
               "action": "claimed, but not in Acme's audit log", "tool": w["tool"], "claimed_not_audited": True}
              for w in effects.get("claimed_not_audited", []))],
        "failures": [_failure(c, r, seq) for c, r, seq in pairs if not r.get("ok")],
        "recovered": [r for r in (_recovered(c, res, seq) for c, res, seq in pairs) if r],
        "skipped_steps": plans[-1]["plan"].get("not_applicable", {}) if plans else {},  # SOP write steps, with why
        "replans": [{k: p.get(k) for k in ("replan", "reasons", "changed")} for p in plans if p.get("replan")],
        "escalation": next((e["payload"] for e in events if e["type"] == "escalation"), None),
        "rollback": next((e["payload"] for e in events if e["type"] == "rollback"), None),
        "predictions": [e["payload"] for e in events if e["type"] == "prediction"],  # before each irreversible write
        "narrative": [e["payload"]["text"] for e in events if e["type"] == "agent_message"],  # the agent's words
        "stops": [e["payload"]["reason"] for e in events if e["type"] == "executor_stop"],
        "verifier": {"postconditions": verdict.get("postconditions", []), "milestones": verdict.get("milestones", []),
                     "judge": verdict.get("judge", [])},
    }


def render_markdown(report: dict[str, Any]) -> str:
    """One screen: outcome first, then what a person must look at (register 7.4)."""
    lines = [f"# Run {report['run_id']}: {report['status']}", "", f"Request: {report['request']}", ""]
    lines += [f"- {r}" for r in report["status_reasons"] + [f"stopped early: {x}" for x in report.get("stops", [])]]
    lines += [f"- **judge flag:** {flag}" for flag in report.get("judge_flags", [])]
    lines += [f"- note: {note}" for note in report["notes"]]
    for q in report["questions"]:
        lines += ["", f"**Question:** {q['text']}", f"Candidates: {', '.join(q['candidates']) or 'none'}"]
    if report["refusal"]:
        lines += ["", f"**Declined:** {report['refusal']['reason']}"] + [f"- {e}" for e in report["refusal"]["evidence"]]
    for a in report["action_approvals"]:
        shown = {k: v for k, v in a["predicted"].items()
                 if k not in ("request", "side_effect", "effect") and v not in (None, {})}
        lines += ["", f"**Action approval {a['approval_id']}** ({', '.join(a['policy_ids'])}): {a['decision']}",
                  f"Would do: {a['predicted']['effect']}", "```", json.dumps(shown, indent=2, ensure_ascii=False), "```"]
    if report["security_findings"]:
        lines += ["", "**Security findings**"] + [f"- {f['policy_id']} {f['detail']}" for f in report["security_findings"]]
    lines += ["", "**What changed in Acme**"]
    lines += [f"- {s['table']} {s['entity_id']}: {s['action']}"
              + (" (UNEXPLAINED)" if s.get("unexplained") else "") for s in report["side_effects"]] or ["- nothing"]
    if report["failures"]:
        lines += ["", "**Calls that did not succeed**"] + [f"- {f['tool']}: {f['error_type']} ({f['kind']}): {f['next']}"
                                        for f in report["failures"]]
    if report["recovered"]:
        lines += ["", "**Recovered**"] + [f"- {r['tool']}: {r['error_type']} x{r['count']} ({r['kind']}): {r['read_back']}"
                                          for r in report["recovered"]]
    lines += [f"- SOP step {k} not applicable: {v}" for k, v in report.get("skipped_steps", {}).items()]
    lines += [f"- replan {r['replan']}: {'; '.join(r['reasons'] or [])[:300]}" for r in report.get("replans", [])]
    lines += [f"- escalated: {report['escalation']}"] if report.get("escalation") else []
    lines += [f"- rolled back after the rejection: {report['rollback']}"] if report.get("rollback") else []
    lines += [f"\n**The agent's own summary** (not the status): {_clip(t, 400)}" for t in report.get("narrative", [])]
    lines += ["", f"Evidence: {len(report['evidence'])} tool results in the run log."]
    return "\n".join(lines) + "\n"


def write_report(run, report: dict[str, Any]) -> Path:
    folder = run.ctx.store.path.parent / run.run_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (folder / "report.md").write_text(render_markdown(report), encoding="utf-8")
    return folder / "report.json"
