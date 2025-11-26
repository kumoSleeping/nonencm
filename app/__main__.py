import argparse
import sys
from pathlib import Path

def get_version():
    try:
        if sys.version_info >= (3, 11):
            import tomllib
        else:
            # For older python versions, we might need to fallback or just return a default
            # But project requires >= 3.11
            return "Unknown"
        
        # Assuming app/__main__.py is 2 levels deep from root (app/__main__.py)
        # But wait, __file__ is inside app package.
        # If run from run.py (root), __file__ of this module is .../app/__main__.py
        pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
        if pyproject_path.exists():
            with open(pyproject_path, "rb") as f:
                data = tomllib.load(f)
                return data["project"]["version"]
    except Exception:
        pass
    return "Unknown"

def main():
    parser = argparse.ArgumentParser(description="NonePyNCM CLI")
    parser.add_argument("-v", "--version", action="store_true", help="Show version and exit")
    parser.add_argument("--no-overwrite", action="store_true", help="Do not overwrite existing files")
    parser.add_argument("--use-download-api", action="store_true", help="Use standard download API instead of quality-based API")
    args = parser.parse_args()

    if args.version:
        print(get_version())
        return

    from .utils import init_log
    init_log()

    from .config import config_manager
    from .ui import ui
    from .utils import logger
    
    # Apply runtime config
    if args.no_overwrite:
        config_manager.set_runtime("overwrite", False)
    if args.use_download_api:
        config_manager.set_runtime("use_download_api", True)

    config_manager.ensure_config()
    ui.run()

if __name__ == "__main__":
    main()
