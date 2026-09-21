#!/usr/bin/env python3
"""Optional: check that everything in saved_runs/ still opens.

    python validate_saved_runs.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from core import load_saved, run_summary

# Only fires on the shape of a real key, so it stays silent unless something is actually wrong.
KEY_SHAPES = re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}|\btvly-[A-Za-z0-9_\-]{10,}"
                        r'|"(?:x-api-key|authorization|x-subscription-token)"\s*:\s*"[^"]{12,}"', re.I)


def main():
    files = sorted(Path("saved_runs").glob("*.json"))
    if not files:
        print("No saved runs yet.")
        return 0
    bad = 0
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
            summary = run_summary(load_saved(text))
        except (ValueError, KeyError, TypeError, OSError, UnicodeDecodeError) as exc:
            print(f"BROKEN  {path.name}: {exc}")
            bad += 1
            continue
        verdicts = ", ".join(f"{p}:{v}" for p, v in summary["verdicts"].items()) or "no briefs"
        print(f"ok      {path.name}: {summary['company']} | {verdicts}")
        if KEY_SHAPES.search(text.replace("[REDACTED API KEY]", "")):
            print("        check this one: it contains something shaped like an API key")
            bad += 1
    print(f"\n{len(files) - bad}/{len(files)} ready.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
