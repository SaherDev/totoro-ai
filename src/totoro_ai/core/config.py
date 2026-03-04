from pathlib import Path

import yaml


def find_project_root() -> Path:
    """Walk up from this file until we find pyproject.toml."""
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / "pyproject.toml").exists():
            return current
        current = current.parent
    raise FileNotFoundError(
        "Could not find project root (no pyproject.toml found)"
    )


def load_yaml_config(name: str) -> dict[str, str]:
    """Load a YAML file from the config/ directory."""
    config_path = find_project_root() / "config" / name
    try:
        with config_path.open() as f:
            config: dict[str, str] = yaml.safe_load(f)
    except FileNotFoundError as err:
        raise FileNotFoundError(
            f"Config not found at {config_path}. "
            "Check your working directory."
        ) from err
    except yaml.YAMLError as err:
        raise ValueError(
            f"Invalid YAML in {config_path}: {err}"
        ) from err
    return config
