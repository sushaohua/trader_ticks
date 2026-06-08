import json
import os
import logging

logger = logging.getLogger(__name__)

class AnalyzerConfigManager:
    def __init__(self, config_path="configs/analyzer_params.json"):
        self.config_path = os.path.abspath(config_path)
        self.configs = self._load_configs()

    def _load_configs(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading config {self.config_path}: {e}")
                return {}
        return {}

    def save_configs(self):
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.configs, f, indent=4)
        except Exception as e:
            logger.error(f"Error saving config {self.config_path}: {e}")

    def get_stock_config(self, code):
        """Get the configuration for a specific stock, or return defaults."""
        default_config = {
            "vpin": {
                "volume_bucket_size": 10000,
                "window_size": 50
            },
            "iceberg": {
                "time_interval_ms": 100,
                "volume_cluster_threshold": 3
            },
            "flow_speed": {
                "rolling_window_seconds": 60,
                "speed_surge_threshold": 100
            }
        }
        return self.configs.get(code, default_config)

    def update_stock_config(self, code, model, param_name, value):
        """Update a specific parameter and save."""
        if code not in self.configs:
            self.configs[code] = self.get_stock_config(code)
            
        if model not in self.configs[code]:
            self.configs[code][model] = {}
            
        self.configs[code][model][param_name] = value
        self.save_configs()
