"""Make requests to the GitHub API and the show the results."""

import os
from http import HTTPStatus

import httpx
from dotenv import load_dotenv

# tool.ruff in:file filename:pyproject.toml path:/ size>20_000      => total_count=666
# tool.ty in:file filename:pyproject.toml path:/ size>20_000        => total_count=147
# filename:ruff.toml path:/ size>20_000                             => total_count=11
# filename:ty.toml path:/ size>20_000                               => total_count=17


def make_request(github_token: str) -> None:
    url = "https://api.github.com/search/code"
    query = "filename:ty.toml extension:toml path:/ size:>20000"
    params = {"q": query, "per_page": 100, "page": 1}
    headers = {"Authorization": f"Bearer {github_token}", "Accept": "application/vnd.github+json"}
    resp = httpx.get(url, params=params, headers=headers)
    print(f'Query "{query}"')
    print("Status code", resp.status_code)
    print("x-ratelimit-limit", resp.headers.get("x-ratelimit-limit"))
    print("x-ratelimit-remaining", resp.headers.get("x-ratelimit-remaining"))
    print("x-ratelimit-reset", resp.headers.get("x-ratelimit-reset"))
    print("x-ratelimit-used", resp.headers.get("x-ratelimit-used"))
    if HTTPStatus(resp.status_code).is_success:
        print("Total count", resp.json()["total_count"])
        print("Nb items: ", len(resp.json()["items"]))
        print("JSON:")
        for item in resp.json()["items"][:3]:
            print(item["path"])


def main() -> None:
    load_dotenv()
    github_token = os.environ["GITHUB_TOKEN"]
    make_request(github_token)


if __name__ == "__main__":
    main()
