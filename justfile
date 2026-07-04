set windows-shell := ["powershell.exe", "-NoProfile", "-Command"]

# --- Color Macros ---

info := CYAN
warn := YELLOW
error := RED
reset := NORMAL

gha := env('GITHUB_ACTIONS', 'false')
noop := if os() == "windows" { "$null" } else { "true" }

default:
    @just --list

# --- Core Application Execution ---

dev:
    @echo "{{ info }}Starting Uvicorn live reload application framework...{{ reset }}"
    @uv run uvicorn "canterlot.main:app" --reload --port 8080

start:
    @echo "{{ info }}Bootstrapping production application container...{{ reset }}"
    @uv run uvicorn "canterlot.main:app" --port 8080

# --- Environment Bootstrap & Pre-flight Checklist ---

[private]
check-deps:
    @{{ if os() == "windows" { "Get-Command uv, docker -ErrorAction Stop > $null" } else { "command -v uv >/dev/null 2>&1 && command -v docker >/dev/null 2>&1" } }}

# Emits a GitHub Actions collapsible log group; no-ops outside GITHUB_ACTIONS
[private]
group-start title:
    @{{ if gha == "true" { 'echo "::group::' + title + '"' } else { noop } }}

[private]
group-end:
    @{{ if gha == "true" { 'echo "::endgroup::"' } else { noop } }}

setup: check-deps
    @uv run python -m tools.setup

clean:
    @uv run python -m tools.clean

# --- Docker Infrastructure Control ---

# Bring up services. Usage: `just up` or `just up mongodb` or `just up mongodb redis`
up *services="":
    @echo "{{ info }}Deploying infrastructure [Targets: {{ if services == "" { "all" } else { services } }}]...{{ reset }}"
    @docker compose up -d {{ services }}

# Force build and restart services. Usage: `just rebuild` or `just rebuild mongodb redis`
rebuild *services="":
    @echo "{{ warn }}Forcing rebuild and restart [Targets: {{ if services == "" { "all" } else { services } }}]...{{ reset }}"
    @docker compose up -d --build {{ services }}

# Stop services safely. Usage: `just down` or `just down mongodb redis`
down *services="":
    @echo "{{ warn }}Decommissioning service processes [Targets: {{ if services == "" { "all" } else { services } }}]...{{ reset }}"
    @docker compose down {{ services }}

# --- Quality Gates & Linters ---

lint flags="":
    @echo "{{ info }}Running Ruff static linting checks...{{ reset }}"
    @uv run ruff check src tests tools {{ flags }}

lint-fix:
    @echo "{{ info }}Applying automatic linter fixes...{{ reset }}"
    @uv run ruff check src tests tools --fix

fmt flags="":
    @echo "{{ info }}Executing Ruff code formatters...{{ reset }}"
    @uv run ruff format src tests tools {{ flags }}

compile:
    @echo "{{ info }}Byte-compiling Python application modules...{{ reset }}"
    @uv run python -m compileall src tests tools

mypy:
    @echo "{{ info }}Running MyPy strict type analysis...{{ reset }}"
    @uv run mypy src tests tools

pyright:
    @echo "{{ info }}Running Pyright type checks...{{ reset }}"
    @uv run pyright

test:
    @echo "{{ info }}Executing test suites via Pytest...{{ reset }}"
    @uv run pytest

deptry flags="":
    @echo "{{ info }}Running dependency analysis...{{ reset }}"
    @uv run deptry src {{ flags }}

radon:
    @echo "{{ info }}Running Radon code maintainability analysis...{{ reset }}"
    @uv run radon mi --min B src tools

xenon:
    @echo "{{ info }}Running Xenon cyclomatic complexity assertions...{{ reset }}"
    @uv run xenon --max-absolute B --max-modules B --max-average A src tools

# --- Custom Python Verification Scripts ---

check-imports:
    @uv run python -m tools.check_imports

coverage:
    @echo "{{ info }}Evaluating test suite metrics and coverage...{{ reset }}"
    @uv run pytest --cov=src --cov-report=term-missing --cov-report=html --cov-report=json
    @uv run python -m tools.coverage

# --- Unified Multi-Stage Pipeline ---

# Local verification (safely applies non-breaking style auto-fixes)
verify:
    @echo "{{ info }}Starting verification pipeline...{{ reset }}"
    @just lint-fix
    @just fmt
    @just compile
    @just check-imports
    @just deptry
    @just lint
    @just mypy
    @just pyright
    @just coverage
    @just radon
    @just xenon
    @echo ""
    @echo "{{ info }}Success: All quality verification gates passed.{{ reset }}"

# CI pipeline (strict read-only execution gate, enforces no auto-fixes)
ci:
    @echo "{{ info }}Starting CI quality gate execution pipeline...{{ reset }}"
    @just group-start "Format Check"
    @just fmt --check
    @just group-end
    @just group-start "Byte Compilation"
    @just compile
    @just group-end
    @just group-start "Import Checks"
    @just check-imports
    @just group-end
    @just group-start "Dependency Analysis"
    @just deptry -go
    @just group-end
    @just group-start "Ruff Lint"
    @just lint --output-format=github
    @just group-end
    @just group-start "MyPy"
    @just mypy
    @just group-end
    @just group-start "Pyright"
    @just pyright
    @just group-end
    @just group-start "Test Coverage"
    @just coverage
    @just group-end
    @just group-start "Radon"
    @just radon
    @just group-end
    @just group-start "Xenon"
    @just xenon
    @just group-end
    @echo ""
    @echo "{{ info }}Success: Continuous integration gate checks passed.{{ reset }}"
