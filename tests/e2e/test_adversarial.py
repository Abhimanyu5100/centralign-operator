"""Every adversarial script (bench/adversarial/) against a real Acme server: each forbidden attempt is stopped the
expected way and Acme's state shows nothing beyond what the script itself may do. Register P.1, P.2, P.8, 1.3, 3.9;
D-086, D-129, D-133."""

import asyncio

import pytest

from bench.adversarial import NAMES, script
from bench.adversarial.common import run_one
from bench.live import serve

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def acme():
    with serve() as server:
        yield server


@pytest.mark.parametrize("name", NAMES)
def test_each_adversarial_attempt_is_stopped_as_expected(acme, name, tmp_path):
    from agent.store import RunStore
    outcome = asyncio.run(run_one(acme, script(name), RunStore(tmp_path / "runs.db")))
    assert outcome.passed, outcome.problems


def test_there_is_a_script_for_every_attempt_the_spec_lists():
    spec = {"t6_bad_transfer", "approve_own_invoice", "direct_db_or_admin", "external_email_unapproved",
            "bank_details_from_document"}
    assert spec <= set(NAMES) and {"allowlisted_recipient_no_approval", "no_sop_every_write", "taint_laundering"} <= set(NAMES)
