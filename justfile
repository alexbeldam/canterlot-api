# --- Color Macros ---

info := CYAN
warn := YELLOW
error := RED
reset := NORMAL

default:
    @just --list

# --- Core Application Execution ---

dev:
    @echo "{{ info }}Starting Uvicorn live reload application framework...{{ reset }}"
    @uv run uvicorn main:app --reload --port 8000

start:
    @echo "{{ info }}Bootstrapping production application container...{{ reset }}"
    @uv run uvicorn main:app --port 8000

# --- Environment Bootstrap & Pre-flight Checklist ---

setup:
    #!/usr/bin/env bash
    set -euo pipefail

    echo -e "{{ info }}=== Running Pre-flight Environment Checks ==={{ reset }}"

    if ! command -v uv &> /dev/null; then
        echo -e "{{ error }}Error: 'uv' is not installed on this system.{{ reset }}" >&2
        echo "Please install it via: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
        exit 1
    fi
    echo -e "✔ 'uv' is available."

    if ! docker compose version &> /dev/null; then
        echo -e "{{ error }}Error: 'docker compose' is not available or Docker daemon is not running.{{ reset }}" >&2
        echo "Please install Docker Desktop / Docker Engine and ensure the daemon is alive." >&2
        exit 1
    fi
    echo -e "✔ 'docker compose' is available."

    echo -e "\n{{ info }}=== Initializing Configuration ==={{ reset }}"
    if [ ! -f .env ]; then
        if [ -f .env.example ]; then
            cp .env.example .env
            echo -e "✔ Created local .env file from .env.example template."
        else
            touch .env
            echo -e "{{ warn }}WARN: No .env.example found. Created an empty .env file.{{ reset }}"
        fi
    else
        echo -e "✔ Existing .env file detected. Skipping generation."
    fi

    echo -e "\n{{ info }}=== Orchestrating Docker Infrastructure ==={{ reset }}"
    docker compose up -d

    echo -e "\n{{ info }}=== Syncing Project Dependencies ==={{ reset }}"
    uv sync

    echo -e "\n{{ info }}Local development setup is fully operational!{{ reset }}"

clean:
    @echo "{{ warn }}Cleaning project runtime caches and temporary structures...{{ reset }}"
    @rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov coverage.json
    @find . -type d -name "__pycache__" -exec rm -rf {} +
    @find . -type f -name "*.py[co]" -delete
    @echo "{{ info }}Clean operation completed successfully.{{ reset }}"

# --- Docker Infrastructure Control ---

# Bring up services. Usage: `just up` or `just up mongodb` or `just up mongodb redis`
up *services="":
    @echo "{{ info }}Deploying infrastructure [Targets: {{ if services == "" { "all" } else { services } }}]...{{ reset }}"
    docker compose up -d {{ services }}

# Force build and restart services. Usage: `just rebuild` or `just rebuild mongodb redis`
rebuild *services="":
    @echo "{{ warn }}Forcing rebuild and restart [Targets: {{ if services == "" { "all" } else { services } }}]...{{ reset }}"
    docker compose up -d --build {{ services }}

# Stop services safely. Usage: `just down` or `just down mongodb redis`
down *services="":
    @echo "{{ warn }}Decommissioning service processes [Targets: {{ if services == "" { "all" } else { services } }}]...{{ reset }}"
    docker compose down {{ services }}

# --- Quality Gates & Linters ---

lint:
    @echo "{{ info }}Running Ruff static linting checks...{{ reset }}"
    @uv run ruff check src

lint-fix:
    @echo "{{ info }}Applying automatic linter fixes...{{ reset }}"
    @uv run ruff check src --fix

fmt flags="":
    @echo "{{ info }}Executing Ruff code formatters...{{ reset }}"
    @uv run ruff format src {{ flags }}

compile:
    @echo "{{ info }}Byte-compiling Python application modules...{{ reset }}"
    @uv run python -m compileall src

mypy:
    @echo "{{ info }}Running MyPy strict type analysis...{{ reset }}"
    @uv run mypy src

pyright:
    @echo "{{ info }}Running Pyright type checks...{{ reset }}"
    @uv run pyright

test:
    @echo "{{ info }}Executing test suites via Pytest...{{ reset }}"
    @uv run pytest

# --- Custom Python Verification Scripts ---

check-imports:
    @uv run python scripts/check_imports.py

coverage:
    @echo "{{ info }}Evaluating test suite metrics and coverage...{{ reset }}"
    @uv run pytest --cov=src --cov-report=term-missing --cov-report=html --cov-report=json
    @uv run python scripts/coverage.py

radon:
    @echo "{{ info }}Running Radon code maintainability analysis...{{ reset }}"
    @uv run radon mi --min B --exclude "src/vendor/*" src

xenon:
    @echo "{{ info }}Running Xenon cyclomatic complexity assertions...{{ reset }}"
    @uv run xenon --max-absolute B --max-modules B --max-average A --exclude "src/vendor/*" src

# --- Unified Multi-Stage Pipeline ---

# Local verification (safely applies non-breaking style auto-fixes)
verify:
    @echo "{{ info }}Starting verification pipeline...{{ reset }}"
    @just lint-fix
    @just fmt
    @just compile
    @just check-imports
    @just lint
    @just mypy
    @just pyright
    @just radon
    @just xenon
    @just coverage
    @echo "\n{{ info }}Success: All quality verification gates passed.{{ reset }}"

# CI pipeline (strict read-only execution gate, enforces no auto-fixes)
ci:
    @echo "{{ info }}Starting CI quality gate execution pipeline...{{ reset }}"
    @just fmt --check
    @just compile
    @just check-imports
    @just lint
    @just mypy
    @just pyright
    @just radon
    @just xenon
    @just coverage
    @echo "\n{{ info }}Success: Continuous integration gate checks passed.{{ reset }}"
