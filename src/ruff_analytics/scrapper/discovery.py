"""Discover ruff and ty configuration files from GitHub."""

import logging
from typing import TYPE_CHECKING

from httpx import AsyncClient, HTTPStatusError, RequestError

from ruff_analytics.scrapper.github_api import RESULTS_PER_PAGE, discover_configs
from ruff_analytics.scrapper.size_range import SizeRange, split_size_range

if TYPE_CHECKING:
    import asyncio
    from datetime import datetime

    from ruff_analytics.scrapper.config_type import ConfigType
    from ruff_analytics.scrapper.db import ScanWindow, ScrapperRepository
    from ruff_analytics.scrapper.models import DiscoveredConfigResult

logger = logging.getLogger(__name__)

MAX_RESULTS_PER_RESPONSE = 1000


async def init_discovery(repository: ScrapperRepository) -> None:
    """Probe GitHub once per query type and insert initial windows. Call only once."""
    upper_size_range = SizeRange(20_001, 1_000_000)
    main_size_range = SizeRange(0, 20_000)
    for size_range in (upper_size_range, main_size_range):
        repository.create_discovery_window("PYPROJECT_TOML_WITH_RUFF", size_range)
        repository.create_discovery_window("PYPROJECT_TOML_WITH_TY", size_range)
        repository.create_discovery_window("RUFF_TOML", size_range)
        repository.create_discovery_window("TY_TOML", size_range)


async def run_discovery(repository: ScrapperRepository, discovery_done_event: asyncio.Event) -> None:
    """Start or resume discovery — processes all pending windows until none remain."""
    async with AsyncClient() as client:
        while window := repository.next_discovery_window_to_process():
            await _process_window(client, repository, window)
    discovery_done_event.set()
    logger.info("Discovery is done")


def _save_configs(
    repository: ScrapperRepository,
    configs: list[DiscoveredConfigResult],
    config_type: ConfigType,
    discovered_at: datetime,
    query: str,
) -> None:
    for config in configs:
        if config.repository.fork:
            logger.debug(
                "Skipping repository %s/%s because it is a fork", config.repository.owner, config.repository.name
            )
            continue
        repository.save_repo(
            repo_id=config.repository.id, repo_owner=config.repository.owner.login, repo_name=config.repository.name
        )
        repository.save_config(
            repo_id=config.repository.id,
            config_type=config_type,
            config_path=config.path,
            blob_sha=config.blob_sha,
            commit_sha=config.get_commit_sha(),
            discovered_at=discovered_at,
            query=query,
        )


async def _process_window(client: AsyncClient, repository: ScrapperRepository, window: ScanWindow) -> None:
    logger.debug("Processing window %s - %s: %s", str(window.size_from), str(window.size_to), window.window_status)
    size_range = SizeRange(window.size_from, window.size_to)
    try:
        query, result = await discover_configs(client, window.config_type, size_range, page=1)
    except RequestError:
        logger.warning(
            "Discovery: transient network error when processing window %d - %d; will retry later",
            window.size_from,
            window.size_to,
            exc_info=True,
        )
        return
    except HTTPStatusError as e:
        logger.exception(
            "Discovery: processed window %d - %d as error (HTTP response was %d)",
            window.size_from,
            window.size_to,
            e.response.status_code,
        )
        repository.mark_discovery_window_as_error(window.id)
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
            repository.mark_discovery_window_as_error(window.id)
        else:
            logger.info(
                "Discovery: window %d - %d needs to be split (total count %d)",
                window.size_from,
                window.size_to,
                result.total_count,
            )
            repository.split_discovery_window(window.id, size_range_split)
        return
    logger.debug(
        "Discovery: window %d - %d is ready (total count %d)", window.size_from, window.size_to, result.total_count
    )
    _save_configs(repository, result.items, window.config_type, result.discovered_at, query)
    num_pages = (result.total_count + RESULTS_PER_PAGE - 1) // RESULTS_PER_PAGE
    for page in range(2, num_pages + 1):
        logger.debug(
            "Discovery: fetching page %d/%d for window %d - %d", page, num_pages, window.size_from, window.size_to
        )
        try:
            query, result = await discover_configs(client, window.config_type, size_range, page=page)
        except RequestError:
            logger.warning(
                "Discovery: transient network error when fetching page %d/%d for window %d - %d; will retry later",
                page,
                num_pages,
                window.size_from,
                window.size_to,
                exc_info=True,
            )
            return
        except HTTPStatusError as e:
            logger.exception(
                "Discovery: error when discovering configurations from window %d - %d (HTTP response was %d)",
                window.size_from,
                window.size_to,
                e.response.status_code,
            )
            repository.mark_discovery_window_as_error(window.id)
            return
        _save_configs(repository, result.items, window.config_type, result.discovered_at, query)
    logger.info(
        "Discovery: saved configurations for window %d - %d (total count %d)",
        window.size_from,
        window.size_to,
        result.total_count,
    )
    repository.mark_discovery_window_as_done(window.id, result.total_count)
