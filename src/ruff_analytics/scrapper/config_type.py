"""The different configuration to scrap."""

from typing import Literal

type ConfigType = Literal["PYPROJECT_TOML_WITH_RUFF", "PYPROJECT_TOML_WITH_TY", "RUFF_TOML", "TY_TOML"]
