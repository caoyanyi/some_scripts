#!/usr/bin/env python3
"""Web dashboard for ops monitor history and whitelisted diagnostics."""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
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
ACTION_TIMEOUT_SECONDS = 8

# Keep this list read-only. The dashboard is usually reachable from the LAN, so
# it must not expose arbitrary shell input or destructive operations.
DIAGNOSTIC_ACTIONS: dict[str, dict[str, Any]] = {
    "uptime": {
        "label": "系统运行时间",
        "command": ["uptime"],
    },
    "disk": {
        "label": "磁盘空间",
        "command": ["df", "-h", "-x", "tmpfs", "-x", "devtmpfs"],
    },
    "memory": {
        "label": "内存详情",
        "command": ["free", "-h"],
    },
    "services": {
        "label": "监控服务状态",
        "command": ["systemctl", "status", "ops-monitor.service", "ops-monitor-dashboard.service", "--no-pager"],
    },
    "monitor_log": {
        "label": "监控日志",
        "command": ["journalctl", "-u", "ops-monitor.service", "-n", "80", "--no-pager"],
    },
    "dashboard_log": {
        "label": "仪表盘日志",
        "command": ["journalctl", "-u", "ops-monitor-dashboard.service", "-n", "80", "--no-pager"],
    },
    "processes": {
        "label": "进程快照",
        "command": ["ps", "-eo", "pid,ppid,stat,pcpu,pmem,etimes,args", "--sort=-pcpu"],
    },
}


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
                memory_total_bytes INTEGER,
                memory_used_bytes INTEGER,
                swap_total_bytes INTEGER,
                swap_used_bytes INTEGER,
                disk_total_bytes INTEGER,
                disk_used_bytes INTEGER,
                process_count INTEGER NOT NULL,
                watched_process_count INTEGER NOT NULL
            )
            """
        )
        ensure_columns(
            connection,
            "metric_samples",
            {
                "memory_total_bytes": "INTEGER",
                "memory_used_bytes": "INTEGER",
                "swap_total_bytes": "INTEGER",
                "swap_used_bytes": "INTEGER",
                "disk_total_bytes": "INTEGER",
                "disk_used_bytes": "INTEGER",
            },
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
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS process_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp INTEGER NOT NULL,
                rank_type TEXT NOT NULL,
                rank_position INTEGER NOT NULL,
                pid INTEGER NOT NULL,
                ppid INTEGER NOT NULL,
                stat TEXT NOT NULL,
                elapsed_seconds INTEGER NOT NULL,
                cpu_percent REAL NOT NULL,
                memory_percent REAL NOT NULL,
                rss_kb INTEGER NOT NULL,
                command TEXT NOT NULL
            )
            """
        )


def ensure_columns(connection: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    if table != "metric_samples":
        raise ValueError(f"unexpected table for schema migration: {table}")
    existing_columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
    for column_name, column_type in columns.items():
        if column_name not in existing_columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column_name} {column_type}")


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def localize_message(message: str) -> str:
    replacements = [
        ("system temperature is ", "系统温度当前为 "),
        ("temperature sensor data was not found", "未找到温度传感器数据"),
        ("memory usage could not be read from /proc/meminfo", "无法从 /proc/meminfo 读取内存使用率"),
        ("memory usage is ", "内存使用率当前为 "),
        ("disk usage on ", "磁盘使用率："),
        ("disk path ", "磁盘路径 "),
        (" could not be read", " 无法读取"),
        ("1m load per CPU ", "1分钟平均负载/CPU "),
        ("threshold ", "阈值为 "),
        ("process rule '", "进程规则“"),
        ("' matched pid ", "”命中 PID "),
        ("runtime ", "运行时间 "),
        ("command=", "命令="),
        ("cleanup=", "清理结果="),
        ("dry-run: would terminate pid ", "演练模式：将终止 PID "),
        ("terminated pid ", "已终止 PID "),
        ("killed pid ", "已强制结束 PID "),
        (" after SIGTERM grace period", "（SIGTERM 等待超时后）"),
        ("process already exited", "进程已退出"),
        ("permission denied", "权限不足"),
        ("process is in uninterruptible sleep state", "进程处于不可中断睡眠状态"),
        (" for ", "，已持续 "),
        ("cpu ", "CPU "),
        (" failed", "失败"),
    ]
    localized = message
    for english_text, chinese_text in replacements:
        localized = localized.replace(english_text, chinese_text)
    return localized.replace(", ", "，").replace("; ", "；")


