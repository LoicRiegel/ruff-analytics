"""Core scraping logic for collecting ruff configuration files from GitHub."""

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, cast

from httpx import AsyncClient

from ruff_analytics.scrapper.date_range import DateRange, split_date_range
from ruff_analytics.scrapper.db import (
    Config,
    ScanWindow,
    create_window,
    mark_window_as_done,
    mark_window_as_error,
    next_pending_window,
    split_window,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

START_DATE = date(2022, 1, 1)  # this is the year ruff was released
END_DATE = datetime.now(tz=UTC).date()

_GITHUB_SEARCH_URL = "https://api.github.com/search/code"
_MAX_RESULTS = 1000
_RESULTS_PER_PAGE = 100


async def init_scrapper(session: Session) -> None:
    """Probe GitHub once per query type and insert initial windows. Call only once."""
    date_range = DateRange(START_DATE, datetime.now(tz=UTC).date())
    create_window(session, "pyproject_toml", date_range)
    create_window(session, "ruff_toml", date_range)
    session.commit()


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
            )
        )
    session.commit()


async def _process_window(client: AsyncClient, session: Session, window: ScanWindow) -> None:
    config_type = window.config_type
    query = _build_query(config_type, window.date_from, window.date_to)

    first_page = await _fetch_page(client, query, page=1)
    total_count: int = first_page["total_count"]

    if total_count > _MAX_RESULTS:
        date_range = DateRange(window.date_from, window.date_to)
        try:
            date_range_split = split_date_range(date_range)
        except ValueError:
            mark_window_as_error(session, window.id)
        else:
            split_window(session, window.id, date_range_split)
        return

    discovered_at = datetime.now(tz=UTC)
    items = await _fetch_all_items(client, query, total_count, first_page["items"])
    _save_configs(session, items, discovered_at)
    mark_window_as_done(session, window.id, total_count)


async def run_scraper(session: Session) -> None:
    """Start or resume scraping — processes all pending windows until none remain."""
    # TODO: handle GitHub rate limiting (10 code-search requests/min for authenticated users)
    async with AsyncClient() as client:
        while window := next_pending_window(session):
            await _process_window(client, session, window)
