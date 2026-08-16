from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal, cast

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship

from ruff_analytics.scrapper.config_type import ConfigType  # noqa: TC001 (needed by sqlalchemy)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ruff_analytics.scrapper.size_range import SizeRange, SizeRangeSplit


class Base(DeclarativeBase):
    pass


type WindowStatus = Literal["pending", "done", "needs_split", "split", "error"]


class ScanWindow(Base):
    __tablename__ = "scan_windows"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    config_type: Mapped[ConfigType] = mapped_column(String(20), nullable=False)
    size_from: Mapped[int] = mapped_column(Integer, nullable=False)
    size_to: Mapped[int] = mapped_column(Integer, nullable=False)
    window_status: Mapped[WindowStatus] = mapped_column(String(20), nullable=False)
    result_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Repo(Base):
    __tablename__ = "repos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)


class Config(Base):
    __tablename__ = "configs"
    __table_args__ = (Index("idx_configs_type", "config_type"), Index("idx_configs_discovered_at", "discovered_at"))

    repo_id: Mapped[int] = mapped_column(ForeignKey("repos.id"), primary_key=True)
    config_path: Mapped[str] = mapped_column(String, primary_key=True)
    config_type: Mapped[ConfigType] = mapped_column(String(40), nullable=False)
    blob_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    commit_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    repo: Mapped[Repo] = relationship(lazy="joined")


class Content(Base):
    __tablename__ = "contents"

    repo_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    config_path: Mapped[str] = mapped_column(String, primary_key=True)
    blob_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    downloaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ScrapperRepository:
    """Data-access layer for the scrapper, owning the session and its commit boundaries."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create_discovery_window(self, config_type: ConfigType, size_range: SizeRange) -> None:
        """Add a new pending scan window (not committed)."""
        self._session.add(
            ScanWindow(
                config_type=config_type,
                size_from=size_range.size_from,
                size_to=size_range.size_to,
                window_status="pending",
                result_count=None,
                created_at=datetime.now(tz=UTC),
            )
        )
        self._session.commit()

    def next_discovery_window_to_process(self) -> ScanWindow | None:
        """Return the next pending or needs-split window to process, if any."""
        return self._session.query(ScanWindow).filter(ScanWindow.window_status.in_(["pending", "needs_split"])).first()

    def mark_discovery_window_as_done(self, window_id: int, result_count: int) -> None:
        """Mark a window as done with its result count, and commit."""
        window = cast("ScanWindow", self._session.get(ScanWindow, window_id))
        window.window_status = "done"
        window.result_count = result_count
        self._session.commit()

    def mark_discovery_window_as_error(self, window_id: int) -> None:
        """Mark a window as errored, and commit."""
        window = cast("ScanWindow", self._session.get(ScanWindow, window_id))
        window.window_status = "error"
        self._session.commit()

    def split_discovery_window(self, window_id: int, size_range_split: SizeRangeSplit) -> None:
        """Mark a window as split and create its two replacement windows, then commit."""
        window = cast("ScanWindow", self._session.get(ScanWindow, window_id))
        config_type = window.config_type
        window.window_status = "split"
        self.create_discovery_window(config_type, size_range_split.first)
        self.create_discovery_window(config_type, size_range_split.second)
        self._session.commit()

    def save_repo(self, repo_id: int, repo_owner: str, repo_name: str) -> None:
        """Upsert a repository (not committed)."""
        self._session.merge(Repo(id=repo_id, owner=repo_owner, name=repo_name))
        self._session.commit()

    def save_config(
        self,
        repo_id: int,
        config_type: ConfigType,
        config_path: str,
        blob_sha: str,
        commit_sha: str,
        discovered_at: datetime,
    ) -> None:
        """Upsert a discovered config (not committed)."""
        self._session.merge(
            Config(
                repo_id=repo_id,
                config_type=config_type,
                config_path=config_path,
                blob_sha=blob_sha,
                commit_sha=commit_sha,
                discovered_at=discovered_at,
            )
        )
        self._session.commit()

    def save_config_content(
        self, repo_id: int, config_path: str, blob_sha: str, content: str, downloaded_at: datetime
    ) -> None:
        """Upsert a downloaded config's content, and commit."""
        self._session.merge(
            Content(
                repo_id=repo_id,
                config_path=config_path,
                blob_sha=blob_sha,
                content=content,
                downloaded_at=downloaded_at,
            )
        )
        self._session.commit()

    def get_discovered_configs_to_download(self) -> Sequence[Config]:
        """Return the configs that are not downloaded yet, or whose downloaded content is out of date."""
        stmt = (
            select(Config)
            .outerjoin(Content, (Config.repo_id == Content.repo_id) & (Config.config_path == Content.config_path))
            .where((Content.blob_sha.is_(None)) | (Content.blob_sha != Config.blob_sha))
        )
        return self._session.execute(stmt).scalars().all()
