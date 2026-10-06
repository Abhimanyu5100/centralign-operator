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
- `verifier`: what each check found.

The event log is already redacted (D-104), so the report never holds a secret. `write_report` saves
`runs/<run_id>/report.json` and a one-screen `report.md`.
"""

import json
from pathlib import Path
from typing import Any

from agent.failures import classify
from agent.tools.registry import ToolResult


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


def _summary(result: dict[str, Any]) -> str:
    data = result.get("data") or {}
    if not result.get("ok"):
        return f"{result.get('error_type')}: {str(result.get('detail', ''))[:120]}"
    if isinstance(data.get("items"), list):
        return f"{len(data['items'])} item(s)"
    if "id" in data:
        return f"row {data['id']}" + (f", status {data['status']}" if "status" in data else "")
    return str(result.get("detail", ""))[:120] or "ok"


def _failure(call: dict[str, Any], result: dict[str, Any], seq: int) -> dict[str, Any]:
    typed = ToolResult.model_validate({k: v for k, v in result.items() if k in ToolResult.model_fields})
    return {"seq": seq, "tool": call["tool"], "error_type": result.get("error_type"), **classify(typed).model_dump(),
            "detail": str(result.get("detail", ""))[:200]}


def build_report(run) -> dict[str, Any]:
    store, catalog = run.ctx.store, run.client.catalog
    events = store.events(run.run_id)
    verdict = next((e["payload"] for e in reversed(events) if e["type"] == "verifier_result"),
                   {"status": "unverified", "reasons": ["the verifier never ran"], "notes": []})
    pairs = _pairs(events)
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
        "notes": verdict.get("notes", []),
        "questions": [{"text": c["args"]["question"], "candidates": c["args"].get("candidates", [])}
                      for c, _ in ok_calls if c["tool"] == "ask_user"],
        "refusal": refusal,
        "security_findings": list(findings.values()),
        "evidence": [{"seq": seq, "tool": c["tool"], "args": c.get("args", {}), "ok": bool(r.get("ok")),
                      "summary": _summary(r)} for c, r, seq in pairs],
        "action_approvals": [{
            "approval_id": a.approval_id, "tool": a.predicted.get("tool"),
            "predicted": {**a.predicted.get("args", {}), "request": a.predicted.get("request"),
                          "side_effect": a.predicted.get("side_effect"), "effect": a.predicted.get("effect")},
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
        "verifier": {"postconditions": verdict.get("postconditions", []), "milestones": verdict.get("milestones", [])},
    }


def render_markdown(report: dict[str, Any]) -> str:
    """One screen: outcome first, then what a person must look at (register 7.4)."""
    lines = [f"# Run {report['run_id']}: {report['status']}", "", f"Request: {report['request']}", ""]
    lines += [f"- {reason}" for reason in report["status_reasons"]]
    lines += [f"- note: {note}" for note in report["notes"]]
    for q in report["questions"]:
        lines += ["", f"**Question:** {q['text']}", f"Candidates: {', '.join(q['candidates']) or 'none'}"]
    if report["refusal"]:
        lines += ["", f"**Declined:** {report['refusal']['reason']}"] + [f"- {e}" for e in report["refusal"]["evidence"]]
    for a in report["action_approvals"]:
        shown = {k: v for k, v in a["predicted"].items()
                 if k not in ("request", "side_effect", "effect") and v is not None}
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
    lines += ["", f"Evidence: {len(report['evidence'])} tool results in the run log."]
    return "\n".join(lines) + "\n"


def write_report(run, report: dict[str, Any]) -> Path:
    folder = run.ctx.store.path.parent / run.run_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (folder / "report.md").write_text(render_markdown(report), encoding="utf-8")
    return folder / "report.json"
