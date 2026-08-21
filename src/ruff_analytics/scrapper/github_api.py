import asyncio
import logging
import os
import time
from http import HTTPStatus
from typing import TYPE_CHECKING, assert_never

from httpx import RequestError

from ruff_analytics.scrapper.models import DiscoveryResult, DownloadResult

if TYPE_CHECKING:
    from httpx import AsyncClient, Request, Response

    from ruff_analytics.scrapper.config_type import ConfigType
    from ruff_analytics.scrapper.size_range import SizeRange

logger = logging.getLogger(__name__)

GITHUB_SEARCH_URL = "https://api.github.com/search/code"
RESULTS_PER_PAGE = 100


async def discover_configs(
    client: AsyncClient, config_type: ConfigType, size_range: SizeRange, page: int
) -> tuple[str, DiscoveryResult]:
    """Discover the files of the provided config type, within the provided size range and in the given page.

    Retry when rate limitations are hit.

    """
    query = _build_query(config_type, size_range)
    request = client.build_request(
        "GET", GITHUB_SEARCH_URL, params={"q": query, "per_page": RESULTS_PER_PAGE, "page": page}, headers=_headers()
    )
    response = await _send_request(client, request)
    response.raise_for_status()
    return query, DiscoveryResult.model_validate(response.json())


async def download_blob(client: AsyncClient, repo_id: int, blob_sha: str) -> DownloadResult:
    """Download a git blob's content and return it decoded as text.

    :raises HTTPStatusError: if the request fails.
    """
    url = f"https://api.github.com/repositories/{repo_id}/git/blobs/{blob_sha}"
    request = client.build_request("GET", url, headers=_headers())
    response = await _send_request(client, request)
    response.raise_for_status()
    return DownloadResult.model_validate(response.json())


MAX_RETRIES = 5
RETRY_WAIT_NETWORK_ERROR = 5
RETRY_WAIT_ON_RATE_LIMITING = 60


async def _send_request(client: AsyncClient, request: Request) -> Response:
    """Send a request and return the response.

    Retry when rate limitations (primary or secondary) are hit.
    """
    retries = 0
    while True:
        try:
            response = await client.send(request)
        except RequestError:
            if retries >= MAX_RETRIES:
                raise
            retries += 1
            wait = min(RETRY_WAIT_NETWORK_ERROR * retries, RETRY_WAIT_ON_RATE_LIMITING)
            logger.warning(
                "Request transport error for %s, retrying in %.0fs (%d/%d)",
                request.url,
                wait,
                retries,
                MAX_RETRIES,
                exc_info=True,
            )
            await asyncio.sleep(wait)
            continue

        if _check_response(response) or retries >= MAX_RETRIES:
            return response

        wait = _get_retry_wait(response)
        logger.debug("Waiting %.0fs before retrying %s", wait, request.url)
        await asyncio.sleep(wait)
        retries += 1


def _check_response(response: Response) -> bool:
    if response.status_code == HTTPStatus.FORBIDDEN:
        logger.error("Response error 403 (Forbidden) for %s", response.url)
        return False
    if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
        logger.error("Response error 429 (Too many requests) for %s", response.url)
        return False
    return True


def _get_retry_wait(resp: Response, default: float = RETRY_WAIT_ON_RATE_LIMITING) -> float:
    retry_after: float | None = resp.headers.get("retry-after")
    if retry_after is not None:
        return max(float(retry_after), 1)
    reset: str | None = resp.headers.get("x-ratelimit-reset")
    if reset:
        return int(reset) - time.time() + 1
    return default


def _build_query(config_type: ConfigType, size_range: SizeRange) -> str:
    match config_type:
        case "RUFF_TOML":
            return _build_ruff_query(size_range)
        case "TY_TOML":
            return _build_ty_query(size_range)
        case "PYPROJECT_TOML_WITH_RUFF":
            return _build_pyproject_with_ruff_query(size_range)
        case "PYPROJECT_TOML_WITH_TY":
            return _build_pyproject_with_ty_query(size_range)
        case _:
            assert_never()


def _build_ruff_query(size_range: SizeRange) -> str:
    return f"filename:ruff.toml path:/ size:{size_range.size_from}..{size_range.size_to}"


def _build_ty_query(size_range: SizeRange) -> str:
    return f"filename:ty.toml path:/ size:{size_range.size_from}..{size_range.size_to}"


def _build_pyproject_with_ruff_query(size_range: SizeRange) -> str:
    return (
        '"tool.ruff" in:file filename:pyproject.toml extension:toml path:/ '
        f"size:{size_range.size_from}..{size_range.size_to}"
    )


def _build_pyproject_with_ty_query(size_range: SizeRange) -> str:
    return (
        '"tool.ty" in:file filename:pyproject.toml extension:toml path:/ '
        f"size:{size_range.size_from}..{size_range.size_to}"
    )


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}", "Accept": "application/vnd.github+json"}
