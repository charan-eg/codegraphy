import os

# Default configuration
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///repolens.db")
REPOLENS_ROOT = os.environ.get("REPOLENS_ROOT", ".")

# Plugin list can be derived from env vars or TOML
_plugins_env = os.environ.get("REPOLENS_PLUGINS", "")
REPOLENS_PLUGINS = [p.strip() for p in _plugins_env.split(",")] if _plugins_env else []

def load_config():
    # Placeholder for loading from repolens.toml if needed
    pass
