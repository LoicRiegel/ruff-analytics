# ruff-analytics

Analytics on [ruff](https://docs.astral.sh/ruff/) usage.

## Setup

- Clone the project
- Make sure [uv](https://docs.astral.sh/uv/) is installed
- Create a ``.env`` file and write the GitHub token into it:
  ```sh
  GITHUB_TOKEN=...
  ```

## Scan repositories that contain ruff configuration files

The [discovery](./discovery.py) script discovers all public repositories on GitHub that contain a ruff configuration file: either `ruff.toml`, `.ruff.toml`, or `pyproject.toml` with a `[tool.ruff]` section.

The script uses the GitHub search API. To work around the API's 1000-result limit, it splits the search into multiple requests using the repository creation time as a partition key. Results are saved to a SQLite database.

Run it with:
```sh
uv run discovery.py
```
