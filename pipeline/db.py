"""SQLite schema and insert helpers for the readymeals pipeline database."""

import sqlite3
from pathlib import Path

from config import COLUMNS

_DATA_COLUMNS_SQL = ",\n    ".join(f"{col} TEXT" for col in COLUMNS)

SCHEMA_SQL = f"""
CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    snapshot_datetime TEXT NOT NULL,
    retailer TEXT NOT NULL,
    {_DATA_COLUMNS_SQL}
);

CREATE INDEX IF NOT EXISTS idx_snapshots_run_id ON snapshots(run_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_retailer ON snapshots(retailer, snapshot_datetime);
CREATE INDEX IF NOT EXISTS idx_snapshots_product ON snapshots(product_id, retailer);

CREATE TABLE IF NOT EXISTS run_log (
    run_id TEXT NOT NULL,
    retailer TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    row_count INTEGER,
    error_message TEXT,
    csv_path TEXT,
    PRIMARY KEY (run_id, retailer)
);
"""

_INSERT_COLUMNS = ["run_id", "snapshot_datetime", "retailer"] + COLUMNS
_INSERT_SQL = (
    "INSERT INTO snapshots (" + ", ".join(_INSERT_COLUMNS) + ") VALUES ("
    + ", ".join("?" for _ in _INSERT_COLUMNS) + ")"
)


def get_connection(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    conn.commit()


def insert_snapshot_row(conn: sqlite3.Connection, run_id: str, snapshot_datetime: str,
                         retailer: str, row: dict) -> None:
    values = [run_id, snapshot_datetime, retailer] + [row.get(col, "") for col in COLUMNS]
    conn.execute(_INSERT_SQL, values)


def write_run_log(conn: sqlite3.Connection, run_id: str, retailer: str, started_at: str,
                   finished_at: str, status: str, row_count, error_message, csv_path) -> None:
    conn.execute(
        """
        INSERT INTO run_log (run_id, retailer, started_at, finished_at, status, row_count, error_message, csv_path)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_id, retailer) DO UPDATE SET
            finished_at=excluded.finished_at,
            status=excluded.status,
            row_count=excluded.row_count,
            error_message=excluded.error_message,
            csv_path=excluded.csv_path
        """,
        (run_id, retailer, started_at, finished_at, status, row_count, error_message,
         str(csv_path) if csv_path else None),
    )
    conn.commit()
