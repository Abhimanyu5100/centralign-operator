"""Verifier layer 3: every change Acme's audit log shows since the run started must be one the run says it made.

1. Read `list_audit` from the run's start mark (`run_start`, D-139) to the end.
2. Group the rows by `ts`: Acme ticks its logical clock once per service write and stamps cascaded rows (an
   auto-approval, the approval withdrawals of a void) with the same `ts`, so one group is one write call. This
   relies on Acme's clock; a production system would correlate by a request id (D-135, README limitation).
3. Each group holding a row by the run's own account must match an unused successful write of the run: the same
   entity (catalog `entity`; a GUI submit's `ui_forms` twin) and, when the write returned one, the same id. Any
   row of the group may match: Acme writes a cascade's withdrawals before the void itself (N.162).
4. Left-over groups are UNEXPLAINED (a failure); successful writes left without a group (and not replays of an
   earlier write) are CLAIMED BUT NOT AUDITED, which is how a silent drop shows up (a note: the write's
   postcondition or a milestone decides whether it mattered). Rows by `system` or `meera` are listed, never
   unexplained. The harness compares the rows with its own ground truth (Acme's admin diff); the agent
   never calls an admin endpoint.
"""

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel


class SideEffects(BaseModel):
    rows: list[dict[str, Any]] = []              # every audit row since the mark, flagged `unexplained`
    unexplained: list[list[dict[str, Any]]] = []  # groups by the run's account that no write of the run explains
    claimed_not_audited: list[dict[str, Any]] = []
    wrote: bool = False                           # the run's account changed anything at all


@dataclass(frozen=True)
class Write:
    tool: str
    entity: str | None
    id: int | None              # None: a GUI submit that creates a row (it returns a page, not the row)
    already_done: bool


def writes_of(catalog: Any, pairs: list[tuple[dict[str, Any], dict[str, Any]]]) -> list[Write]:
    """The run's successful writes, from (tool_call, tool_result) pairs."""
    writes = []
    for call, result in pairs:
        if not result.get("ok") or call.get("side_effect") in (None, "read"):
            continue
        data, ep = result.get("data") or {}, catalog.get(call["tool"])
        if ep is not None:
            entity, row_id = ep.entity, data.get("id")
        else:  # a browser submit: its form names the entity, and the record id when it changes one (D-155)
            path = (call.get("request") or {}).get("path", "")
            form = catalog.form(path)
            entity, row_id = (form.entity, form.target_id(path)) if form else (None, None)
        writes.append(Write(call["tool"], entity, row_id, bool(data.get("already_done"))))
    return writes


def match(rows: list[dict[str, Any]], writes: list[Write], user: str) -> SideEffects:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(row["ts"], []).append(row)
    used: set[int] = set()
    unexplained = []
    for group in groups.values():
        if not any(row["actor"] == user for row in group):
            continue
        hit = next((i for i, w in enumerate(writes) if i not in used and any(
            row["entity_type"] == w.entity and (w.id is None or row["entity_id"] == w.id) for row in group)), None)
        if hit is None:
            unexplained.append(group)
        else:
            used.add(hit)
    missing = [{"tool": w.tool, "entity": w.entity, "id": w.id} for i, w in enumerate(writes)
               if i not in used and not w.already_done]
    flagged = {row["id"] for group in unexplained for row in group}
    listed = [{"entity_type": r["entity_type"], "entity_id": r["entity_id"], "action": r["action"],
               "actor": r["actor"], "channel": r["channel"], "unexplained": r["id"] in flagged} for r in rows]
    return SideEffects(rows=listed, unexplained=unexplained, claimed_not_audited=missing,
                       wrote=any(r["actor"] == user for r in rows))


async def read_audit(run, since: int) -> list[dict[str, Any]]:
    rows = []
    while True:
        page = await run.call("list_audit", {"since": since, "limit": 1000})
        if not page.ok:
            raise RuntimeError(f"cannot read the audit log: {page.error_type}: {page.detail[:120]}")
        rows += page.data["items"]
        since = page.data["next_since"]
        if not page.data["has_more"]:
            return rows


async def side_effects(run, events: list[dict[str, Any]], pairs: list) -> SideEffects:
    mark = next((e["payload"]["audit_since"] for e in events if e["type"] == "run_start"), None)
    if mark is None:
        raise RuntimeError("the run has no start mark (run_start): its side effects cannot be bounded")
    rows = await read_audit(run, mark)
    return match(rows, writes_of(run.client.catalog, pairs), run.client.catalog.session.user)
