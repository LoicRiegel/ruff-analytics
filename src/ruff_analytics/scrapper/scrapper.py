"""Core scraping logic for collecting ruff configuration files from GitHub."""

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import parse_qs, urlparse

from httpx import AsyncClient

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
from ruff_analytics.scrapper.size_range import SizeRange, split_size_range

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from ruff_analytics.scrapper.config_type import ConfigType

logger = logging.getLogger(__name__)

MAX_RESULTS_PER_RESPONSE = 1000


async def init_scrapper(session: Session) -> None:
    """Probe GitHub once per query type and insert initial windows. Call only once."""
    upper_size_range = SizeRange(20_001, 1_000_000)
    main_size_range = SizeRange(0, 20_000)
    for size_range in (upper_size_range, main_size_range):
        create_window(session, "PYPROJECT_TOML_WITH_RUFF", size_range)
        create_window(session, "PYPROJECT_TOML_WITH_TY", size_range)
        create_window(session, "RUFF_TOML", size_range)
        create_window(session, "TY_TOML", size_range)
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


def _save_config(session: Session, data: dict[str, Any], config_type: ConfigType) -> None:
    discovered_at = datetime.now(tz=UTC)
    for item in data["items"]:
        config_path = cast("str", item["path"])
        blob_sha = cast("str", item["sha"])
        commit_sha = cast("str", parse_qs(urlparse(item["url"]).query)["ref"][0])
        repo = cast("dict[str, Any]", item["repository"])
        repo_id = cast("int", repo["id"])
        repo_owner = cast("str", repo["owner"]["login"])
        repo_name = cast("str", repo["name"])
        save_config(
            session,
            repo_id=repo_id,
            repo_owner=repo_owner,
            repo_name=repo_name,
            config_type=config_type,
            config_path=config_path,
            blob_sha=blob_sha,
            commit_sha=commit_sha,
            discovered_at=discovered_at,
        )


async def _process_window(client: AsyncClient, session: Session, window: ScanWindow) -> None:
    logger.debug("Processing window %s - %s: %s", str(window.size_from), str(window.size_to), window.window_status)
    size_range = SizeRange(window.size_from, window.size_to)
    request = build_request(client, window.config_type, size_range, page=1)
    response = await send_request(client, request)
    if not response.is_success:
        logger.error(
            "Processed window %d - %d: error (HTTP response was %d)",
            window.size_from,
            window.size_to,
            response.status_code,
        )
        mark_window_as_error(session, window.id)
        return
    data = response.json()
    total_count: int = data["total_count"]
    if total_count > MAX_RESULTS_PER_RESPONSE:
        try:
            size_range_split = split_size_range(size_range)
        except ValueError:
            logger.error(  # noqa: TRY400
                "Processed window %d - %d: error should be split but the window cannot be split (total count %d)",
                window.size_from,
                window.size_to,
                total_count,
            )
            mark_window_as_error(session, window.id)
        else:
            logger.info(
                "Processed window %d - %d: needs split (total count %d)", window.size_from, window.size_to, total_count
            )
            split_window(session, window.id, size_range_split)
        return
    logger.info(
        "Processed window %s - %s: ready (total count %s)", str(window.size_from), str(window.size_to), str(total_count)
    )
    _save_config(session, data, window.config_type)
    num_pages = (total_count + RESULTS_PER_PAGE - 1) // RESULTS_PER_PAGE
    for page in range(2, num_pages + 1):
        request = build_request(client, window.config_type, size_range, page=page)
        response = await send_request(client, request)
        data = response.json()
        _save_config(session, data, window.config_type)
    logger.info(
        "Processed window %s - %s: done (total count %s)", str(window.size_from), str(window.size_to), str(total_count)
    )
    mark_window_as_done(session, window.id, total_count)
