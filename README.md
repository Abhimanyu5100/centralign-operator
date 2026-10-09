# CentrAlign Operator

An AI operator that turns a short company request into completed, verified work inside a mock company (Acme).
Work in progress: the full README (setup, demo, results, tools used) is written on Day 6. Project rules live in
`CLAUDE.md`; where the build stands is in `docs/progress.md`.

## Known limitations

- **Verifier channel (D-134).** Verifier predicates are independent reads, never the write's own response, but for
  an API write that read is the same channel (an API GET). The different-channel check comes from the audit-log
  layer (Acme's own record of every write) and the harness's `/__admin/diff` cross-check. GUI writes are read back
  through the API.
- **Side effects grouped by audit timestamp (D-135).** The verifier groups Acme's audit rows into write calls by
  their `ts`, which works because Acme ticks its logical clock once per write and stamps cascaded rows with the same
  `ts`. A production system would correlate audit rows with calls by a request id.
- **Sandbox security (D-046).** Acme has no CSRF tokens and no `Secure` cookie flag (plain http on localhost and in
  Docker); dev-only default passwords can be overridden by environment variables.
- **`toast_2s` chaos accounting (D-132).** An error page made by an exception handler loses its alert after 2 s but
  is not counted as "fired".
- **Judge independence (D-189, D-193).** The verifier's judge runs on Groq `openai/gpt-oss-120b`, another model
  family than the executor and the planner (both Gemini), so it is independent of the model that did the work and of
  the one that wrote its criteria; the feasibility gate shares its model. When Groq is unavailable the judge falls
  back to Gemini Flash-Lite and the report says so. It can only lower `completed` (to `completed_with_exceptions`)
  or add flags; it never raises a status, and the deterministic layers stay authoritative.
- **Resume after an action approval is in-process (N.185).** A held call waits for the approver while the run is
  alive (`make run APPROVE_WAIT=s`); an approval given after the process ended needs a new run.
