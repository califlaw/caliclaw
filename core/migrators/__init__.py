"""Auto-discover and register all migrator modules in this package."""
import importlib
import pkgutil
from pathlib import Path

_pkg_dir = Path(__file__).parent

for _, module_name, _ in pkgutil.iter_modules([str(_pkg_dir)]):
    importlib.import_module(f"{__name__}.{module_name}")
