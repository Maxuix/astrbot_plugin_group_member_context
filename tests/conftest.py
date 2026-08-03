"""Make the repository root importable as AstrBot's installed plugin package."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys


PACKAGE_NAME = "astrbot_plugin_group_member_context"
PLUGIN_ROOT = Path(__file__).resolve().parents[1]


if PACKAGE_NAME not in sys.modules:
    package_spec = spec_from_file_location(
        PACKAGE_NAME,
        PLUGIN_ROOT / "__init__.py",
        submodule_search_locations=[str(PLUGIN_ROOT)],
    )
    if package_spec is None or package_spec.loader is None:
        raise RuntimeError(f"Unable to load test package from {PLUGIN_ROOT}")
    package = module_from_spec(package_spec)
    sys.modules[PACKAGE_NAME] = package
    package_spec.loader.exec_module(package)
