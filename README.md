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
