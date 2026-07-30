"""Command-line interface for the ruff configuration scraper."""

from dotenv import load_dotenv
from typer import Typer

app = Typer(add_completion=False)


@app.command(help="Initialize the scrapping process and populate the database with initial data")
def init() -> None:
    """Initialize the scrapping.

    Perform the first API call to populate the database with the first data.
    """
    load_dotenv()


@app.command(help="Start or resume scraping to collect ruff configuration files and store metadata")
def start() -> None:
    """Start (or resume) the scrapping.

    Store all ruff configuration files in a database.
    The state of the scrapping are also saved to allow to be paused and resumed.
    """
    load_dotenv()


if __name__ == "__main__":
    app()
