#!/usr/bin/env python
import json
import os
import sys
from pathlib import Path

IS_CI = os.getenv("GITHUB_ACTIONS") == "true"

COLOR_RED = "\033[31m"
COLOR_GREEN = "\033[32m"
COLOR_RESET = "\033[0m"


def main():
    coverage_file = Path("coverage.json")

    if not coverage_file.exists():
        msg = "coverage.json not found. Did tests run successfully?"
        print(f"::error::{msg}" if IS_CI else f"{COLOR_RED}Error: {msg}{COLOR_RESET}")
        sys.exit(1)

    try:
        with open(coverage_file) as f:
            data = json.load(f)
    except json.JSONDecodeError:
        msg = "coverage.json is corrupted or invalid."
        print(f"::error::{msg}" if IS_CI else f"{COLOR_RED}Error: {msg}{COLOR_RESET}")
        sys.exit(1)

    failed = False
    files = data.get("files", {})

    for filename, file_data in files.items():
        pct = file_data.get("summary", {}).get("percent_covered", 0)
        pct_rounded = round(pct, 2)

        if pct < 80:
            if IS_CI:
                print(f"::error file={filename}::Coverage is {pct_rounded}%, needs to be >= 80%")
            else:
                print(f"{COLOR_RED}FAIL:{COLOR_RESET} {filename} dropped to {pct_rounded}% coverage (min 80%)")
            failed = True

    if failed:
        error_msg = "\nFail: One or more files fell below the 80% coverage threshold."
        if not IS_CI:
            print(f"{COLOR_RED}{error_msg}{COLOR_RESET}")
        sys.exit(1)

    success_msg = "\nSuccess: All files meet the 80% coverage requirement!"
    print(success_msg if IS_CI else f"{COLOR_GREEN}{success_msg}{COLOR_RESET}")


if __name__ == "__main__":
    main()
