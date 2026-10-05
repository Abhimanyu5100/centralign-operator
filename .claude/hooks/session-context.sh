#!/usr/bin/env bash
# SessionStart hook: print where the project is, so a new, resumed, cleared or compacted session starts
# with context. Read-only. Never reads .env. Always exits 0. Output capped at 80 lines, key-like
# strings redacted. No `set -e` on purpose: a failing command must not stop the session.

cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}" 2>/dev/null || exit 0

redact() {
  sed -E \
    -e 's/AIza[0-9A-Za-z_-]{20,}/[REDACTED]/g' \
    -e 's/gsk_[0-9A-Za-z]{20,}/[REDACTED]/g' \
    -e 's/sk-[0-9A-Za-z_-]{20,}/[REDACTED]/g' \
    -e 's/(([Kk][Ee][Yy]|[Tt][Oo][Kk][Ee][Nn]|[Ss][Ee][Cc][Rr][Ee][Tt])[[:space:]]*[:=][[:space:]]*)[^[:space:]`]{8,}/\1[REDACTED]/g'
}

{
  echo "=== Project context (SessionStart hook; docs/progress.md is the source of truth, git wins) ==="
  if [ -f docs/progress.md ]; then
    awk '/^## /{p = ($0 ~ /^## Now/)} p' docs/progress.md | head -n 30
  else
    echo "docs/progress.md is missing"
  fi
  echo
  echo "--- git log --oneline -8"
  git log --oneline -8 2>/dev/null
  echo
  echo "--- git status --short"
  git status --short 2>/dev/null | head -n 15
  echo
  echo "--- open risks (docs/risk-log.md, max 10)"
  awk -F'|' 'NF >= 9 {
      s = $7; gsub(/^[ \t]+|[ \t]+$/, "", s)
      if (s == "open") {
        id = $3; pr = $4
        gsub(/^[ \t]+|[ \t]+$/, "", id); gsub(/^[ \t]+|[ \t]+$/, "", pr)
        print id ": " pr
      }
    }' docs/risk-log.md 2>/dev/null | head -n 10
} 2>/dev/null | redact | head -n 80

exit 0
