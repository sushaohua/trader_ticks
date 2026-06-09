import os
import json

def get_config_path():
    """
    Get the configuration file path.
    Resolves using the following priority:
    1. Environment variable FUTU_SETTINGS_PATH (if set)
    2. Local override file configs/futu_settings.local.json (if exists)
    3. Default configs/futu_settings.json
    """
    env_path = os.environ.get("FUTU_SETTINGS_PATH")
    if env_path:
        return os.path.abspath(env_path)
    
    # PROJECT_ROOT is two levels up from core/config.py
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    local_path = os.path.join(project_root, "configs", "futu_settings.local.json")
    if os.path.exists(local_path):
        return local_path
        
    return os.path.join(project_root, "configs", "futu_settings.json")

def load_config():
    """
    Load and parse the JSON configuration.
    """
    path = get_config_path()
    if not os.path.exists(path):
        raise FileNotFoundError(f"Configuration file not found at: {path}")
        
    with open(path, 'r', encoding='utf-8') as f:
        config = json.load(f)
        
    if "storage" not in config:
        config["storage"] = {}
    if "engine" not in config["storage"]:
        config["storage"]["engine"] = "clickhouse"
        
    return config

