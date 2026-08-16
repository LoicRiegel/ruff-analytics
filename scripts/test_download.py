"""Download a file's content from the GitHub API and print it."""

import base64
import os
from http import HTTPStatus

import httpx
from dotenv import load_dotenv


def download_file(github_token: str, repo_id: int, blob_sha: str) -> None:
    headers = {"Authorization": f"Bearer {github_token}", "Accept": "application/vnd.github+json"}
    git_url = f"https://api.github.com/repositories/{repo_id}/git/blobs/{blob_sha}"
    resp = httpx.get(git_url, headers=headers)
    print("Status code", resp.status_code)
    if HTTPStatus(resp.status_code).is_success:
        blob = resp.json()
        content = base64.b64decode(blob["content"])
        print("Content:")
        print(content.decode())


def main() -> None:
    load_dotenv()
    github_token = os.environ["GITHUB_TOKEN"]
    repo_id = 65600975
    blob_sha = "695842c971aeff3513933eeabc14b2bba48976ed"
    download_file(github_token, repo_id, blob_sha)


if __name__ == "__main__":
    main()
