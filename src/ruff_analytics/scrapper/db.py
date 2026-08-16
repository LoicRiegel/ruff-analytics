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


def create_window(session: Session, config_type: ConfigType, size_range: SizeRange) -> None:
    session.add(
        ScanWindow(
            config_type=config_type,
            size_from=size_range.size_from,
            size_to=size_range.size_to,
            window_status="pending",
            result_count=None,
            created_at=datetime.now(tz=UTC),
        )
    )


def mark_window_as_done(session: Session, window_id: int, result_count: int) -> None:
    window = cast("ScanWindow", session.get(ScanWindow, window_id))
    window.window_status = "done"
    window.result_count = result_count


def mark_window_as_error(session: Session, window_id: int) -> None:
    window = cast("ScanWindow", session.get(ScanWindow, window_id))
    window.window_status = "error"


def mark_window_as_needs_split(session: Session, window_id: int) -> None:
    window = cast("ScanWindow", session.get(ScanWindow, window_id))
    window.window_status = "needs_split"


def split_window(session: Session, window_id: int, size_range_split: SizeRangeSplit) -> None:
    window = cast("ScanWindow", session.get(ScanWindow, window_id))
    config_type = window.config_type
    window.window_status = "split"
    create_window(session, config_type, size_range_split.first)
    create_window(session, config_type, size_range_split.second)


def next_window_to_process(session: Session) -> ScanWindow | None:
    return session.query(ScanWindow).filter(ScanWindow.window_status.in_(["pending", "needs_split"])).first()


class Repo(Base):
    __tablename__ = "repos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)


def save_repo(session: Session, repo_id: int, repo_owner: str, repo_name: str) -> None:
    session.merge(Repo(id=repo_id, owner=repo_owner, name=repo_name))


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


def save_config(
    session: Session,
    repo_id: int,
    config_type: ConfigType,
    config_path: str,
    blob_sha: str,
    commit_sha: str,
    discovered_at: datetime,
) -> None:
    session.merge(
        Config(
            repo_id=repo_id,
            config_type=config_type,
            config_path=config_path,
            blob_sha=blob_sha,
            commit_sha=commit_sha,
            discovered_at=discovered_at,
        )
    )


class Content(Base):
    __tablename__ = "contents"

    repo_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    config_path: Mapped[str] = mapped_column(String, primary_key=True)
    blob_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    downloaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def save_content(
    session: Session, repo_id: int, config_path: str, blob_sha: str, content: str, downloaded_at: datetime
) -> None:
    session.merge(
        Content(
            repo_id=repo_id, config_path=config_path, blob_sha=blob_sha, content=content, downloaded_at=downloaded_at
        )
    )


def configs_to_download(session: Session) -> Sequence[Config]:
    """Return the configs that are not downloaded yet, or whose downloaded content is out of date."""
    stmt = (
        select(Config)
        .outerjoin(Content, (Config.repo_id == Content.repo_id) & (Config.config_path == Content.config_path))
        .where((Content.blob_sha.is_(None)) | (Content.blob_sha != Config.blob_sha))
    )
    return session.execute(stmt).scalars().all()
