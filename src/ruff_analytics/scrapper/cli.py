"""Command-line interface for the ruff configuration scraper."""

import asyncio
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from typer import Typer

from ruff_analytics.scrapper.db import Base
from ruff_analytics.scrapper.scrapper import init_scrapper, run_scraper

DB_URL_ENV_VAR = "RUFF_ANALYTICS_DB"

app = Typer(add_completion=False)


@app.command(help="Initialize the scrapping process and populate the database with initial data")
def init() -> None:
    """Initialize the scrapping.

    Perform the first API call to populate the database with the first data.
    """
    load_dotenv()
    engine = create_engine(os.environ[DB_URL_ENV_VAR])
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        asyncio.run(init_scrapper(session))


@app.command(help="Start or resume scraping to collect ruff configuration files and store metadata")
def start() -> None:
    """Start (or resume) the scrapping.

    Store all ruff configuration files in a database.
    The state of the scrapping are also saved to allow to be paused and resumed.
    """
    load_dotenv()
    engine = create_engine(os.environ[DB_URL_ENV_VAR])
    with Session(engine) as session:
        asyncio.run(run_scraper(session))


if __name__ == "__main__":
    app()
