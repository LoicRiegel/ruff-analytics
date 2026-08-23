"""One-off migration helpers for normalizing config content by blob SHA.

Step 1 creates/populates `blobs` from existing `contents.content`.
Step 2 rebuilds `contents` without the denormalized `content` column.
"""

import os
import time

from dotenv import load_dotenv
from sqlalchemy import Engine, create_engine, text

BATCH_SIZE = 10_000


def _format_progress(processed: int, total: int, started_at: float) -> str:
    elapsed = max(time.time() - started_at, 1e-9)
    percent = (processed / total * 100) if total else 100.0
    rate = processed / elapsed
    return f"processed={processed}/{total} ({percent:.1f}%), elapsed={elapsed:.1f}s, rate={rate:.0f} rows/s"


def migration_step_1(engine: Engine) -> None:
    """Create `blobs` and backfill it from existing rows in `contents`."""
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS blobs (
                    blob_sha VARCHAR(40) PRIMARY KEY,
                    content TEXT NOT NULL
                )
                """
            )
        )

    with engine.connect() as conn:
        min_rowid, max_rowid, total_rows = conn.execute(
            text("SELECT min(rowid), max(rowid), count(*) FROM contents")
        ).one()

    if min_rowid is None or max_rowid is None:
        min_rowid = 0
        max_rowid = 0

    min_rowid = int(min_rowid)
    max_rowid = int(max_rowid)
    total_rows = int(total_rows)
    print(f"{min_rowid = }")
    print(f"{max_rowid = }")
    print(f"{total_rows = }")

    if total_rows == 0:
        print("No rows in contents. Step 1 is done.")
        return

    print(f"Step 1 starting with batch size {BATCH_SIZE}.")
    started_at = time.time()
    processed = 0

    batch_start = min_rowid
    while batch_start <= max_rowid:
        batch_end = batch_start + BATCH_SIZE - 1
        with engine.begin() as conn:
            source_rows = conn.execute(
                text(
                    """
                    SELECT count(*)
                    FROM contents
                    WHERE rowid BETWEEN :start_rowid AND :end_rowid
                    """
                ),
                {"start_rowid": batch_start, "end_rowid": batch_end},
            ).scalar_one()

            if source_rows > 0:
                conn.execute(
                    text(
                        """
                        INSERT OR IGNORE INTO blobs (blob_sha, content)
                        SELECT blob_sha, content
                        FROM contents
                        WHERE rowid BETWEEN :start_rowid AND :end_rowid
                        """
                    ),
                    {"start_rowid": batch_start, "end_rowid": batch_end},
                )

            processed += source_rows

        print(f"Step 1 progress: {_format_progress(processed, total_rows, started_at)}")
        batch_start = batch_end + 1

    with engine.connect() as conn:
        blob_count = conn.execute(text("SELECT count(*) FROM blobs")).scalar_one()
    print(f"Step 1 finished. Distinct blobs: {blob_count}")


def migration_step_2(engine: Engine) -> None:
    """Rebuild `contents` without `content`, keeping only the blob reference."""
    with engine.connect() as conn:
        existing_contents_new = conn.execute(
            text("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = :name LIMIT 1"), {"name": "contents_new"}
        ).fetchone()

    if existing_contents_new is not None:
        print("Found existing contents_new table. Drop it manually before re-running step 2.")
        return

    with engine.connect() as conn:
        min_rowid, max_rowid, total_rows = conn.execute(
            text("SELECT min(rowid), max(rowid), count(*) FROM contents")
        ).one()

    min_rowid = int(min_rowid)
    max_rowid = int(max_rowid)
    total_rows = int(total_rows)

    with engine.begin() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=OFF")

        conn.execute(
            text(
                """
                CREATE TABLE contents_new (
                    repo_id INTEGER NOT NULL,
                    config_path VARCHAR NOT NULL,
                    blob_sha VARCHAR(40) NOT NULL,
                    downloaded_at DATETIME NOT NULL,
                    PRIMARY KEY (repo_id, config_path),
                    FOREIGN KEY(blob_sha) REFERENCES blobs (blob_sha)
                )
                """
            )
        )

    print(f"Step 2 starting with batch size {BATCH_SIZE}.")
    started_at = time.time()
    processed = 0

    batch_start = min_rowid
    while batch_start <= max_rowid:
        batch_end = batch_start + BATCH_SIZE - 1
        with engine.begin() as conn:
            moved = conn.execute(
                text(
                    """
                    INSERT INTO contents_new (repo_id, config_path, blob_sha, downloaded_at)
                    SELECT repo_id, config_path, blob_sha, downloaded_at
                    FROM contents
                    WHERE rowid BETWEEN :start_rowid AND :end_rowid
                    """
                ),
                {"start_rowid": batch_start, "end_rowid": batch_end},
            )
            processed += moved.rowcount

        print(f"Step 2 progress: {_format_progress(processed, total_rows, started_at)}")
        batch_start = batch_end + 1

    with engine.begin() as conn:
        conn.execute(text("DROP TABLE contents"))
        conn.execute(text("ALTER TABLE contents_new RENAME TO contents"))
        conn.execute(text("CREATE INDEX idx_contents_lookup ON contents (repo_id, config_path, blob_sha)"))

        conn.exec_driver_sql("PRAGMA foreign_keys=ON")

    print("Step 2 finished.")


def main() -> None:
    load_dotenv()
    db_url = os.environ["RUFF_ANALYTICS_DB"]
    engine = create_engine(db_url, connect_args={"timeout": 5})

    # Run migration_step_1 or migration_step_2
    migration_step_2(engine)


if __name__ == "__main__":
    main()
