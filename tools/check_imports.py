import importlib
import inspect
import os
import sys
import traceback
from pathlib import Path

TARGET_DIR = "src"


def discover_modules() -> list[str]:
    modules: set[str] = set()
    for file in Path(TARGET_DIR).rglob("*.py"):
        relative = file.relative_to(TARGET_DIR)

        if file.name == "__init__.py":
            module = ".".join(relative.parent.parts)
            if module:
                modules.add(module)
            continue
        modules.add(".".join(relative.with_suffix("").parts))
    return sorted(modules)


def get_exported_symbols(module) -> list[str]:
    if hasattr(module, "__all__"):
        return list(module.__all__)

    exports = []
    for name, obj in inspect.getmembers(module):
        if name.startswith("_"):
            continue

        obj_module = getattr(obj, "__module__", None)
        if inspect.isclass(obj) or inspect.isfunction(obj) or inspect.ismethod(obj):
            if obj_module == module.__name__:
                exports.append(name)
        else:
            exports.append(name)
    return sorted(set(exports))


def _ensure_target_on_path() -> None:
    target_path = os.path.abspath(TARGET_DIR)
    if target_path not in sys.path:
        sys.path.insert(0, target_path)


def _discover_local_roots() -> set[str]:
    local_roots = {
        p.relative_to(TARGET_DIR).parts[0] for p in Path(TARGET_DIR).iterdir() if p.is_dir() or p.suffix == ".py"
    }
    local_roots.discard("__pycache__")
    return local_roots


def _evict_cached_modules(local_roots: set[str]) -> None:
    for cached_key in list(sys.modules.keys()):
        if any(cached_key == root or cached_key.startswith(f"{root}.") for root in local_roots):
            del sys.modules[cached_key]


def _verify_module_symbols(module) -> bool:
    all_ok = True

    for symbol in get_exported_symbols(module):
        try:
            getattr(module, symbol)
        except Exception:
            all_ok = False
            print(f"  Error: Failed to load symbol: {symbol}")
            traceback.print_exc()

    return all_ok


def _verify_module(module_name: str) -> bool:
    print(f"Module: {module_name}")

    try:
        module = importlib.import_module(module_name)
        print("  Status: Imported successfully")
    except Exception:
        print("  Error: Module import failed")
        traceback.print_exc()
        return False

    return _verify_module_symbols(module)


def verify_imports() -> bool:
    print("============================================================")
    print("Verifying Module Imports and Exported Symbols")
    print("============================================================")

    _ensure_target_on_path()
    local_roots = _discover_local_roots()

    all_ok = True
    for module_name in discover_modules():
        _evict_cached_modules(local_roots)
        if not _verify_module(module_name):
            all_ok = False

    print("------------------------------------------------------------")
    if all_ok:
        print("Success: All entrypoints and symbols verified.\n")
    else:
        print("Failure: Dynamic verification anomalies detected.\n")
    return all_ok


def main() -> None:
    if not verify_imports():
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
