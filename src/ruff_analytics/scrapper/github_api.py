import asyncio
import os
import time
from typing import TYPE_CHECKING, assert_never

if TYPE_CHECKING:
    from httpx import AsyncClient, Request, Response

    from ruff_analytics.scrapper.config_type import ConfigType
    from ruff_analytics.scrapper.size_range import SizeRange


GITHUB_SEARCH_URL = "https://api.github.com/search/code"
RESULTS_PER_PAGE = 100


def build_request(client: AsyncClient, config_type: ConfigType, size_range: SizeRange, page: int) -> Request:
    query = _build_query(config_type, size_range)
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
        "tool.ruff in:file filename:pyproject.toml extension:toml path:/ "
        f"size:{size_range.size_from}..{size_range.size_to}"
    )


def _build_pyproject_with_ty_query(size_range: SizeRange) -> str:
    return (
        "tool.ty in:file filename:pyproject.toml extension:toml path:/ "
        f"size:{size_range.size_from}..{size_range.size_to}"
    )


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}", "Accept": "application/vnd.github+json"}
