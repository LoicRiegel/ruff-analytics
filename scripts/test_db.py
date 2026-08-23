"""Inspect discovery window statuses to understand remaining discovery backlog."""

import os
import time

from dotenv import load_dotenv
from sqlalchemy import Engine, create_engine, text

from ruff_analytics.scrapper.db import Base

STATUS_COUNTS_QUERY = r"""
SELECT
    window_status,
    count(*) AS window_count
FROM discovery_windows
GROUP BY window_status
ORDER BY window_count DESC, window_status ASC
"""

BACKLOG_WINDOWS_QUERY = r"""
SELECT
    id,
    config_type,
    size_from,
    size_to,
    window_status,
    result_count,
    created_at
FROM discovery_windows
WHERE window_status IN ('pending', 'needs_split')
   OR window_status NOT IN ('done', 'split', 'error')
ORDER BY created_at ASC, id ASC
"""


def create_indexes(engine: Engine) -> None:
    for table in Base.metadata.tables.values():
        for index in table.indexes:
            index.create(engine, checkfirst=True)


def run_query(engine: Engine) -> None:
    with engine.connect() as conn:
        t_start = time.time()
        status_counts = conn.execute(text(STATUS_COUNTS_QUERY)).fetchall()
        backlog_windows = conn.execute(text(BACKLOG_WINDOWS_QUERY)).fetchall()
        delay = time.time() - t_start

        print("Status counts:")
        for status, count in status_counts:
            print(f"- {status}: {count}")

        print(f"\nBacklog rows: {len(backlog_windows)}")
        for row in backlog_windows:
            print(row)

        print(f"Took {delay:.3f}s")


def main() -> None:
    load_dotenv()
    db_url = os.environ["RUFF_ANALYTICS_DB"]
    engine = create_engine(db_url, connect_args={"timeout": 5})
    create_indexes(engine)
    run_query(engine)


if __name__ == "__main__":
    main()
