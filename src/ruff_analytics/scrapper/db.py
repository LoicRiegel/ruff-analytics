"""Database models."""

from datetime import UTC
from typing import TYPE_CHECKING, Literal, cast

from sqlalchemy import Date, DateTime, Index, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from ruff_analytics.scrapper.date_range import DateRange, DateRangeSplit

if TYPE_CHECKING:
    from datetime import date, datetime


class Base(DeclarativeBase):  # noqa: D101
    pass


type ConfigType = Literal[
    "ruff.toml", ".ruff.toml", "pyproject.toml"  # only those containing a [tool.ruff] section
]

type WindowStatus = Literal["pending", "done", "needs_split", "split", "error"]


class ScanWindow(Base):
    __tablename__ = "scan_windows"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    config_type: Mapped[ConfigType] = mapped_column(String(20), nullable=False)
    date_from: Mapped[date] = mapped_column(Date, nullable=False)
    date_to: Mapped[date] = mapped_column(Date, nullable=False)
    window_status: Mapped[WindowStatus] = mapped_column(String(20), nullable=False)
    result_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def create_window(session: Session, config_type: ConfigType, date_range: DateRange) -> None:
    """Create a new scan window with status PENDING."""
    session.add(
        ScanWindow(
            config_type=config_type,
            date_from=date_range.date_from,
            date_to=date_range.date_to,
            window_status="pending",
            result_count=None,
            created_at=datetime.now(tz=UTC),
        )
    )


def mark_window_as_done(session: Session, window_id: int, result_count: int) -> None:
    """Set the status of a scan window to DONE."""
    window = cast("ScanWindow", session.get(ScanWindow, window_id))
    window.window_status = "done"
    window.result_count = result_count


def mark_window_as_error(session: Session, window_id: int) -> None:
    """Set the status of a scan window to ERROR."""
    window = cast("ScanWindow", session.get(ScanWindow, window_id))
    window.window_status = "error"


def mark_window_as_needs_split(session: Session, window_id: int) -> None:
    """Set the status of a scan window to NEEDS_SPLIT."""
    window = cast("ScanWindow", session.get(ScanWindow, window_id))
    window.window_status = "needs_split"


def split_window(session: Session, window_id: int, date_range_split: DateRangeSplit) -> None:
    """Set the status of a scan window to SPLIT and adds new windows to scan with status PENDING."""
    window = cast("ScanWindow", session.get(ScanWindow, window_id))
    config_type = window.config_type
    window.window_status = "split"
    create_window(session, config_type, date_range_split.first)
    create_window(session, config_type, date_range_split.second)


def next_pending_window(session: Session) -> ScanWindow | None:
    """Return the next pending window."""
    return session.query(ScanWindow).filter_by(window_status="pending").first()


class Config(Base):
    __tablename__ = "configs"
    __table_args__ = (Index("idx_configs_type", "config_type"), Index("idx_configs_discovered_at", "discovered_at"))

    repo_owner: Mapped[str] = mapped_column(String, primary_key=True)
    repo_name: Mapped[str] = mapped_column(String, primary_key=True)
    config_path: Mapped[str] = mapped_column(String, primary_key=True)
    config_type: Mapped[ConfigType] = mapped_column(String(40), nullable=False)
    branch: Mapped[str] = mapped_column(String, nullable=False)
    commit_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def save_config(
    session: Session,
    repo_owner: str,
    repo_name: str,
    config_path: str,
    branch: str,
    commit_sha: str,
    discovered_at: datetime,
) -> None:
    session.merge(
        Config(
            repo_owner=repo_owner,
            repo_name=repo_name,
            config_path=config_path,
            branch=branch,
            commit_sha=commit_sha,
            discovered_at=discovered_at,
        )
    )
