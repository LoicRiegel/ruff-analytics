"""Search for ruff configuration files in GitHub public repositories. Store the result in the 'configs' database."""

import os
import sqlite3
import time
import json
import httpx
from pathlib import Path
from dataclasses import dataclass
from dotenv import load_dotenv
from pprint import pprint, pformat

load_dotenv()

CONFIG_DB = Path(__file__).resolve().parent / "configs.db"
TEMP_JSON = Path(__file__).resolve().parent / "temp.json"
TEMP2_JSON = Path(__file__).resolve().parent / "temp2.json"
TEMP_JSON.touch(exist_ok=True)
TEMP2_JSON.touch(exist_ok=True)

SEARCH_QUERIES = (
    "[tool.ruff] in:file filename:pyproject.toml extension:toml",
    "filename:ruff.toml extension:toml",
    "filename:.ruff.toml extension:toml",
)

GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]


@dataclass(frozen=True)
class DiscoveredConfig:
    """A discovered ruff configuration."""

    repo_link: str
    path: str
    branch: str
    commit: str


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS configs (
            repo_owner      TEXT NOT NULL,
            repo_name       TEXT NOT NULL,
            branch          TEXT,
            commit_sha      TEXT,
            config_path     TEXT NOT NULL,
            config_type     TEXT NOT NULL,  -- 'pyproject.toml' | 'ruff.toml' | '.ruff.toml'
            discovered_at   INTEGER NOT NULL, -- epoch seconds
            PRIMARY KEY (repo_owner, repo_name, config_path)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_configs_type ON configs (config_type)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_configs_discovered_at ON configs (discovered_at)"
    )


def make_request() -> None:
    url = "https://api.github.com/search/code"
    params = {
        "q": SEARCH_QUERIES[1],
        "per_page": 100,
        "page": 1,
    }
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }
    resp = httpx.get(url, params=params, headers=headers)
    print("Status code", resp.status_code)
    print("x-ratelimit-limit", resp.headers.get("x-ratelimit-limit"))
    print("x-ratelimit-remaining", resp.headers.get("x-ratelimit-remaining"))
    print("x-ratelimit-reset", resp.headers.get("x-ratelimit-reset"))
    print("x-ratelimit-used", resp.headers.get("x-ratelimit-used"))
    if resp.status_code == 200:
        print("Total count", resp.json()["total_count"])
        print("Nb items: ", len(resp.json()["items"]))
        TEMP2_JSON.write_text(json.dumps(resp.json()))


def main() -> None:
    with sqlite3.connect(CONFIG_DB) as conn:
        print("Init DB")
        init_db(conn)
        print("DB initialized")

    make_request()


if __name__ == "__main__":
    main()
