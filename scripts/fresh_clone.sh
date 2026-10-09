#!/usr/bin/env bash
# Fresh-clone test (Day 6 G; register 0.7, M.6): what an evaluator does, from the committed HEAD only.
#   scripts/fresh_clone.sh            clone, uv sync, make test, make run TASK=T1 REPLAY=1 with no key, secret scan
#   DOCKER=1 scripts/fresh_clone.sh   also: docker compose up in the clone, /healthz, docker compose down
# The working tree's uncommitted changes are NOT tested: commit first. Run from the repo root.
set -euo pipefail

repo=$(pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
echo "== clone $(git rev-parse --short HEAD) into $tmp"
git clone -q "$repo" "$tmp/clone"
cd "$tmp/clone"

echo "== secret scan (tracked files and cassettes)"
if git ls-files -z | xargs -0 grep -nIE 'AIza[0-9A-Za-z_-]{30,}|gsk_[0-9A-Za-z]{20,}|sk-or-v1-[0-9a-f]{20,}|Bearer [A-Za-z0-9._-]{20,}' ; then
  echo "FAIL: something that looks like a key is tracked"; exit 1
fi
test ! -e .env || { echo "FAIL: .env is tracked"; exit 1; }
echo "no keys found"

echo "== uv sync"
uv sync -q
cp .env.example .env   # as the README says; every key stays empty

echo "== make test"
make test

echo "== make run TASK=T1 REPLAY=1 (no key in the environment either)"
env -u GEMINI_API_KEY -u GROQ_API_KEY -u OPENROUTER_API_KEY make run TASK=T1 REPLAY=1

echo "== make bench AGENT=1 (every recorded run replayed, no key)"
env -u GEMINI_API_KEY -u GROQ_API_KEY -u OPENROUTER_API_KEY make bench AGENT=1 NO_ADVERSARIAL=1 || echo "(the bench exits 1 when a recorded run failed, as measured live; see the table)"

if [ "${DOCKER:-0}" = 1 ]; then
  echo "== docker compose up (Acme) and /healthz"
  export COMPOSE_PROJECT_NAME=freshclone GIT_COMMIT=$(git rev-parse --short HEAD)
  docker compose build -q
  docker compose up -d acme
  for _ in $(seq 60); do curl -fs http://localhost:8000/healthz >/dev/null && break; sleep 1; done
  curl -fs http://localhost:8000/healthz && echo
  docker compose down
fi

echo "== attribution over the whole history"
python3 scripts/check_attribution.py

echo "FRESH CLONE OK at $(git rev-parse --short HEAD)"
