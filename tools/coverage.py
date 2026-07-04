import json
import os
import sys
from pathlib import Path

IS_CI = os.getenv("GITHUB_ACTIONS") == "true"
MIN_COVERAGE_PERCENT = 95

COLOR_RED = "\033[31m"
COLOR_GREEN = "\033[32m"
COLOR_RESET = "\033[0m"


def _emit_error(message: str) -> None:
    print(f"::error::{message}" if IS_CI else f"{COLOR_RED}Error: {message}{COLOR_RESET}")


def _load_coverage_data(coverage_file: Path) -> dict:
    if not coverage_file.exists():
        _emit_error("coverage.json not found. Did tests run successfully?")
        sys.exit(1)

    try:
        with open(coverage_file) as f:
            data: dict = json.load(f)
            return data
    except json.JSONDecodeError:
        _emit_error("coverage.json is corrupted or invalid.")
        sys.exit(1)


def _report_undercovered_file(filename: str, pct_rounded: float) -> None:
    if IS_CI:
        print(f"::error file={filename}::Coverage is {pct_rounded}%, needs to be >= {MIN_COVERAGE_PERCENT}%")
    else:
        print(
            f"{COLOR_RED}FAIL:{COLOR_RESET} {filename} dropped to {pct_rounded}% coverage (min {MIN_COVERAGE_PERCENT}%)"
        )


def _find_undercovered_files(files: dict) -> list[str]:
    undercovered = []

    for filename, file_data in files.items():
        pct = file_data.get("summary", {}).get("percent_covered", 0)

        if pct < MIN_COVERAGE_PERCENT:
            _report_undercovered_file(filename, round(pct, 2))
            undercovered.append(filename)

    return undercovered


def main():
    data = _load_coverage_data(Path("coverage.json"))
    undercovered = _find_undercovered_files(data.get("files", {}))

    if undercovered:
        error_msg = f"\nFail: One or more files fell below the {MIN_COVERAGE_PERCENT}% coverage threshold."
        if not IS_CI:
            print(f"{COLOR_RED}{error_msg}{COLOR_RESET}")
        sys.exit(1)

    success_msg = f"\nSuccess: All files meet the {MIN_COVERAGE_PERCENT}% coverage requirement!"
    print(success_msg if IS_CI else f"{COLOR_GREEN}{success_msg}{COLOR_RESET}")


if __name__ == "__main__":
    main()
