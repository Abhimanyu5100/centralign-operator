"""T3 "Onboard Priya Nair, she joins Monday.": the onboard-employee SOP. Details from HR's offer email, the manager
resolved by email, "Monday" = 2026-10-12 (now is Wednesday 2026-10-07), two IT tickets, an internal welcome email.
The decoy Priya Natarajan is seen in the employee search and left alone."""

from agent.scripted import Step
from bench.oracles import Oracle, item

STEPS = [
    Step("list_mail", {"folder": "inbox"}),
    Step("read_mail", lambda r: {"mail_id": item(r["list_mail"], subject="Offer accepted: Priya Nair")["id"]}),
    Step("find_employees", {"q": "Priya"}, name="existing"),  # only the decoy: no record for Priya Nair yet (OE-1)
    Step("find_employees", {"q": "Sunita"}, name="manager"),
    Step("create_employee", lambda r: {
        "name": "Priya Nair", "email": "priya.nair@acme.example", "role": "Software Engineer",
        "department": "Engineering", "start_date": "2026-10-12",
        "manager_id": item(r["manager"], email="sunita.deshpande@acme.example")["id"]}),
    Step("create_it_ticket", lambda r: {"type": "laptop", "employee_id": r["create_employee"].data["id"]},
         name="laptop_ticket"),
    Step("create_it_ticket", lambda r: {"type": "accounts", "employee_id": r["create_employee"].data["id"]},
         name="accounts_ticket"),
    Step("send_mail", {"to": "priya.nair@acme.example", "subject": "Welcome to Acme, Priya",
                       "body": "Hi Priya,\n\nWelcome to Acme! Your first day is Monday, 12 Oct 2026. Your manager is "
                               "Sunita Deshpande, and your laptop and accounts are being set up.\n\nOperations"}),
    Step("list_mail", {"folder": "outbox"}, name="outbox_read_back"),
]

RUNS = {"T3": Oracle(STEPS)}
