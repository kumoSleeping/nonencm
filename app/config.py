import yaml
from pathlib import Path
from typing import Dict, Any, Optional
from noneprompt import InputPrompt, CancelledError
from .utils import logger

class ConfigManager:
    def __init__(self, config_path: str = "nonencm_config.yaml"):
        self.config_path = Path(config_path)
        self.config: Dict[str, Any] = {}
        self.load_config()

    def load_config(self):
        """Load configuration from YAML file."""
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    self.config = yaml.safe_load(f) or {}
                logger.success(f"Loaded configuration from {self.config_path}")
            except Exception as e:
                logger.error(f"Failed to load config: {e}")
                self.config = {}
        else:
            logger.warning(f"Configuration file {self.config_path} not found.")
            self.config = {}

    def save_config(self):
        """Save configuration to YAML file."""
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                yaml.dump(self.config, f, allow_unicode=True, default_flow_style=False)
            logger.info(f"Saved configuration to {self.config_path}")
        except Exception as e:
            logger.error(f"Failed to save config: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value."""
        return self.config.get(key, default)

    def set(self, key: str, value: Any):
        """Set a configuration value and save."""
        self.config[key] = value
        self.save_config()

    def set_runtime(self, key: str, value: Any):
        """Set a configuration value without saving (runtime only)."""
        self.config[key] = value

    def ensure_config(self):
        """Ensure essential configuration exists, prompt user if not."""
        try:
            changed = False
            # Check if session file exists, if so, skip login config
            if Path("session.pyncm").exists():
                pass
            
            if not self.get("output_dir"):
                self.config["output_dir"] = "downloads"
                changed = True
            
            if not self.get("preferred_format"):
                self.config["preferred_format"] = "auto"
                changed = True
                
            if changed:
                self.save_config()
        except CancelledError:
            logger.warning("Configuration cancelled.")
        except Exception as e:
            logger.error(f"Configuration error: {e}")

config_manager = ConfigManager()
