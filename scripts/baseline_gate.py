#!/usr/bin/env python3
"""Fail on any pytest FAILED/ERROR beyond tests/baseline_failures.txt.

Usage: python scripts/baseline_gate.py <pytest-output.txt> [--baseline tests/baseline_failures.txt]
Feed it the output of `pytest -rfE ...`. Known baseline failures are tolerated; baseline entries that now
pass are reported (so the baseline can be trimmed) but do not fail the check.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINE = re.compile(r"^(FAILED|ERROR) (\S+)")


def parse(text: str) -> set:
    return {f"{m.group(1)} {m.group(2)}" for line in text.splitlines() if (m := LINE.match(line))}


def main(argv) -> int:
    args = [a for a in argv if not a.startswith("--")]
    base_path = ROOT / "tests/baseline_failures.txt"
    if "--baseline" in argv:
        base_path = Path(argv[argv.index("--baseline") + 1])
        args = [a for a in args if a != str(base_path)]
    if not args:
        print(__doc__)
        return 2
    seen = parse(Path(args[0]).read_text(encoding="utf-8", errors="replace"))
    baseline = parse(base_path.read_text(encoding="utf-8"))
    new, fixed = sorted(seen - baseline), sorted(baseline - seen)
    for f in fixed:
        print(f"note: baseline entry no longer failing: {f}")
    if new:
        print(f"{len(new)} failure(s) beyond baseline:")
        for f in new:
            print(f"  {f}")
        return 1
    print(f"OK: {len(seen)} failure(s), all in baseline ({len(baseline)} entries).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
