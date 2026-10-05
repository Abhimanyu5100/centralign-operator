# Risk log

New risks discovered while building. Claude Code appends here; IDs continue as N.1, N.2, ...
Statuses: open · handled · tested · accepted (with reason).

| Date | ID | Problem | How it shows up | How we handle it | Status | Test |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-10-05 | N.1 | LLM work compressed into Days 4–6 | Executor not working until late; no time to tune | Phase A finishes every non-LLM part so Phase B only adds LLM calls behind tested interfaces; hard gate end of Day 4 triggers cuts | open | Invoice task by LLM executor on Day 4 |
| 2026-10-05 | N.2 | Interfaces built without an LLM don't fit one | Tool schemas or observations too verbose or ambiguous for a model | Tool schemas written LLM-ready from Day 2; scripted agent uses the same `registry.call` path; observation size measured in Phase A | open | Day 4 smoke run on the invoice task |
| 2026-10-05 | N.3 | Provider surprises found late | Gemini OpenAI-compat tool calling or quotas don't work as expected | Smoke test is the first thing on Day 4; fallback to native SDK or Groq; billing as plan B | open | Day 4 morning smoke test |
| 2026-10-05 | N.4 | Oracles pass but encode the wrong behaviour | Checkers and oracles agree with each other but not with the SOPs | Oracles written from the SOP text, reviewed against acme-spec expected outcomes; checker tests include failing states | open | Checker failing-state tests |
| 2026-10-05 | N.5 | Sandbox gold-plating | Day 1 spills into Day 2 | Spec is the ceiling; plain HTML; stop-after-each-part prompt | open | Day 1 definition of done met by end of day |
| 2026-10-05 | N.6 | AI attribution or a foreign identity lands in git history | `Co-Authored-By: Claude` / `Claude-Session:` trailers or a Claude author in commits | Three layers: settings attribution off + denied git commands; commit-msg hook strips trailers and refuses other authors; pre-push scan; final `check_attribution.py` | handled | Hook test in SETUP.md step 4 |
| 2026-10-05 | N.7 | Hooks bypassed | `--no-verify` or hooks not executable after unzip | Denied in settings (prefix rules are best-effort); `chmod +x` in setup; final whole-history scan before submission | open | `check_attribution.py` passes on Oct 11 |
| 2026-10-05 | N.8 | Clean commits read as hiding AI use | Reviewer notices fast, polished commits with no disclosure | README lists Claude Code under tools used, as the JD requires | open | README "Tools used" section |
