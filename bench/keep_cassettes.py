"""Build the committed cassettes/ from a live bench (Day 6 B, D-216). Harness side only.

`python -m bench.keep_cassettes bench/results/<live>.json` empties cassettes/ and copies in, for every bench row
(task run x chaos), the recordings of its first passing attempt: the cassette key prefixes the row's LLM calls used
(`Row.cassettes`), from that attempt's folder under the live bench's recording folder. Each row therefore replays
one real live run recorded from an empty folder. A row with no passing attempt keeps its first attempt, so the
replay bench shows that failure as measured (named in the output; never hidden). `--prune <replay>.json` then deletes every cassette a replay bench did not use (a T9 `none` recording
that `approve` overwrote, for example), so the committed set is exactly what replays.
"""

import argparse
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASSETTES = ROOT / "cassettes"


def choose(rows: list[dict]) -> tuple[dict[tuple[str, str], dict], list[str]]:
    """The first passing attempt per (run id, chaos), else its first attempt; the rows that never passed."""
    kept: dict[tuple[str, str], dict] = {}
    for row in sorted(rows, key=lambda r: r["attempt"]):
        key = (row["run_id"], row["chaos"])
        if row["passed"] and key not in kept:
            kept[key] = row
    missing = sorted({f"{r['run_id']} {r['chaos']}" for r in rows if (r["run_id"], r["chaos"]) not in kept})
    for row in sorted(rows, key=lambda r: r["attempt"]):
        kept.setdefault((row["run_id"], row["chaos"]), row)
    return kept, missing


def keep(results: list[dict], target: Path = CASSETTES) -> list[str]:
    """A later results file replaces an earlier one's rows of the same (run id, chaos): a task re-measured after a
    fix (D-215) brings its own recordings."""
    latest: dict[tuple[str, str], list[dict]] = {}
    for result in results:
        source, k = ROOT / result["meta"]["cassettes"], result["meta"]["k"]
        latest |= _group([{**row, "_source": source, "_k": k} for row in result["rows"]])
    kept, missing = choose([row for group in latest.values() for row in group])
    shutil.rmtree(target, ignore_errors=True)
    for row in kept.values():
        source, k = row["_source"], row["_k"]
        folder = source / f"a{row['attempt']}" if k > 1 else source
        for prefix in row["cassettes"]:
            found = list((folder / prefix[:2]).glob(f"{prefix}*.json"))
            if len(found) != 1:
                raise SystemExit(f"{row['run_id']} {row['chaos']}: cassette {prefix} found {len(found)} times")
            (target / prefix[:2]).mkdir(parents=True, exist_ok=True)
            shutil.copy2(found[0], target / prefix[:2] / found[0].name)
    return missing


def _group(rows: list[dict]) -> dict[tuple[str, str], list[dict]]:
    groups: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        groups.setdefault((row["run_id"], row["chaos"]), []).append(row)
    return groups


def prune(replay: dict, target: Path = CASSETTES) -> int:
    used = {p for row in replay["rows"] for p in row.get("cassettes", [])}
    removed = 0
    for path in target.glob("*/*.json"):
        if path.name[:16] not in used:
            path.unlink()
            removed += 1
    return removed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("live", type=Path, nargs="*", help="live bench results .json files (make bench AGENT=1 LIVE=1), "
                        "oldest first: a later file replaces an earlier one's rows of the same run and chaos")
    parser.add_argument("--prune", type=Path, help="a replay bench's results .json: delete the cassettes it did not use")
    args = parser.parse_args()
    if args.live:
        missing = keep([json.loads(path.read_text()) for path in args.live])
        print(f"kept {sum(1 for _ in CASSETTES.glob('*/*.json'))} cassettes; rows with no passing attempt (their "
              f"failing recording kept): {', '.join(missing) or 'none'}")
    if args.prune:
        print(f"pruned {prune(json.loads(args.prune.read_text()))} unused cassettes")


if __name__ == "__main__":
    main()
