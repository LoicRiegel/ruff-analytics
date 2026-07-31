import asyncio
import os
import time
from typing import TYPE_CHECKING, assert_never

if TYPE_CHECKING:
    from httpx import AsyncClient, Request, Response

    from ruff_analytics.scrapper.config_type import ConfigType
    from ruff_analytics.scrapper.date_range import DateRange


GITHUB_SEARCH_URL = "https://api.github.com/search/code"
RESULTS_PER_PAGE = 100


def build_request(client: AsyncClient, config_type: ConfigType, date_range: DateRange, page: int) -> Request:
    query = _build_query(config_type, date_range)
    return client.build_request(
        "GET", GITHUB_SEARCH_URL, params={"q": query, "per_page": RESULTS_PER_PAGE, "page": page}, headers=_headers()
    )


async def send_request(client: AsyncClient, request: Request) -> Response:
    """Send a request and return the response.

    Retry when rate limitations are hit.
    """
    resp = await client.send(request)
    if resp.is_client_error:
        reset = resp.headers.get("x-ratelimit-reset")
        wait = max(int(reset) - time.time(), 1) if reset else 60
        await asyncio.sleep(wait)
        resp = await client.send(request)
    return resp


def _build_query(config_type: ConfigType, date_range: DateRange) -> str:
    match config_type:
        case "ruff.toml":
            return _build_ruff_query(date_range)
        case ".ruff.toml":
            return _build_dot_ruff_query(date_range)
        case "pyproject.toml":
            return _build_pyproject_query(date_range)
        case _:
            assert_never()


def _build_ruff_query(date_range: DateRange) -> str:
    return f"filename:ruff.toml created:{date_range.date_from}..{date_range.date_to}"


def _build_dot_ruff_query(date_range: DateRange) -> str:
    return f"filename:.ruff.toml created:{date_range.date_from}..{date_range.date_to}"


def _build_pyproject_query(date_range: DateRange) -> str:
    return (
        "[tool.ruff] in:file filename:pyproject.toml extension:toml "
        f"created:{date_range.date_from}..{date_range.date_to}"
    )


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}", "Accept": "application/vnd.github+json"}
