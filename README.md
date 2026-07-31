# ruff-analytics

Analytics on [ruff](https://docs.astral.sh/ruff/) usage.

## Setup

- Clone the project
- Make sure [uv](https://docs.astral.sh/uv/) is installed
- Create a `.env` file with the required environment variables:
  ```sh
  GITHUB_TOKEN=
  RUFF_ANALYTICS_DB=
  ```

## Run the scraper

The package exposes a CLI named `scrapper`.

1. Initialize the database and create initial scan windows:
   ```sh
   uv run scrapper init
   ```

2. Start (or resume) scraping:
   ```sh
   uv run scrapper start
   ```

The scraper searches public repositories for ruff configuration files (`ruff.toml`, `.ruff.toml`, and `pyproject.toml` containing `[tool.ruff]`) and stores metadata in the configured database.
