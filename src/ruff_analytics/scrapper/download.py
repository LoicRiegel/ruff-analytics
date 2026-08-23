"""Download ruff and ty configuration files from GitHub."""

import asyncio
import logging
from asyncio import Event, Semaphore
from datetime import UTC, datetime
from http import HTTPStatus
from typing import TYPE_CHECKING

from httpx import AsyncClient, HTTPStatusError, RequestError

from ruff_analytics.scrapper.github_api import download_blob

if TYPE_CHECKING:
    from ruff_analytics.scrapper.db import Config, ScrapperRepository


logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 5

PERMANENT_FAILURE_STATUSES = {HTTPStatus.NOT_FOUND, HTTPStatus.GONE}
MAX_CONCURRENT_DOWNLOADS = 20


async def run_download(repository: ScrapperRepository, discovery_done_event: Event) -> None:
    """Start or resume downloading the discovered configuration files that are missing or outdated.

    Keeps polling for newly discovered configs (discovery runs concurrently and may add work at any time),
    stopping only once `discovery_done` is set and no configs are left to download.
    """
    semaphore = Semaphore(MAX_CONCURRENT_DOWNLOADS)

    async def _download_config_limited(client: AsyncClient, config: Config) -> None:
        async with semaphore:
            await _download_config(client, repository, config)

    async with AsyncClient() as client:
        while True:
            pending = repository.get_discovered_configs_to_download()
            if not pending:
                if discovery_done_event.is_set():
                    logger.info("No more configs to download")
                    return
                logger.debug(
                    "No configs to download (waiting for discover), sleeping for %d seconds", POLL_INTERVAL_SECONDS
                )
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
                continue

            logger.info("Start downloading %d configs", len(pending))
            async with asyncio.TaskGroup() as tg:
                for config in pending:
                    tg.create_task(_download_config_limited(client, config))


async def _download_config(client: AsyncClient, repository: ScrapperRepository, config: Config) -> None:
    if repository.is_config_content_downloaded(config.blob_sha):
        repository.save_config_content_from_existing_blob(
            repo_id=config.repo_id,
            config_path=config.config_path,
            blob_sha=config.blob_sha,
            downloaded_at=datetime.now(tz=UTC),
        )
        logger.info("Reused cached blob for %s/%s/%s", config.repo.owner, config.repo.name, config.config_path)
        return

    logger.debug("Downloading %s/%s/%s", config.repo.owner, config.repo.name, config.config_path)
    try:
        result = await download_blob(client, config.repo_id, config.blob_sha)
    except RequestError:
        logger.warning(
            "Transient network error while downloading %s/%s/%s; will retry later",
            config.repo.owner,
            config.repo.name,
            config.config_path,
            exc_info=True,
        )
        return
    except HTTPStatusError as error:
        logger.exception("Failed to download %s/%s/%s", config.repo.owner, config.repo.name, config.config_path)
        if error.response.status_code in PERMANENT_FAILURE_STATUSES:
            logger.info(
                "Saved %s/%s/%s as permanent download failures", config.repo.owner, config.repo.name, config.config_path
            )
            repository.save_download_failure(
                repo_id=config.repo_id,
                config_path=config.config_path,
                blob_sha=config.blob_sha,
                status_code=error.response.status_code,
                failed_at=datetime.now(tz=UTC),
            )
        return

    repository.save_config_content(
        repo_id=config.repo_id,
        config_path=config.config_path,
        blob_sha=config.blob_sha,
        content=result.get_content(),
        downloaded_at=result.downloaded_at,
    )
    logger.info("Saved %s/%s/%s", config.repo.owner, config.repo.name, config.config_path)
