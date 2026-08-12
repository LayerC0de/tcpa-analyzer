#!/usr/bin/env python3
"""Validate corpus contributions. Run by CI on every pull request.

This is a GATE, not a linter. Reviewers cannot reliably eyeball whether a JSON
file leaks personal data, so anything outside the allowlist fails the build
automatically. A contributor cannot merge a field we did not anticipate, however
well-intentioned the addition.

    python scripts/validate_contribution.py corpus/*.json
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tcpa.report.contribute import audit  # noqa: E402


def main(argv: list[str]) -> int:
    paths = [Path(p) for p in argv] or sorted((ROOT / "corpus").glob("*.json"))
    paths = [p for p in paths if p.name != "README.md"]
    if not paths:
        print("no contributions to validate")
        return 0

    failed = 0
    for path in paths:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"FAIL {path.name}: invalid JSON -- {exc}")
            failed += 1
            continue

        problems = audit(doc)
        if problems:
            failed += 1
            print(f"FAIL {path.name}")
            for p in problems:
                print(f"     {p}")
        else:
            n = len(doc.get("numbers", []))
            fid = doc.get("fingerprint", {}).get("id", "?")
            print(f"ok   {path.name}  campaign {fid}, {n} numbers")

    if failed:
        print(f"\n{failed} contribution(s) rejected.")
        print("Contributions must contain ONLY the caller's infrastructure --")
        print("no recipient number, name, location, duration, or exact timestamp.")
        return 1
    print(f"\nall {len(paths)} contribution(s) clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
