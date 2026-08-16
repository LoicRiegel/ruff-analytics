"""Pydantic models mapping the GitHub API responses used by the scrapper."""

import base64
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

from pydantic import BaseModel, Field


class _Owner(BaseModel):
    login: str


class _Repository(BaseModel):
    id: int
    name: str
    owner: _Owner
    fork: bool


class DiscoveredConfigResult(BaseModel):
    """A single configuration file found via the code search API."""

    path: str
    blob_sha: str = Field(alias="sha")
    url: str
    repository: _Repository

    def get_commit_sha(self) -> str:
        """Parse and return the commit sha this file was found at."""
        return parse_qs(urlparse(self.url).query)["ref"][0]


class DiscoveryResult(BaseModel):
    """Result of discovering configuration files for a single page of search results."""

    items: list[DiscoveredConfigResult]
    total_count: int
    discovered_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))


class DownloadResult(BaseModel):
    """Result of downloading a git blob."""

    raw_content: str = Field(alias="content")
    downloaded_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))

    def get_content(self) -> str:
        """Decode and return the blob's content as text."""
        return base64.b64decode(self.raw_content).decode()
