"""What the gate may know about a run: a read-only view of the run's own event log (D-127, D-133, D-126).

`RunFacts.of(run_id)` reads the log once and answers four questions. Everything comes from what the run's tools
returned, so `check()` stays pure (no Acme call, no write) and the answers are the same after a pause and resume.

- `untrusted`: values (emails, account numbers, IFSC codes, rupee amounts) seen in tool results tagged
  `provenance.source == "untrusted"`: mail, PDF text, browser pages.
- `trusted`: the same kinds of values in the run's request text and in the top-level fields of business rows
  (vendor, invoice, approval, payment, employee, IT ticket) returned by API reads, except rows this run created
  and rows the agent's account created. Write results, nested sub-rows, mail, audit rows and pages never count,
  so a value the agent wrote into Acme cannot come back as trusted (taint laundering, D-133).
- `vendor_status`: the latest status of each vendor this run read through a trusted read (ORG-002, D-127).
- `created`: (entity, id) of rows this run created: rows its API writes returned, plus rows a `list_audit` result
  shows the agent's account inserted after the run's start mark (how a GUI write is found, D-126, D-128).
"""

from dataclasses import dataclass, field
from typing import Any

from agent.policy.scanner import normalise_value, strings, values
from agent.store import RunStore

TRUSTED_ENTITIES = frozenset({"vendor", "invoice", "approval", "payment", "employee", "it_ticket"})


@dataclass(frozen=True)
class Facts:
    untrusted: frozenset[str] = frozenset()
    trusted: frozenset[str] = frozenset()
    vendor_status: dict[int, str] = field(default_factory=dict)
    created: frozenset[tuple[str, int]] = frozenset()


def calls(events: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """(tool_call payload, tool_result payload) pairs in order. Calls run one at a time, so each tool_result
    belongs to the tool_call logged just before it."""
    pairs, call = [], None
    for event in events:
        if event["type"] == "tool_call":
            call = event["payload"]
        elif event["type"] == "tool_result" and call is not None:
            pairs.append((call, event["payload"]))
            call = None
    return pairs


def inserted(audit_row: dict[str, Any]) -> bool:
    """An audit row that created its record: Acme's audit API gives `before: null` for an insert. A row without
    the key is not taken as one (a missing field must never widen what the run is allowed to undo)."""
    return "before" in audit_row and audit_row["before"] is None


def _rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    items = data.get("items")
    return [r for r in items if isinstance(r, dict)] if isinstance(items, list) else [data]


def _scalar_values(row: dict[str, Any]) -> set[str]:
    """Values in a row's own fields; nested lists and objects (embedded sub-rows) are left out on purpose."""
    found = set()
    for value in row.values():
        if isinstance(value, str):
            found |= values(value) | {normalise_value(value)}
        elif isinstance(value, int) and not isinstance(value, bool):
            found.add(str(value))
    return found


class RunFacts:
    def __init__(self, store: RunStore, catalog: Any):
        self.store = store
        self.catalog = catalog  # agent.tools.api.Catalog: each tool's entity and path parameters, the agent's login

    def _entity(self, tool: str) -> str | None:
        ep = self.catalog.get(tool)
        return ep.entity if ep else None

    def _creates(self, tool: str) -> bool:
        """A write to a collection (no path parameter) creates the row it returns; an undo changes an existing one."""
        ep = self.catalog.get(tool)
        return ep is not None and ep.side_effect != "read" and not ep.path_params

    def of(self, run_id: str) -> Facts:
        events = self.store.events(run_id)
        pairs = [(c, r) for c, r in calls(events) if r.get("ok")]
        user = self.catalog.session.user
        mark = next((e["payload"]["audit_since"] for e in events if e["type"] == "run_start"), None)

        created: set[tuple[str, int]] = set()
        for call, result in pairs:
            data, entity = result.get("data") or {}, self._entity(call["tool"])
            if self._creates(call["tool"]) and isinstance(data.get("id"), int):
                created.add((entity, data["id"]))
            if entity == "audit" and mark is not None:
                created |= {(r["entity_type"], r["entity_id"]) for r in _rows(data)
                            if r.get("actor") == user and inserted(r) and r.get("id", 0) > mark}

        untrusted: set[str] = set()
        trusted = set(values(self.store.run(run_id)["request"]))
        vendors: dict[int, str] = {}
        for call, result in pairs:
            data = result.get("data") or {}
            if (data.get("provenance") or {}).get("source") == "untrusted":
                untrusted |= {v for text in strings(data) for v in values(text)}
                continue
            entity = self._entity(call["tool"])
            if call.get("side_effect") != "read" or entity not in TRUSTED_ENTITIES:
                continue
            for row in _rows(data):
                own = any(row.get(f) == user for f in self.catalog.session.creator_fields)
                if not isinstance(row.get("id"), int) or (entity, row["id"]) in created or own:
                    continue
                trusted |= _scalar_values(row)
                if entity == "vendor" and isinstance(row.get("status"), str):
                    vendors[row["id"]] = row["status"]
        return Facts(frozenset(untrusted), frozenset(trusted), vendors, frozenset(created))

