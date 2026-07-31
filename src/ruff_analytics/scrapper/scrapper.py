"""Core scraping logic for collecting ruff configuration files from GitHub."""

import logging
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

from httpx import AsyncClient

from ruff_analytics.scrapper.config_type import parse_config_type
from ruff_analytics.scrapper.date_range import DateRange, split_date_range
from ruff_analytics.scrapper.db import (
    ScanWindow,
    create_window,
    mark_window_as_done,
    mark_window_as_error,
    next_window_to_process,
    save_config,
    split_window,
)
from ruff_analytics.scrapper.github_api import RESULTS_PER_PAGE, build_request, send_request

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

START_DATE = date(2022, 1, 1)  # this is the year ruff was released

MAX_RESULTS_PER_RESPONSE = 1000


async def init_scrapper(session: Session) -> None:
    """Probe GitHub once per query type and insert initial windows. Call only once."""
    date_range = DateRange(START_DATE, datetime.now(tz=UTC).date())
    create_window(session, "pyproject.toml", date_range)
    create_window(session, "ruff.toml", date_range)
    create_window(session, ".ruff.toml", date_range)
    session.commit()
    logger.info("Ready to start the scrapping...")


async def run_scraper(session: Session) -> None:
    """Start or resume scraping — processes all pending windows until none remain."""
    logger.info("Resuming the scrapping... (exit with CTRL+C)")
    async with AsyncClient() as client:
        try:
            while window := next_window_to_process(session):
                await _process_window(client, session, window)
                session.commit()
        except KeyboardInterrupt:
            logger.info("Scraping interrupted (can be resumed later)")


def _save_config(session: Session, data: dict[str, Any]) -> None:
    discovered_at = datetime.now(tz=UTC)
    for item in data["items"]:
        config_path = item["path"]
        commit_sha = item["sha"]
        repo = item["repository"]
        repo_owner = repo["owner"]["login"]
        repo_name = repo["name"]
        branch = repo["default_branch"]
        save_config(
            session,
            repo_owner=repo_owner,
            repo_name=repo_name,
            config_type=parse_config_type(config_path),
            config_path=config_path,
            branch=branch,
            commit_sha=commit_sha,
            discovered_at=discovered_at,
        )


async def _process_window(client: AsyncClient, session: Session, window: ScanWindow) -> None:
    logger.debug("Processing window %s - %s: %s", str(window.date_from), str(window.date_to), window.window_status)
    date_range = DateRange(window.date_from, window.date_to)
    request = build_request(client, window.config_type, date_range, page=1)
    response = await send_request(client, request)
    if not response.is_success:
        logger.error(
            "Processed window %s - %s: error (HTTP response was %s)",
            str(window.date_from),
            str(window.date_to),
            str(response.status_code),
        )
        mark_window_as_error(session, window.id)
        return
    data = response.json()
    total_count: int = data["total_count"]
    if total_count > MAX_RESULTS_PER_RESPONSE:
        try:
            date_range_split = split_date_range(date_range)
        except ValueError:
            logger.error(  # noqa: TRY400
                "Processed window %s - %s: error should be split but the window cannot be split (total count %s)",
                str(window.date_from),
                str(window.date_to),
                str(total_count),
            )
            mark_window_as_error(session, window.id)
        else:
            logger.info(
                "Processed window %s - %s: needs split (total count %s)",
                str(window.date_from),
                str(window.date_to),
                str(total_count),
            )
            split_window(session, window.id, date_range_split)
        return
    logger.info(
        "Processed window %s - %s: ready (total count %s)", str(window.date_from), str(window.date_to), str(total_count)
    )
    _save_config(session, data)
    num_pages = (total_count + RESULTS_PER_PAGE - 1) // RESULTS_PER_PAGE
    for page in range(2, num_pages + 1):
        request = build_request(client, window.config_type, date_range, page=page)
        response = await send_request(client, request)
        data = response.json()
        _save_config(session, data)
    logger.info(
        "Processed window %s - %s: done (total count %s)", str(window.date_from), str(window.date_to), str(total_count)
    )
    mark_window_as_done(session, window.id, total_count)
