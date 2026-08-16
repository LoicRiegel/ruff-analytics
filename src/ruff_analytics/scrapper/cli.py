"""Command-line interface for the ruff configuration scraper."""

import asyncio
import logging
import os

import rich
from dotenv import load_dotenv
from rich.logging import RichHandler
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session
from typer import Typer

from ruff_analytics.scrapper.db import Base, ScrapperRepository
from ruff_analytics.scrapper.discovery import init_discovery, run_discovery
from ruff_analytics.scrapper.download import run_download

DB_URL_ENV_VAR = "RUFF_ANALYTICS_DB"

logger = logging.getLogger(__name__)
app = Typer(add_completion=False)


def set_up_logging(*, debug: bool) -> None:
    logging.basicConfig(level=logging.WARNING, format="%(message)s", handlers=[RichHandler(rich_tracebacks=True)])
    level = logging.DEBUG if debug else logging.INFO
    logging.getLogger("ruff_analytics").setLevel(level)


def _create_engine(db_url: str) -> Engine:
    engine = create_engine(db_url, connect_args={"timeout": 5})
    with engine.connect() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL"))
    return engine


@app.command(help="Initialize the scrapping process and populate the database with initial data")
def init(debug: bool = False) -> None:  # noqa: FBT001, FBT002
    """Initialize the scrapping.

    Perform the first API call to populate the database with the first data.
    """
    load_dotenv()
    set_up_logging(debug=debug)
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
def start(debug: bool = False) -> None:  # noqa: FBT001, FBT002
    """Start (or resume) the scrapping.

    Store all ruff configuration files in a database.
    The state of the scrapping are also saved to allow to be paused and resumed.
    """
    load_dotenv()
    set_up_logging(debug=debug)
    engine = _create_engine(os.environ[DB_URL_ENV_VAR])
    rich.print("Resuming the scrapping... (exit with CTRL+C)")
    with Session(engine) as discovery_session, Session(engine) as download_session:
        discovery_repository = ScrapperRepository(discovery_session)
        download_repository = ScrapperRepository(download_session)
        try:
            asyncio.run(_start_discovery_and_download(discovery_repository, download_repository))
        except KeyboardInterrupt:
            rich.print("Scraping interrupted (can be resumed later)")


async def _start_discovery_and_download(
    discovery_repository: ScrapperRepository, download_repository: ScrapperRepository
) -> None:
    trigger_download_event = asyncio.Event()
    discovery_done_event = asyncio.Event()
    await asyncio.gather(
        run_discovery(discovery_repository, trigger_download_event, discovery_done_event),
        run_download(download_repository, trigger_download_event, discovery_done_event),
    )


if __name__ == "__main__":
    app()
