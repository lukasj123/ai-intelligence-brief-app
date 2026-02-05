import yaml
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = BASE_DIR / "config" / "config.yaml"

FREQUENCY_TO_DAYS = {
    "daily": 1,
    "weekly": 7,
    "biweekly": 14,
    "monthly": 30
}

_cached_config = None


def load_config():
    """
    Load centralized configuration from config/config.yaml.
    Returns the entire config dict.
    """
    global _cached_config

    if _cached_config is not None:
        return _cached_config

    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            config = yaml.safe_load(f)
    else:
        config = {
            "analyzer_instructions": "Focus on concrete technical developments, product releases, and policy changes.",
            "reviewer_focus": "Prioritize highly relevant AI developments.",
            "max_key_points": 10,
            "frequency": "weekly",
            "lookback_days": 7,
            "skip_normalization": False,
            "email": {
                "enabled": False,
                "recipient_email": "",
                "send_day": "Monday",
                "send_time": "09:00"
            }
        }

    if config.get("lookback_days"):
        config["_calculated_lookback_days"] = config["lookback_days"]
    else:
        frequency = config.get("frequency", "weekly")
        config["_calculated_lookback_days"] = FREQUENCY_TO_DAYS.get(frequency, 7)

    _cached_config = config
    return config


def save_config(config):
    """Save configuration to config/config.yaml."""
    global _cached_config
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, 'w') as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)
    _cached_config = config


def reload_config():
    """Force reload config from disk (clears cache)."""
    global _cached_config
    _cached_config = None
    return load_config()


def get_lookback_days():
    """Get the lookback period in days."""
    config = load_config()
    return config.get("_calculated_lookback_days", 7)


def get_analyzer_instructions():
    """Get analyzer instructions."""
    config = load_config()
    return config.get("analyzer_instructions", "")


def get_reviewer_focus():
    """Get reviewer focus instructions."""
    config = load_config()
    return config.get("reviewer_focus", "")


def get_max_key_points():
    """Get maximum number of key points."""
    config = load_config()
    return config.get("max_key_points", 10)


def get_skip_normalization():
    """Get skip normalization flag."""
    config = load_config()
    return config.get("skip_normalization", False)


# Legacy compatibility functions
def load_briefing_config():
    """Legacy function for backwards compatibility."""
    config = load_config()
    email_config = config.get("email", {})
    return {
        "frequency": config.get("frequency", "weekly"),
        "lookback_days": config.get("_calculated_lookback_days", 7),
        "recipient_email": email_config.get("recipient_email", ""),
        "enabled": email_config.get("enabled", False),
        "send_day": email_config.get("send_day", "Monday"),
        "send_time": email_config.get("send_time", "09:00")
    }
