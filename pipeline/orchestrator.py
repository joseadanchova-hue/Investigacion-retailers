"""
Weekly pipeline entry point.

Runs each retailer's scraper as a subprocess, validates the freshness/completeness
of the CSV it produced, and loads whatever succeeded into a SQLite historical
snapshot. A failure in one retailer never blocks the other, and this script
always exits 0 unless the orchestrator itself (not a scraper) crashes, so
Windows Task Scheduler never flags a partial-success run as an error.

Usage: python pipeline/orchestrator.py   (run from anywhere; paths are absolute)
"""

import csv
import logging
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
import db
import export


@dataclass
class RetailerResult:
    status: str  # "success" | "failed"
    error: Optional[str] = None
    csv_path: Optional[Path] = None


def clear_dir(path: Path) -> None:
    if path.exists():
        for child in path.iterdir():
            if child.is_dir():
                for sub in child.rglob("*"):
                    if sub.is_file():
                        sub.unlink()
                for sub in sorted(child.rglob("*"), reverse=True):
                    if sub.is_dir():
                        sub.rmdir()
                child.rmdir()
            else:
                child.unlink()
    path.mkdir(parents=True, exist_ok=True)


def setup_logging(run_id: str) -> logging.Logger:
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("readymeals_pipeline")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    file_handler = logging.FileHandler(config.LOG_DIR / f"run_{run_id}.log", encoding="utf-8")
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(fmt)
    logger.addHandler(stream_handler)

    return logger


def run_retailer(retailer: dict, run_id: str, run_start_ts: float, logger: logging.Logger) -> RetailerResult:
    name = retailer["name"]
    logger.info(f"--- {name}: starting ---")
    csv_path = retailer["dir"] / retailer["csv_name"]

    try:
        clear_dir(retailer["tmp_dir"])
        if csv_path.exists():
            csv_path.unlink()

        subprocess_log = config.LOG_DIR / f"run_{run_id}_{name.lower()}.log"
        with open(subprocess_log, "w", encoding="utf-8") as f:
            proc = subprocess.run(
                [sys.executable, retailer["script"]],
                cwd=retailer["dir"],
                stdout=f,
                stderr=subprocess.STDOUT,
                timeout=config.SCRAPER_TIMEOUT_SECONDS,
            )

        if proc.returncode != 0:
            msg = f"scraper exited with code {proc.returncode}; see {subprocess_log}"
            logger.error(f"{name}: {msg}")
            return RetailerResult(status="failed", error=msg)

        if not csv_path.exists():
            msg = f"scraper exited 0 but produced no CSV at {csv_path}"
            logger.error(f"{name}: {msg}")
            return RetailerResult(status="failed", error=msg)

        if csv_path.stat().st_mtime < run_start_ts:
            msg = "CSV mtime predates this run's start — treating as stale, not loading"
            logger.error(f"{name}: {msg}")
            return RetailerResult(status="failed", error=msg)

        logger.info(f"{name}: scraper completed OK, CSV at {csv_path}")
        return RetailerResult(status="success", csv_path=csv_path)

    except subprocess.TimeoutExpired:
        msg = f"scraper timed out after {config.SCRAPER_TIMEOUT_SECONDS}s"
        logger.error(f"{name}: {msg}")
        return RetailerResult(status="failed", error=msg)
    except Exception as exc:
        logger.exception(f"{name}: unexpected error launching/monitoring scraper")
        return RetailerResult(status="failed", error=str(exc))


def load_csv_into_db(conn, retailer: dict, run_id: str, snapshot_datetime: str, logger: logging.Logger) -> int:
    name = retailer["name"]
    csv_path = retailer["dir"] / retailer["csv_name"]
    rows_loaded = 0
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            db.insert_snapshot_row(conn, run_id, snapshot_datetime, name, row)
            rows_loaded += 1
    conn.commit()
    logger.info(f"{name}: loaded {rows_loaded} rows into snapshots (run_id={run_id})")
    return rows_loaded


def main() -> None:
    run_id = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    logger = setup_logging(run_id)
    logger.info(f"=== Pipeline run {run_id} starting ===")
    run_start_ts = time.time()
    snapshot_datetime = datetime.now(timezone.utc).isoformat()

    conn = db.get_connection(config.DB_PATH)
    db.init_schema(conn)

    results: dict[str, RetailerResult] = {}
    for retailer in config.RETAILERS:
        started_at = datetime.now(timezone.utc).isoformat()
        try:
            result = run_retailer(retailer, run_id, run_start_ts, logger)
        except Exception:
            logger.exception(f"UNEXPECTED orchestrator error handling {retailer['name']}")
            result = RetailerResult(status="failed", error="orchestrator exception")
        results[retailer["name"]] = result

        row_count = 0
        if result.status == "success":
            try:
                row_count = load_csv_into_db(conn, retailer, run_id, snapshot_datetime, logger)
            except Exception:
                logger.exception(f"{retailer['name']}: failed to load CSV into database")
                result.status = "failed"
                result.error = "CSV load into SQLite failed"
                row_count = 0

        finished_at = datetime.now(timezone.utc).isoformat()
        db.write_run_log(
            conn, run_id, retailer["name"], started_at, finished_at,
            result.status, row_count, result.error, result.csv_path,
        )

    try:
        export.export_latest_snapshot(conn, config.EXPORT_PATH)
        logger.info(f"Export Excel actualizado en {config.EXPORT_PATH}")
    except Exception:
        logger.exception("Fallo al generar el export Excel (no bloqueante)")

    conn.close()

    elapsed = time.time() - run_start_ts
    logger.info(f"=== Pipeline run {run_id} finished in {elapsed:.0f}s ===")
    for name, result in results.items():
        logger.info(f"  {name}: {result.status}, error={result.error or '-'}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.basicConfig()
        logging.exception("FATAL: orchestrator crashed outside main()'s own handling")
        sys.exit(1)
