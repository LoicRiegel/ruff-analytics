from pathlib import Path
from typing import Literal

type ConfigType = Literal[
    "pyproject.toml",  # only those containing a tool.ruff section
    "ruff.toml",
    ".ruff.toml",
]


def parse_config_type(path: str | Path) -> ConfigType:
    """Parse the config type from a file path.

    :raises ValueError: if the file is not a valid ruff configuration file.
    """
    if isinstance(path, str):
        path = Path(path)
    name = path.name
    if name not in ("pyproject.toml", "ruff.toml", ".ruff.toml"):
        msg = f"Unsupported config file: {name!r}"
        raise ValueError(msg)
    return name
