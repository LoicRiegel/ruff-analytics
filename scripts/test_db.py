"""Run EXPLAIN QUERY PLAN and timing for the configs/contents join used by `scrapper status`.

Also creates the covering indexes needed for that join, since `Base.metadata.create_all` only
creates indexes for tables that don't exist yet and won't touch an already-existing database.
"""

import os
import time

from dotenv import load_dotenv
from sqlalchemy import Engine, create_engine, text

from ruff_analytics.scrapper.db import Base

QUERY = r"""
SELECT count(*) FROM configs c JOIN contents t
  ON c.repo_id = t.repo_id AND c.config_path = t.config_path
  WHERE t.blob_sha = c.blob_sha
"""


def create_indexes(engine: Engine) -> None:
    for table in Base.metadata.tables.values():
        for index in table.indexes:
            index.create(engine, checkfirst=True)


def run_query(engine: Engine) -> None:
    with engine.connect() as conn:
        t_start = time.time()
        result = conn.execute(text(QUERY)).fetchone()
        delay = time.time() - t_start
        print(f"Result: {result}")
        print(f"Took {delay:.3f}s")


def main() -> None:
    load_dotenv()
    db_url = os.environ["RUFF_ANALYTICS_DB"]
    engine = create_engine(db_url, connect_args={"timeout": 5})
    create_indexes(engine)
    run_query(engine)


if __name__ == "__main__":
    main()
