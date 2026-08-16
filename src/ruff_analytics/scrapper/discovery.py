"""Discover ruff and ty configuration files from GitHub."""

import logging
from typing import TYPE_CHECKING

from httpx import AsyncClient, HTTPStatusError

from ruff_analytics.scrapper.db import (
    ScanWindow,
    create_window,
    mark_window_as_done,
    mark_window_as_error,
    next_window_to_process,
    save_config,
    save_repo,
    split_window,
)
from ruff_analytics.scrapper.github_api import RESULTS_PER_PAGE, discover_configs
from ruff_analytics.scrapper.size_range import SizeRange, split_size_range

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.orm import Session

    from ruff_analytics.scrapper.config_type import ConfigType
    from ruff_analytics.scrapper.models import DiscoveredConfigResult

logger = logging.getLogger(__name__)

MAX_RESULTS_PER_RESPONSE = 1000


async def init_discovery(session: Session) -> None:
    """Probe GitHub once per query type and insert initial windows. Call only once."""
    upper_size_range = SizeRange(20_001, 1_000_000)
    main_size_range = SizeRange(0, 20_000)
    for size_range in (upper_size_range, main_size_range):
        create_window(session, "PYPROJECT_TOML_WITH_RUFF", size_range)
        create_window(session, "PYPROJECT_TOML_WITH_TY", size_range)
        create_window(session, "RUFF_TOML", size_range)
        create_window(session, "TY_TOML", size_range)
    session.commit()


async def run_discovery(session: Session) -> None:
    """Start or resume discovery — processes all pending windows until none remain."""
    async with AsyncClient() as client:
        while window := next_window_to_process(session):
            await _process_window(client, session, window)
            session.commit()


def _save_configs(
    session: Session, configs: list[DiscoveredConfigResult], config_type: ConfigType, discovered_at: datetime
) -> None:
    for config in configs:
        save_repo(
            session,
            repo_id=config.repository.id,
            repo_owner=config.repository.owner.login,
            repo_name=config.repository.name,
        )
        save_config(
            session,
            repo_id=config.repository.id,
            config_type=config_type,
            config_path=config.path,
            blob_sha=config.blob_sha,
            commit_sha=config.get_commit_sha(),
            discovered_at=discovered_at,
        )


async def _process_window(client: AsyncClient, session: Session, window: ScanWindow) -> None:
    logger.debug("Processing window %s - %s: %s", str(window.size_from), str(window.size_to), window.window_status)
    size_range = SizeRange(window.size_from, window.size_to)
    try:
        result = await discover_configs(client, window.config_type, size_range, page=1)
    except HTTPStatusError as e:
        logger.exception(
            "Discovery: processed window %d - %d as error (HTTP response was %d)",
            window.size_from,
            window.size_to,
            e.response.status_code,
        )
        mark_window_as_error(session, window.id)
        return
    if result.total_count > MAX_RESULTS_PER_RESPONSE:
        try:
            size_range_split = split_size_range(size_range)
        except ValueError:
            logger.error(  # noqa: TRY400
                "Discovery: window %d - %d should be split but the window cannot be split (total count %d)",
                window.size_from,
                window.size_to,
                result.total_count,
            )
            mark_window_as_error(session, window.id)
        else:
            logger.info(
                "Discovery: window %d - %d needs to be split (total count %d)",
                window.size_from,
                window.size_to,
                result.total_count,
            )
            split_window(session, window.id, size_range_split)
        return
    logger.debug(
        "Discovery: window %d - %d is ready (total count %d)", window.size_from, window.size_to, result.total_count
    )
    _save_configs(session, result.items, window.config_type, result.discovered_at)
    num_pages = (result.total_count + RESULTS_PER_PAGE - 1) // RESULTS_PER_PAGE
    for page in range(2, num_pages + 1):
        try:
            result = await discover_configs(client, window.config_type, size_range, page=page)
        except HTTPStatusError as e:
            logger.exception(
                "Discovery: error when discovering configurations from window %d - %d (HTTP response was %d)",
                window.size_from,
                window.size_to,
                e.response.status_code,
            )
            mark_window_as_error(session, window.id)
            return
        _save_configs(session, result.items, window.config_type, result.discovered_at)
    logger.info(
        "Discovery: saved configurations for window %d - %d (total count %d)",
        window.size_from,
        window.size_to,
        result.total_count,
    )
    mark_window_as_done(session, window.id, result.total_count)
