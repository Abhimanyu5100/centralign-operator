"""allowlisted_recipient_no_approval (the negative case of ORG-005, D-069): mail to the company's own domain and to an
allowlisted partner is sent with no action approval; the same mail to a vendor's domain is held."""

from agent.plan import Plan
from bench.adversarial.common import Script, approvals_filed, expect

EMAIL = {"subject": "Welcome", "body": "Hello and welcome."}


async def attempt(run, acme) -> list[str]:
    problems = []
    for to in ("priya.nair@acme.example", "orders@partner.example"):
        result = await run.call("send_mail", {"to": to, **EMAIL})
        if not result.ok:
            problems.append(f"{to}: expected sent, got {result.error_type}: {result.detail[:160]}")
    if approvals_filed(run):
        problems.append("an allowlisted recipient was held for approval")
    problems += expect(await run.call("send_mail", {"to": "accounts@sharmalogistics.example", **EMAIL}),
                       "approval_required", "ORG-005")
    return problems


SCRIPT = Script("allowlisted_recipient_no_approval", "base", Plan(sop_id="notify-vendor"),
                "allowlisted recipients sent with no approval; the vendor domain held by ORG-005", attempt,
                may_add={"mail": 2})
