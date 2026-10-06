"""AcmeBench adversarial scripts (bench/adversarial/<name>.py): each attempts a forbidden call on purpose and must be
stopped the expected way (acme-spec "Checkers, oracles and adversarial scripts"; D-086, D-129, D-133).
`run_all(acme)` runs every script on its own reset and returns one Outcome each. Shared parts: common.py."""

import importlib

from agent.store import RunStore
from bench.adversarial.common import Outcome, Script, run_one

NAMES = ["t6_bad_transfer", "approve_own_invoice", "direct_db_or_admin", "external_email_unapproved",
         "bank_details_from_document", "allowlisted_recipient_no_approval", "no_sop_every_write", "taint_laundering"]


def script(name: str) -> Script:
    return importlib.import_module(f"bench.adversarial.{name}").SCRIPT


async def run_all(acme, store: RunStore | None = None) -> list[Outcome]:
    from bench.live import BENCH_STORE
    store = store or RunStore(BENCH_STORE)  # never the operator's store: the inbox shows only real runs (N.164)
    return [await run_one(acme, script(name), store) for name in NAMES]
