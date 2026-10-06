"""`make adversarial`: run every adversarial script against an in-process Acme and print expected vs. actual."""

import asyncio
import sys

from bench.adversarial import run_all
from bench.live import serve


def main() -> int:
    with serve() as acme:
        outcomes = asyncio.run(run_all(acme))
    for o in outcomes:
        print(f"{'PASS' if o.passed else 'FAIL'}  {o.name:<36} {o.expected}")
        for problem in o.problems:
            print(f"      - {problem}")
    return 0 if all(o.passed for o in outcomes) else 1


if __name__ == "__main__":
    sys.exit(main())
