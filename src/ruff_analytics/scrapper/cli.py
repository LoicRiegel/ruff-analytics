"""Command-line interface for the ruff configuration scraper."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING

import rich
from dotenv import load_dotenv
from rich.logging import RichHandler
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session
from typer import Typer

from ruff_analytics.scrapper.db import Base, ScrapperRepository
from ruff_analytics.scrapper.discovery import init_discovery, run_discovery
from ruff_analytics.scrapper.download import run_download

if TYPE_CHECKING:
    import sqlite3

    from sqlalchemy.pool import ConnectionPoolEntry

DB_URL_ENV_VAR = "RUFF_ANALYTICS_DB"

logger = logging.getLogger(__name__)
app = Typer(add_completion=False)


def set_up_logging() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(message)s", handlers=[RichHandler(rich_tracebacks=True)])
    logging.getLogger("ruff_analytics").setLevel(logging.DEBUG)


def _create_engine(db_url: str) -> Engine:
    engine = create_engine(db_url, connect_args={"timeout": 5})

    if engine.url.get_backend_name() == "sqlite":

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection: sqlite3.Connection, _connection_record: ConnectionPoolEntry) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    with engine.connect() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL"))
    return engine


@app.command(help="Initialize the scrapping process and populate the database with initial data")
def init() -> None:
    """Initialize the scrapping.

    Perform the first API call to populate the database with the first data.
    """
    load_dotenv()
    set_up_logging()
    engine = _create_engine(os.environ[DB_URL_ENV_VAR])
    logger.debug("Clean database")
    Base.metadata.drop_all(engine)
    logger.debug("Create database")
    Base.metadata.create_all(engine)
    logger.debug("Initialize database")
    with Session(engine) as session:
        asyncio.run(init_discovery(ScrapperRepository(session)))
    rich.print("Scrapper initialization done")


@app.command(help="Start or resume scraping to collect ruff configuration files and store metadata")
def start() -> None:
    """Start (or resume) the scrapping.

    Store all ruff configuration files in a database.
    The state of the scrapping are also saved to allow to be paused and resumed.
    """
    load_dotenv()
    set_up_logging()
    engine = _create_engine(os.environ[DB_URL_ENV_VAR])
    rich.print("Resuming the scrapping... (exit with CTRL+C)")
    with Session(engine) as discovery_session, Session(engine) as download_session:
        discovery_repository = ScrapperRepository(discovery_session)
        download_repository = ScrapperRepository(download_session)
        try:
            asyncio.run(_start_discovery_and_download(discovery_repository, download_repository))
        except KeyboardInterrupt:
            rich.print("Scraping interrupted (can be resumed later)")


@app.command(help="Print the current discovery and download progress")
def status() -> None:
    """Print the number of discovered and downloaded configs."""
    load_dotenv()
    set_up_logging()
    engine = _create_engine(os.environ[DB_URL_ENV_VAR])
    with Session(engine) as session:
        repository = ScrapperRepository(session)
        discovered = repository.count_discovered_configs()
        up_to_date, stale = repository.count_downloaded_configs()
    up_to_date_percentage = (up_to_date / discovered * 100) if discovered else 0.0
    stale_percentage = (stale / discovered * 100) if discovered else 0.0
    rich.print(f"Discovered {discovered} configs")
    rich.print(f"Downloaded {up_to_date}/{discovered} configs (up to date) ({up_to_date_percentage:.0f}%)")
    rich.print(f"Downloaded {stale}/{discovered} configs (stale) ({stale_percentage:.0f}%)")


async def _start_discovery_and_download(
    discovery_repository: ScrapperRepository, download_repository: ScrapperRepository
) -> None:
    discovery_done_event = asyncio.Event()
    async with asyncio.TaskGroup() as tg:
        tg.create_task(run_discovery(discovery_repository, discovery_done_event), name="discovery")
        tg.create_task(run_download(download_repository, discovery_done_event), name="download")


if __name__ == "__main__":
    app()
