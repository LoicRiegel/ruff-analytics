"""One-off script to copy repos/configs/contents from an old database into the current (freshly re-created) one.

Needed after a schema change to `Config` (repo_owner/repo_name moved out into a separate `Repo` table,
keyed by repo_id). Scan windows are not migrated: `scrapper init` already recreates them from scratch.

Usage:
    uv run scrapper init  # drops and re-creates the schema in RUFF_ANALYTICS_DB
    python scripts/migrate.py ruff_analytics_old.db ruff_analytics.db
"""

import logging
import sys
from datetime import datetime

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from ruff_analytics.scrapper.db import Config, Content, Repo

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def migrate(old_db_url: str, new_db_url: str) -> None:
    old_engine = create_engine(old_db_url)
    new_engine = create_engine(new_db_url)

    with Session(old_engine) as old_session, Session(new_engine) as new_session:
        # the old "configs" table still has repo_owner/repo_name columns that Config no longer maps,
        # so read them with raw SQL instead of the (now repo_owner/repo_name-less) Config ORM class.
        repo_rows = old_session.execute(
            text("SELECT repo_id, repo_owner, repo_name FROM configs ORDER BY discovered_at")
        ).all()
        for repo_id, repo_owner, repo_name in repo_rows:
            new_session.merge(Repo(repo_id=repo_id, repo_owner=repo_owner, repo_name=repo_name))
        logger.info("Migrated %d repo(s)", len({repo_id for repo_id, _, _ in repo_rows}))

        # the old "configs" table has a Config.repo relationship the old table can't satisfy (no "repos" table
        # exists yet there), so read raw columns instead of going through the Config ORM class.
        configs = old_session.execute(
            text(
                "SELECT repo_id, config_path, config_type, blob_sha, commit_sha, discovered_at "
                "FROM configs ORDER BY discovered_at"
            )
        ).all()
        for repo_id, config_path, config_type, blob_sha, commit_sha, discovered_at in configs:
            new_session.merge(
                Config(
                    repo_id=repo_id,
                    config_path=config_path,
                    config_type=config_type,
                    blob_sha=blob_sha,
                    commit_sha=commit_sha,
                    discovered_at=datetime.fromisoformat(discovered_at),
                )
            )
        logger.info("Migrated %d config(s)", len(configs))

        contents = old_session.execute(select(Content).order_by(Content.downloaded_at)).scalars().all()
        for content in contents:
            new_session.merge(
                Content(
                    repo_id=content.repo_id,
                    config_path=content.config_path,
                    blob_sha=content.blob_sha,
                    content=content.content,
                    downloaded_at=content.downloaded_at,
                )
            )
        logger.info("Migrated %d content(s)", len(contents))

        new_session.commit()


def main() -> None:
    if len(sys.argv) != 3:  # noqa: PLR2004
        logger.error("Usage: python scripts/migrate.py <old_db_name> <new_db_name>")
        sys.exit(1)
    old_db_url = f"sqlite:///{sys.argv[1]}"
    new_db_url = f"sqlite:///{sys.argv[2]}"
    migrate(old_db_url, new_db_url)


if __name__ == "__main__":
    main()
