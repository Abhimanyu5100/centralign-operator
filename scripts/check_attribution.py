#!/usr/bin/env python3
"""Scan commits for AI attribution or a foreign author/committer.

Usage:
  python3 scripts/check_attribution.py            # whole history
  python3 scripts/check_attribution.py A..B       # a range
Exit code 1 if anything is found. Run before pushing and before submitting.
"""
import re
import subprocess
import sys

BAD = re.compile(
    r"co-authored-by:.*(claude|anthropic)|generated with \[?claude code|claude-session:|noreply@anthropic\.com",
    re.I,
)
FOREIGN = re.compile(r"claude|anthropic", re.I)


def main(rev_range):
    allowed = subprocess.run(
        ["git", "config", "--get", "hooks.allowedAuthorEmail"], capture_output=True, text=True
    ).stdout.strip().lower()
    args = ["git", "log", "--format=%H%x00%an <%ae>%x00%cn <%ce>%x00%B%x01"]
    if rev_range:
        args.append(rev_range)
    out = subprocess.run(args, capture_output=True, text=True).stdout
    problems = []
    for rec in filter(None, (r.strip() for r in out.split("\x01"))):
        sha, author, committer, body = rec.split("\x00", 3)
        for who, ident in (("author", author), ("committer", committer)):
            email = re.search(r"<([^>]*)>", ident)
            if FOREIGN.search(ident) or (allowed and email and email.group(1).lower() != allowed):
                problems.append(f"{sha[:10]} {who}: {ident}")
        if BAD.search(body):
            problems.append(f"{sha[:10]} message contains AI attribution")
    for p in problems:
        print(p)
    if problems:
        print("\nFix before pushing: git rebase -i <base> and reword/amend, then re-run this check.")
        return 1
    print("Attribution check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))
