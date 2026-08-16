"""Download ruff and ty configuration files from GitHub."""

import asyncio
import logging
from typing import TYPE_CHECKING

from httpx import AsyncClient, HTTPStatusError

from ruff_analytics.scrapper.github_api import download_blob

if TYPE_CHECKING:
    from ruff_analytics.scrapper.db import Config, ScrapperRepository


logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 5


async def run_download(
    repository: ScrapperRepository, trigger_download_event: asyncio.Event, discovery_done_event: asyncio.Event
) -> None:
    """Start or resume downloading the discovered configuration files that are missing or outdated.

    Keeps polling for newly discovered configs (discovery runs concurrently and may add work at any time),
    stopping only once `discovery_done` is set and no configs are left to download.
    """
    async with AsyncClient() as client:
        while True:
            if not trigger_download_event.is_set():
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
                continue

            trigger_download_event.clear()

            pending = repository.get_discovered_configs_to_download()
            for config in pending:
                await _download_config(client, repository, config)

            if discovery_done_event.is_set():
                logger.info("Downloading files is done")
                return


async def _download_config(client: AsyncClient, repository: ScrapperRepository, config: Config) -> None:
    try:
        result = await download_blob(client, config.repo_id, config.blob_sha)
    except HTTPStatusError:
        logger.exception("Failed to download %s/%s/%s", config.repo.owner, config.repo.name, config.config_path)
        return

    repository.save_config_content(
        repo_id=config.repo_id,
        config_path=config.config_path,
        blob_sha=config.blob_sha,
        content=result.get_content(),
        downloaded_at=result.downloaded_at,
    )
    logger.info("Downloaded %s/%s/%s", config.repo.owner, config.repo.name, config.config_path)
