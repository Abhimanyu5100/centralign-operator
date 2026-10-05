# Setup and first session

## Day 0 (Oct 5): environment only, no API keys

1. Install Claude Code (macOS):  `curl -fsSL https://claude.ai/install.sh | bash`  then `claude --version`.
2. Create the repo and copy this pack into it (use Terminal; Finder hides the dotfiles):
   ```
   mkdir -p ~/projects/centralign-operator && cd ~/projects/centralign-operator
   git init
   cp -R ~/Downloads/centralign-handoff/. .
   cp .env.example .env        # leave the LLM keys empty until Day 4
   ```
3. Install Docker Desktop for Mac (needed for the `docker compose up` deliverable).
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
> code and no API keys until Day 4. Run /risk-check "Day 1: Acme sandbox". After I confirm, set up a
> Python 3.12 project (uv or venv) with fastapi, uvicorn, jinja2, pydantic, reportlab, pypdf,
> playwright, pytest, python-dotenv, and run `playwright install chromium`. Then build the Acme sandbox
> in this order, committing after each: (1) data model, service layer with audit log, seed and reset;
> (2) login and roles; (3) UI pages and forms with server-side validation; (4) read and write API with
> idempotency keys; (5) mailbox; (6) PDF generator; (7) knowledge files (SOPs, policies.yaml);
> (8) admin endpoints (reset, snapshot, state_hash, diff, chaos); (9) chaos profiles; (10) task YAMLs
> T1–T8 with SQL checkers and checker tests. Stop after each numbered part and show me what changed.

## Day 4 (Oct 9): LLM keys

Only now create the keys (Google AI Studio, Groq) and fill `.env`, following `docs/model-plan.md`.
First task of the day: the LLM smoke test (one forced tool call per provider).
