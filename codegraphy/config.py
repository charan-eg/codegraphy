import os

# Default configuration
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///codegraphy.db")
CODEGRAPHY_ROOT = os.environ.get("CODEGRAPHY_ROOT", ".")

# Plugin list can be derived from env vars or TOML
_plugins_env = os.environ.get("CODEGRAPHY_PLUGINS", "")
CODEGRAPHY_PLUGINS = [p.strip() for p in _plugins_env.split(",")] if _plugins_env else []

def load_config():
    # Placeholder for loading from codegraphy.toml if needed
    pass
