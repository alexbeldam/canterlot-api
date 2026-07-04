import subprocess
import sys
from pathlib import Path


def ensure_env() -> None:
    env = Path(".env")

    if env.exists():
        print("✓ Existing .env found.")
        return

    example = Path(".env.example")

    if example.exists():
        env.write_text(example.read_text())
        print("✓ Created .env from .env.example.")
        print("  \033[33m⚠ Remember to replace placeholder values in your '.env' file.\033[0m")
    else:
        env.touch()
        print("⚠ Created empty .env.")


def run(*args: str) -> None:
    print("+", *args)
    subprocess.run(args, check=True)


def main() -> int:
    print("=== Initializing Configuration ===")
    ensure_env()
    print()

    run("docker", "compose", "up", "-d")

    print()
    print("✓ Setup complete.")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
