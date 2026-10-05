# Setup and first session

Claude Code never runs `git commit` or `git push`. Every commit below is run by you, after reviewing
the changes with `git diff`.

## Day 0 (Oct 5): environment only, no API keys

1. Install Claude Code (macOS):  `curl -fsSL https://claude.ai/install.sh | bash`  then `claude --version`.
2. Create the repo and copy this pack into it (use Terminal; Finder hides the dotfiles):
   ```
   mkdir -p ~/projects/centralign-operator && cd ~/projects/centralign-operator
   git init
   cp -R ~/Downloads/centralign-handoff/. .
   cp .env.example .env        # leave the LLM keys empty until the Day 3 evening check
   ```
3. Install Docker Desktop for Mac (needed for the `docker compose up` deliverable, built Day 3 evening).
4. Make every commit yours (do this before the first commit):
   ```
   git config user.name  "Abhimanyu Singh"
   git config user.email "<the email linked to your GitHub account>"
   git config hooks.allowedAuthorEmail "<same email>"
   chmod +x .githooks/* scripts/*.py
   git config core.hooksPath .githooks
   ```
   Also turn attribution off for every project on this Mac by adding this to `~/.claude/settings.json`
   (create the file if it does not exist):
   ```
   { "attribution": { "commit": "", "pr": "" } }
   ```
   Test the hook once:
   ```
   git commit --allow-empty -m "test" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
   git log -1 --format='%an <%ae>%n%B'      # should show only your name and "test"
   git reset --hard HEAD~1                  # remove the test commit (only if it is not the first commit)
   ```
   If this is the very first commit, skip the reset and just `git commit --amend -m "Day 0: setup"`.
5. Commit: `git add -A && git commit -m "Day 0: project brief and docs"`.
6. Before every push and before submitting: `python3 scripts/check_attribution.py`.

## Day 1 (Oct 6): first prompt to Claude Code

Start `claude` in the repo and paste:

> Read CLAUDE.md and every file in docs/, especially docs/acme-spec.md. We are in Phase A: no LLM
> code and no API keys. Run /risk-check "Day 1: Acme sandbox". After I confirm, set up a
> Python 3.12 project (uv or venv) with fastapi, uvicorn, jinja2, pydantic, reportlab, pypdf,
> playwright, pytest, python-dotenv, and run `playwright install chromium`. Then build the Acme sandbox
> in this order: (1) data model, service layer with audit log, business rules (auto-approval, payment
> requests, undo paths), seed and reset with frozen `now`; (2) login and roles; (3) UI pages and forms
> with server-side validation; (4) read and write API with idempotency keys, undo endpoints and
> `GET /api/audit`; (5) mailbox, including the HR offer email; (6) PDF generator; (7) knowledge files
> (SOPs, policies.yaml with `enforced_by`); (8) admin endpoints (reset, snapshot, state_hash, diff,
> chaos); (9) the five Day 1 chaos profiles (the other four are Day 3); (10) task YAMLs T1–T9 with SQL
> checkers and checker tests. Stop after each numbered part and show me what changed. Do not run
> git commit or git push; I review with git diff and commit myself.

## Day 3 (Oct 8) evening: Docker and the provider check

1. Dockerfile and `docker compose` (Acme plus runner), built with Claude Code as part of Day 3.
2. Manual provider check, 5 minutes per provider, outside the repo (no LLM code before Day 4):
   create the keys (Google AI Studio, Groq, OpenRouter), fill `.env`, copy the exact model IDs from each
   console, then make one forced tool call per provider:
   ```
   set -a; source .env; set +a
   # repeat with GROQ_* and OPENROUTER_* values
   curl -s "${GEMINI_BASE_URL%/}/chat/completions" \
     -H "Authorization: Bearer $GEMINI_API_KEY" -H "Content-Type: application/json" \
     -d '{"model":"'"$GEMINI_MODEL"'","messages":[{"role":"user","content":"Add 2 and 3 using the tool."}],
          "tools":[{"type":"function","function":{"name":"add","description":"Add two integers",
          "parameters":{"type":"object","properties":{"a":{"type":"integer"},"b":{"type":"integer"}},
          "required":["a","b"]}}}],"tool_choice":"required"}'
   ```
   A pass is a `tool_calls` entry for `add` with `{"a":2,"b":3}`. If a provider rejects
   `"tool_choice":"required"`, retry with `"auto"`.
3. Record the live limits in `docs/model-plan.md`. If Gemini Flash shows under about 500 requests per
   day, enable billing on that AI Studio project (plan B, already approved).

## Day 4 (Oct 9): LLM code

Keys already exist from the Day 3 evening check. First task of the day: the LLM smoke test through
`LLMClient` (one forced tool call per provider), following `docs/model-plan.md`.

## Day 6 (Oct 11): fresh-clone test

Clone the repo into a new directory (ideally a second machine), then run `docker compose up` and the
demo in `REPLAY=1` mode with no keys.
