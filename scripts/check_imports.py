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


def verify_imports() -> bool:
    print("============================================================")
    print("Verifying Module Imports and Exported Symbols")
    print("============================================================")

    target_path = os.path.abspath(TARGET_DIR)
    if target_path not in sys.path:
        sys.path.insert(0, target_path)

    local_roots = {
        p.relative_to(TARGET_DIR).parts[0] for p in Path(TARGET_DIR).iterdir() if p.is_dir() or p.suffix == ".py"
    }

    local_roots.discard("__pycache__")

    all_ok = True

    for module_name in discover_modules():
        print(f"Module: {module_name}")

        for cached_key in list(sys.modules.keys()):
            if any(cached_key == root or cached_key.startswith(f"{root}.") for root in local_roots):
                del sys.modules[cached_key]

        try:
            module = importlib.import_module(module_name)
            print("  Status: Imported successfully")

            for symbol in get_exported_symbols(module):
                try:
                    getattr(module, symbol)
                except Exception:
                    all_ok = False
                    print(f"  Error: Failed to load symbol: {symbol}")
                    traceback.print_exc()
        except Exception:
            all_ok = False
            print("  Error: Module import failed")
            traceback.print_exc()

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
