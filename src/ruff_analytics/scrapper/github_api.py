"""Core scraping logic for collecting ruff configuration files from GitHub."""

import os
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, assert_never

from httpx import AsyncClient

from ruff_analytics.scrapper.date_range import DateRange
from ruff_analytics.scrapper.db import Config, ConfigType

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

START_DATE = date(2022, 1, 1)  # this is the year ruff was released
END_DATE = datetime.now(tz=UTC).date()

_GITHUB_SEARCH_URL = "https://api.github.com/search/code"
_MAX_RESULTS = 1000
_RESULTS_PER_PAGE = 100


def make_query(config_type: ConfigType, date_range: DateRange) -> str:
    match config_type:
        case "ruff.toml" | ".ruff.toml":
            return make_ruff_query(date_range)
        case "pyproject.toml":
            return make_pyproject_query(date_range)
        case _:
            assert_never()


def make_ruff_query(date_range: DateRange) -> str:
    return f"filename:ruff.toml OR filename:.ruff.toml created:{date_range.date_from}..{date_range.date_to}"


def make_pyproject_query(date_range: DateRange) -> str:
    return f"[tool.ruff] in:file filename:pyproject.toml extension:toml created:{date_range.date_from}..{date_range.date_to}"


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
        "Accept": "application/vnd.github+json",
    }


async def _fetch_page(client: AsyncClient, query: str, page: int) -> dict:
    resp = await client.get(
        _GITHUB_SEARCH_URL,
        params={"q": query, "per_page": _RESULTS_PER_PAGE, "page": page},
        headers=_headers(),
    )
    resp.raise_for_status()
    return resp.json()


async def _fetch_all_items(
    client: AsyncClient,
    query: str,
    total_count: int,
    first_page_items: list[dict],
) -> list[dict]:
    items = list(first_page_items)
    num_pages = (total_count + _RESULTS_PER_PAGE - 1) // _RESULTS_PER_PAGE
    for page in range(2, num_pages + 1):
        data = await _fetch_page(client, query, page)
        items.extend(data["items"])
    return items


def _save_configs(session: Session, items: list[dict], discovered_at: datetime) -> None:
    for item in items:
        repo = item["repository"]
        session.merge(
            Config(
                repo_owner=repo["owner"]["login"],
                repo_name=repo["name"],
                config_path=item["path"],
                branch=repo["default_branch"],
                commit_sha=item["sha"],
                discovered_at=discovered_at,
            ),
        )
    session.commit()