def localize_finding(finding: dict[str, Any]) -> dict[str, Any]:
    return {**finding, "message": localize_message(str(finding.get("message", "")))}


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


def merge_finding_rows(rows: list[sqlite3.Row], merge_window_seconds: int) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    active_groups: dict[tuple[str, str], dict[str, Any]] = {}

    for row in rows:
        finding = localize_finding(row_to_dict(row))
        group_key = (str(finding["severity"]), str(finding["finding_key"]))
        group = active_groups.get(group_key)
        if group and int(group["first_timestamp"]) - int(finding["timestamp"]) <= merge_window_seconds:
            group["first_timestamp"] = finding["timestamp"]
            group["repeat_count"] += 1
            continue

        group = {
            **finding,
            "last_timestamp": finding["timestamp"],
            "first_timestamp": finding["timestamp"],
            "repeat_count": 1,
        }
        active_groups[group_key] = group
        merged.append(group)

    return merged


def paginate_items(items: list[dict[str, Any]], page: int, page_size: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    total = len(items)
    total_pages = max(1, (total + page_size - 1) // page_size)
    current_page = max(1, min(page, total_pages))
    start = (current_page - 1) * page_size
    end = start + page_size
    return items[start:end], {
        "page": current_page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
    }


def available_actions() -> list[dict[str, str]]:
    return [{"id": action_id, "label": spec["label"]} for action_id, spec in DIAGNOSTIC_ACTIONS.items()]


def run_diagnostic_action(action_id: str) -> dict[str, Any]:
    action = DIAGNOSTIC_ACTIONS.get(action_id)
    if not action:
        return {"error": "操作不存在或未被允许"}

    started_at = int(time.time())
    try:
        result = subprocess.run(
            action["command"],
            check=False,
            capture_output=True,
            text=True,
            timeout=ACTION_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        return {"error": "系统缺少执行该操作所需的命令"}
    except subprocess.TimeoutExpired as exc:
        partial_output = "\n".join(part for part in [exc.stdout, exc.stderr] if part)
        return {
            "id": action_id,
            "label": action["label"],
            "started_at": started_at,
            "exit_code": None,
            "output": partial_output[:12000],
            "error": f"操作超过 {ACTION_TIMEOUT_SECONDS} 秒未完成，已停止",
        }

    output = "\n".join(part for part in [result.stdout, result.stderr] if part).strip()
    if action_id == "processes":
        output = "\n".join(output.splitlines()[:80])
    return {
        "id": action_id,
        "label": action["label"],
        "started_at": started_at,
        "exit_code": result.returncode,
        "output": output[:12000] or "命令已完成，没有输出内容。",
    }


def get_latest_process_samples(connection: sqlite3.Connection, rank_type: str, limit: int = 8) -> list[dict[str, Any]]:
    latest_row = connection.execute(
        "SELECT MAX(timestamp) AS timestamp FROM process_samples WHERE rank_type = ?",
        (rank_type,),
    ).fetchone()
    if not latest_row or latest_row["timestamp"] is None:
        return []

    rows = connection.execute(
        """
        SELECT timestamp, rank_type, rank_position, pid, ppid, stat, elapsed_seconds,
               cpu_percent, memory_percent, rss_kb, command
        FROM process_samples
        WHERE rank_type = ? AND timestamp = ?
        ORDER BY rank_position ASC
        LIMIT ?
        """,
        (rank_type, latest_row["timestamp"], limit),
    ).fetchall()
    return [row_to_dict(row) for row in rows]


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
        active_findings = merge_finding_rows(active_rows, 600)

        count_rows = connection.execute(
            """
            SELECT timestamp, severity, finding_key, message
            FROM findings
            WHERE timestamp >= ?
            ORDER BY timestamp DESC
            """,
            (now - 86400,),
        ).fetchall()
        merged_counts = merge_finding_rows(count_rows, 600)
        counts = {
            "total": len(merged_counts),
            "critical": sum(1 for finding in merged_counts if finding["severity"] == "CRITICAL"),
            "warn": sum(1 for finding in merged_counts if finding["severity"] == "WARN"),
        }
        top_processes = {
            "cpu": get_latest_process_samples(connection, "cpu"),
            "memory": get_latest_process_samples(connection, "memory"),
        }

    active_findings.sort(key=lambda item: (severity_rank(item["severity"]), item["timestamp"]), reverse=True)
    return {
        "status": overall_status(latest, active_findings),
        "generated_at": now,
        "latest": latest,
        "active_window_seconds": active_window_seconds,
        "active_findings": active_findings,
        "last_24h": counts,
        "top_processes": top_processes,
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


def get_findings(
    db_path: Path,
    since_seconds: int,
    limit: int,
    page: int = 1,
    merge_window_seconds: int = 600,
) -> dict[str, Any]:
    now = int(time.time())
    since = now - since_seconds
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT timestamp, severity, finding_key, message
            FROM findings
            WHERE timestamp >= ?
            ORDER BY timestamp DESC
            """,
            (since,),
        ).fetchall()
    findings = merge_finding_rows(rows, merge_window_seconds)
    findings.sort(key=lambda item: (item["last_timestamp"], severity_rank(item["severity"])), reverse=True)
    paged_findings, pagination = paginate_items(findings, page, limit)
    return {
        "generated_at": now,
        "since": since,
        "findings": paged_findings,
        "pagination": pagination,
        "merge_window_seconds": merge_window_seconds,
    }


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

    def do_POST(self) -> None:
        parsed_url = urlparse(self.path)
        if parsed_url.path == "/api/actions":
            self.handle_action()
            return
        self.send_json({"error": "接口不存在"}, HTTPStatus.NOT_FOUND)

    def handle_api(self, path: str, query: dict[str, list[str]]) -> None:
        try:
            if path == "/api/summary":
                payload = get_summary(self.db_path)
            elif path == "/api/actions":
                payload = {"actions": available_actions()}
            elif path == "/api/history":
                hours = parse_int(query, "hours", 24, 1, 24 * 90)
                limit = parse_int(query, "limit", 720, 1, 5000)
                payload = get_history(self.db_path, hours * 3600, limit)
            elif path == "/api/findings":
                hours = parse_int(query, "hours", 24, 1, 24 * 90)
                limit = parse_int(query, "limit", 20, 1, 100)
                page = parse_int(query, "page", 1, 1, 100000)
                merge_window = parse_int(query, "merge_window", 600, 0, 86400)
                payload = get_findings(self.db_path, hours * 3600, limit, page, merge_window)
            else:
                self.send_json({"error": "接口不存在"}, HTTPStatus.NOT_FOUND)
                return
        except sqlite3.Error as exc:
            self.send_json({"error": f"数据库错误：{exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        self.send_json(payload)

    def handle_action(self) -> None:
        content_type = self.headers.get("Content-Type", "")
        if "application/json" not in content_type:
            self.send_json({"error": "请求格式必须是 JSON"}, HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
            return

        content_length = int(self.headers.get("Content-Length", "0") or "0")
        if content_length <= 0 or content_length > 4096:
            self.send_json({"error": "请求内容长度不正确"}, HTTPStatus.BAD_REQUEST)
            return

        try:
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.send_json({"error": "请求 JSON 无法解析"}, HTTPStatus.BAD_REQUEST)
            return

        action_id = str(payload.get("action", ""))
        result = run_diagnostic_action(action_id)
        status = HTTPStatus.BAD_REQUEST if "error" in result and "output" not in result else HTTPStatus.OK
        self.send_json(result, status)

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
    db_path = Path(args.db or config.get("history_db", "/var/lib/ops-monitor/history.db"))

    DashboardHandler.db_path = db_path
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    print(f"运维仪表盘已监听 http://{args.host}:{args.port}")
    print(f"正在读取历史数据库：{db_path}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
