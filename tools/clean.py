import shutil
from pathlib import Path

DIRECTORIES = [
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "htmlcov",
    "dist",
]

FILES = [
    ".coverage",
    "coverage.json",
]


def remove_directory(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
        print(f"Removed {path}")


def remove_file(path: Path) -> None:
    if path.exists():
        path.unlink()
        print(f"Removed {path}")


def main() -> None:
    for name in DIRECTORIES:
        remove_directory(Path(name))

    for name in FILES:
        remove_file(Path(name))

    for path in Path(".").rglob("__pycache__"):
        shutil.rmtree(path)

    for path in Path(".").rglob("*.egg-info"):
        shutil.rmtree(path)

    for path in Path(".").rglob("*.pyc"):
        path.unlink()

    for path in Path(".").rglob("*.pyo"):
        path.unlink()

    print("✓ Clean complete.")


if __name__ == "__main__":
    main()
