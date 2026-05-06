#!/usr/bin/env python3
"""Read-only web dashboard for ops monitor history."""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from http import HTTPStatus
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

try:
    from .ops_monitor import DEFAULT_CONFIG, load_config
except ImportError:
    from ops_monitor import DEFAULT_CONFIG, load_config


ROOT = Path(__file__).resolve().parent
STATIC_ROOT = ROOT / "web"


def ensure_dashboard_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS metric_samples (
                timestamp INTEGER PRIMARY KEY,
                load_1m REAL,
                load_per_cpu REAL,
                cpu_count INTEGER NOT NULL,
                temperature_celsius REAL,
                memory_percent REAL,
                max_disk_percent REAL,
                process_count INTEGER NOT NULL,
                watched_process_count INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS findings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp INTEGER NOT NULL,
                severity TEXT NOT NULL,
                finding_key TEXT NOT NULL,
                message TEXT NOT NULL
            )
            """
        )


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def connect(db_path: Path) -> sqlite3.Connection:
    ensure_dashboard_db(db_path)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def severity_rank(severity: str | None) -> int:
    return {"CRITICAL": 3, "WARN": 2, "INFO": 1}.get(str(severity or "").upper(), 0)


def overall_status(latest: dict[str, Any] | None, active_findings: list[dict[str, Any]]) -> str:
    if not latest:
        return "NO_DATA"
    if any(finding["severity"] == "CRITICAL" for finding in active_findings):
        return "CRITICAL"
    if any(finding["severity"] == "WARN" for finding in active_findings):
        return "WARN"
    return "OK"


def get_summary(db_path: Path, active_window_seconds: int = 3600) -> dict[str, Any]:
    now = int(time.time())
    with connect(db_path) as connection:
        latest_row = connection.execute(
            "SELECT * FROM metric_samples ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        latest = row_to_dict(latest_row) if latest_row else None

        active_rows = connection.execute(
            """
            SELECT timestamp, severity, finding_key, message
            FROM findings
            WHERE timestamp >= ?
            ORDER BY timestamp DESC
            LIMIT 50
            """,
            (now - active_window_seconds,),
        ).fetchall()
        active_findings = [row_to_dict(row) for row in active_rows]

        counts_row = connection.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN severity = 'CRITICAL' THEN 1 ELSE 0 END) AS critical,
                SUM(CASE WHEN severity = 'WARN' THEN 1 ELSE 0 END) AS warn
            FROM findings
            WHERE timestamp >= ?
            """,
            (now - 86400,),
        ).fetchone()
        counts = row_to_dict(counts_row) if counts_row else {"total": 0, "critical": 0, "warn": 0}

    active_findings.sort(key=lambda item: (severity_rank(item["severity"]), item["timestamp"]), reverse=True)
    return {
        "status": overall_status(latest, active_findings),
        "generated_at": now,
        "latest": latest,
        "active_window_seconds": active_window_seconds,
        "active_findings": active_findings,
        "last_24h": counts,
    }


def get_history(db_path: Path, since_seconds: int, limit: int) -> dict[str, Any]:
    now = int(time.time())
    since = now - since_seconds
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM metric_samples
            WHERE timestamp >= ?
            ORDER BY timestamp ASC
            LIMIT ?
            """,
            (since, limit),
        ).fetchall()
    return {"generated_at": now, "since": since, "samples": [row_to_dict(row) for row in rows]}


def get_findings(db_path: Path, since_seconds: int, limit: int) -> dict[str, Any]:
    now = int(time.time())
    since = now - since_seconds
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT timestamp, severity, finding_key, message
            FROM findings
            WHERE timestamp >= ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (since, limit),
        ).fetchall()
    findings = [row_to_dict(row) for row in rows]
    findings.sort(key=lambda item: (item["timestamp"], severity_rank(item["severity"])), reverse=True)
    return {"generated_at": now, "since": since, "findings": findings}


def parse_int(query: dict[str, list[str]], name: str, default: int, minimum: int, maximum: int) -> int:
    raw_value = query.get(name, [str(default)])[0]
    try:
        value = int(raw_value)
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))


class DashboardHandler(SimpleHTTPRequestHandler):
    db_path: Path

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(STATIC_ROOT), **kwargs)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self) -> None:
        parsed_url = urlparse(self.path)
        if parsed_url.path.startswith("/api/"):
            self.handle_api(parsed_url.path, parse_qs(parsed_url.query))
            return
        if parsed_url.path == "/":
            self.path = "/index.html"
        super().do_GET()

    def handle_api(self, path: str, query: dict[str, list[str]]) -> None:
        try:
            if path == "/api/summary":
                payload = get_summary(self.db_path)
            elif path == "/api/history":
                hours = parse_int(query, "hours", 24, 1, 24 * 90)
                limit = parse_int(query, "limit", 720, 1, 5000)
                payload = get_history(self.db_path, hours * 3600, limit)
            elif path == "/api/findings":
                hours = parse_int(query, "hours", 24, 1, 24 * 90)
                limit = parse_int(query, "limit", 200, 1, 1000)
                payload = get_findings(self.db_path, hours * 3600, limit)
            else:
                self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
                return
        except sqlite3.Error as exc:
            self.send_json({"error": f"database error: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        self.send_json(payload)

    def send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        response = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve the ops monitor dashboard.")
    parser.add_argument("-c", "--config", default="ops_monitor/config.example.json", help="monitor config path")
    parser.add_argument("--host", default="127.0.0.1", help="bind host")
    parser.add_argument("--port", type=int, default=8765, help="bind port")
    parser.add_argument("--db", default="", help="override history database path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = Path(args.config)
    config = load_config(config_path) if config_path.exists() else DEFAULT_CONFIG
    db_path = Path(args.db or config.get("history_db", "ops_monitor/ops-monitor.db"))

    DashboardHandler.db_path = db_path
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    print(f"Ops dashboard listening on http://{args.host}:{args.port}")
    print(f"Reading history database: {db_path}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
