#!/usr/bin/env python3
"""Small Linux ops monitor for load, temperature, disk, memory, and stuck jobs."""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import smtplib
import ssl
import sqlite3
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Any


DEFAULT_CONFIG: dict[str, Any] = {
    "interval_seconds": 15,
    "dry_run": True,
    "log_file": "/var/log/ops-monitor/monitor.log",
    "state_file": "/var/lib/ops-monitor/state.json",
    "history_db": "/var/lib/ops-monitor/history.db",
    "history_retention_days": 30,
    "finding_dedup_seconds": 600,
    "alerts": {
        "cooldown_seconds": 300,
        "webhook_url": "",
        "email": {
            "enabled": False,
            "security": "none",
            "smtp_timeout_seconds": 15,
            "username": "",
            "password": "",
            "password_env": "",
        },
    },
    "load": {"enabled": True, "warn_1m_per_cpu": 1.5, "critical_1m_per_cpu": 2.5},
    "temperature": {"enabled": True, "warn_celsius": 75, "critical_celsius": 85},
    "disk": {"enabled": True, "warn_percent": 85, "critical_percent": 95, "paths": ["/"]},
    "memory": {"enabled": True, "warn_percent": 85, "critical_percent": 95},
    "processes": [],
}

LOG = logging.getLogger("ops-monitor")


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    ppid: int
    stat: str
    elapsed_seconds: int
    cpu_percent: float
    memory_percent: float
    rss_kb: int
    command: str


@dataclass(frozen=True)
class Finding:
    severity: str
    key: str
    message: str


@dataclass(frozen=True)
class MetricsSnapshot:
    timestamp: int
    load_1m: float | None
    load_per_cpu: float | None
    cpu_count: int
    temperature_celsius: float | None
    memory_percent: float | None
    max_disk_percent: float | None
    process_count: int
    watched_process_count: int
    memory_total_bytes: int | None = None
    memory_used_bytes: int | None = None
    swap_total_bytes: int | None = None
    swap_used_bytes: int | None = None
    disk_total_bytes: int | None = None
    disk_used_bytes: int | None = None


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as config_file:
        user_config = json.load(config_file)
    return deep_merge(DEFAULT_CONFIG, user_config)


def setup_logging(log_file: str | None, verbose: bool) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_path, encoding="utf-8"))

    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
    )


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"alerts": {}, "cpu_hot_since": {}}
    try:
        with path.open("r", encoding="utf-8") as state_file:
            state = json.load(state_file)
    except (OSError, json.JSONDecodeError) as exc:
        LOG.warning("读取状态文件失败 %s: %s", path, exc)
        return {"alerts": {}, "cpu_hot_since": {}}
    state.setdefault("alerts", {})
    state.setdefault("cpu_hot_since", {})
    return state


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as state_file:
        json.dump(state, state_file, indent=2, sort_keys=True)
    temp_path.replace(path)


def collect_processes() -> list[ProcessInfo]:
    command = ["ps", "-eo", "pid=,ppid=,stat=,etimes=,pcpu=,pmem=,rss=,args="]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    processes: list[ProcessInfo] = []

    for line in result.stdout.splitlines():
        parts = line.strip().split(None, 7)
        if len(parts) < 8:
            continue
        pid, ppid, stat, elapsed, cpu_percent, memory_percent, rss_kb, process_command = parts
        try:
            processes.append(
                ProcessInfo(
                    pid=int(pid),
                    ppid=int(ppid),
                    stat=stat,
                    elapsed_seconds=int(elapsed),
                    cpu_percent=float(cpu_percent),
                    memory_percent=float(memory_percent),
                    rss_kb=int(rss_kb),
                    command=process_command,
                )
            )
        except ValueError:
            LOG.debug("跳过无法解析的进程行: %s", line)

    return processes


def ensure_history_db(db_path: Path) -> None:
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
        connection.execute("CREATE INDEX IF NOT EXISTS idx_findings_timestamp ON findings(timestamp)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_findings_key ON findings(finding_key)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_process_samples_timestamp ON process_samples(timestamp)")


def ensure_columns(connection: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    if table != "metric_samples":
        raise ValueError(f"unexpected table for schema migration: {table}")
    existing_columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
    for column_name, column_type in columns.items():
        if column_name not in existing_columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column_name} {column_type}")


def prune_history(db_path: Path, retention_days: int, now: int) -> None:
    if retention_days <= 0:
        return
    cutoff = now - (retention_days * 86400)
    with sqlite3.connect(db_path) as connection:
        connection.execute("DELETE FROM metric_samples WHERE timestamp < ?", (cutoff,))
        connection.execute("DELETE FROM findings WHERE timestamp < ?", (cutoff,))
        connection.execute("DELETE FROM process_samples WHERE timestamp < ?", (cutoff,))


def top_process_rows(timestamp: int, processes: list[ProcessInfo], limit: int = 8) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    rank_specs = [
        ("cpu", sorted(processes, key=lambda process: process.cpu_percent, reverse=True)),
        ("memory", sorted(processes, key=lambda process: process.memory_percent, reverse=True)),
    ]
    for rank_type, ranked_processes in rank_specs:
        for index, process in enumerate(ranked_processes[:limit], start=1):
            rows.append(
                (
                    timestamp,
                    rank_type,
                    index,
                    process.pid,
                    process.ppid,
                    process.stat,
                    process.elapsed_seconds,
                    process.cpu_percent,
                    process.memory_percent,
                    process.rss_kb,
                    process.command,
                )
            )
    return rows


def save_history_sample(
    db_path: Path,
    snapshot: MetricsSnapshot,
    findings: list[Finding],
    processes: list[ProcessInfo] | None = None,
    finding_dedup_seconds: int = 600,
) -> None:
    ensure_history_db(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO metric_samples (
                timestamp,
                load_1m,
                load_per_cpu,
                cpu_count,
                temperature_celsius,
                memory_percent,
                max_disk_percent,
                memory_total_bytes,
                memory_used_bytes,
                swap_total_bytes,
                swap_used_bytes,
                disk_total_bytes,
                disk_used_bytes,
                process_count,
                watched_process_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot.timestamp,
                snapshot.load_1m,
                snapshot.load_per_cpu,
                snapshot.cpu_count,
                snapshot.temperature_celsius,
                snapshot.memory_percent,
                snapshot.max_disk_percent,
                snapshot.memory_total_bytes,
                snapshot.memory_used_bytes,
                snapshot.swap_total_bytes,
                snapshot.swap_used_bytes,
                snapshot.disk_total_bytes,
                snapshot.disk_used_bytes,
                snapshot.process_count,
                snapshot.watched_process_count,
            ),
        )
        filtered_findings: list[Finding] = []
        for finding in findings:
            if finding_dedup_seconds > 0:
                duplicate_row = connection.execute(
                    """
                    SELECT 1
                    FROM findings
                    WHERE timestamp >= ?
                      AND timestamp <= ?
                      AND severity = ?
                      AND finding_key = ?
                    LIMIT 1
                    """,
                    (
                        snapshot.timestamp - finding_dedup_seconds,
                        snapshot.timestamp,
                        finding.severity,
                        finding.key,
                    ),
                ).fetchone()
                if duplicate_row:
                    continue
            filtered_findings.append(finding)

        connection.executemany(
            """
            INSERT INTO findings (timestamp, severity, finding_key, message)
            VALUES (?, ?, ?, ?)
            """,
            [(snapshot.timestamp, finding.severity, finding.key, finding.message) for finding in filtered_findings],
        )
        if processes:
            connection.executemany(
                """
                INSERT INTO process_samples (
                    timestamp,
                    rank_type,
                    rank_position,
                    pid,
                    ppid,
                    stat,
                    elapsed_seconds,
                    cpu_percent,
                    memory_percent,
                    rss_kb,
                    command
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                top_process_rows(snapshot.timestamp, processes),
            )


def get_load_average() -> tuple[float, float, float]:
    return os.getloadavg()


def get_cpu_count() -> int:
    return os.cpu_count() or 1


def read_meminfo() -> dict[str, int] | None:
    meminfo: dict[str, int] = {}
    try:
        with Path("/proc/meminfo").open("r", encoding="utf-8") as meminfo_file:
            for line in meminfo_file:
                key, value = line.split(":", 1)
                meminfo[key] = int(value.strip().split()[0])
    except (OSError, ValueError):
        return None
    return meminfo


def read_memory_stats() -> dict[str, int | float | None]:
    meminfo = read_meminfo()
    if not meminfo:
        return {
            "memory_percent": None,
            "memory_total_bytes": None,
            "memory_used_bytes": None,
            "swap_total_bytes": None,
            "swap_used_bytes": None,
        }
    total = meminfo.get("MemTotal")
    available = meminfo.get("MemAvailable")
    if total and available is not None:
        memory_used_kb = total - available
        memory_percent = (memory_used_kb / total) * 100
    else:
        memory_used_kb = None
        memory_percent = None

    swap_total = meminfo.get("SwapTotal")
    swap_free = meminfo.get("SwapFree")
    swap_used_kb = None if swap_total is None or swap_free is None else max(0, swap_total - swap_free)
    return {
        "memory_percent": memory_percent,
        "memory_total_bytes": total * 1024 if total else None,
        "memory_used_bytes": memory_used_kb * 1024 if memory_used_kb is not None else None,
        "swap_total_bytes": swap_total * 1024 if swap_total is not None else None,
        "swap_used_bytes": swap_used_kb * 1024 if swap_used_kb is not None else None,
    }


def read_memory_percent() -> float | None:
    memory_percent = read_memory_stats()["memory_percent"]
    return float(memory_percent) if memory_percent is not None else None


def read_disk_stats(disk_path: str) -> dict[str, int | float] | None:
    try:
        usage = os.statvfs(disk_path)
    except OSError:
        return None

    total_blocks = usage.f_blocks
    available_blocks = usage.f_bavail
    if total_blocks <= 0:
        return None
    total_bytes = total_blocks * usage.f_frsize
    used_bytes = (total_blocks - available_blocks) * usage.f_frsize
    return {
        "percent": (used_bytes / total_bytes) * 100,
        "total_bytes": total_bytes,
        "used_bytes": used_bytes,
    }


def read_disk_percent(disk_path: str) -> float | None:
    disk_stats = read_disk_stats(disk_path)
    return float(disk_stats["percent"]) if disk_stats else None


def read_temperature_celsius() -> float | None:
    temperatures: list[float] = []
    for sensor_input in Path("/sys/class/thermal").glob("thermal_zone*/temp"):
        try:
            raw_value = int(sensor_input.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            continue
        temperatures.append(raw_value / 1000 if raw_value > 1000 else float(raw_value))

    if temperatures:
        return max(temperatures)

    try:
        result = subprocess.run(["sensors", "-u"], check=False, capture_output=True, text=True)
    except OSError:
        return None

    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("temp") and "_input:" in stripped:
            try:
                temperatures.append(float(stripped.rsplit(":", 1)[1].strip()))
            except ValueError:
                continue

    return max(temperatures) if temperatures else None


def check_threshold(
    value: float,
    warn_value: float,
    critical_value: float,
    key: str,
    label: str,
    unit: str = "",
) -> Finding | None:
    suffix = f"{unit}" if unit else ""
    if value >= critical_value:
        return Finding("CRITICAL", key, f"{label}当前为 {value:.1f}{suffix}，严重阈值为 {critical_value:.1f}{suffix}")
    if value >= warn_value:
        return Finding("WARN", key, f"{label}当前为 {value:.1f}{suffix}，预警阈值为 {warn_value:.1f}{suffix}")
    return None


def check_load(config: dict[str, Any]) -> list[Finding]:
    load_config = config["load"]
    if not load_config.get("enabled", True):
        return []

    load_1m, _, _ = get_load_average()
    cpu_count = get_cpu_count()
    load_per_cpu = load_1m / cpu_count
    finding = check_threshold(
        load_per_cpu,
        float(load_config["warn_1m_per_cpu"]),
        float(load_config["critical_1m_per_cpu"]),
        "load",
        f"1分钟平均负载/CPU（{load_1m:.2f}/{cpu_count}核）",
    )
    return [finding] if finding else []


def check_memory(config: dict[str, Any]) -> list[Finding]:
    memory_config = config["memory"]
    if not memory_config.get("enabled", True):
        return []

    memory_percent = read_memory_percent()
    if memory_percent is None:
        return [Finding("WARN", "memory:unknown", "无法从 /proc/meminfo 读取内存使用率")]

    finding = check_threshold(
        memory_percent,
        float(memory_config["warn_percent"]),
        float(memory_config["critical_percent"]),
        "memory",
        "内存使用率",
        "%",
    )
    return [finding] if finding else []


def check_temperature(config: dict[str, Any]) -> list[Finding]:
    temperature_config = config["temperature"]
    if not temperature_config.get("enabled", True):
        return []

    temperature = read_temperature_celsius()
    if temperature is None:
        return [Finding("WARN", "temperature:unknown", "未找到温度传感器数据")]

    finding = check_threshold(
        temperature,
        float(temperature_config["warn_celsius"]),
        float(temperature_config["critical_celsius"]),
        "temperature",
        "系统温度",
        "C",
    )
    return [finding] if finding else []


def check_disk(config: dict[str, Any]) -> list[Finding]:
    disk_config = config["disk"]
    if not disk_config.get("enabled", True):
        return []

    findings: list[Finding] = []
    for disk_path in disk_config.get("paths", ["/"]):
        used_percent = read_disk_percent(str(disk_path))
        if used_percent is None:
            findings.append(Finding("WARN", f"disk:{disk_path}", f"无法读取磁盘路径 {disk_path}"))
            continue
        finding = check_threshold(
            used_percent,
            float(disk_config["warn_percent"]),
            float(disk_config["critical_percent"]),
            f"disk:{disk_path}",
            f"{disk_path} 磁盘使用率",
            "%",
        )
        if finding:
            findings.append(finding)

    return findings


def count_watched_processes(processes: list[ProcessInfo], rules: list[dict[str, Any]]) -> int:
    watched_pids: set[int] = set()
    for process in processes:
        for rule in rules:
            match_terms = [str(term) for term in rule.get("match", [])]
            if process_matches(process, match_terms):
                watched_pids.add(process.pid)
    return len(watched_pids)


def process_matches(process: ProcessInfo, match_terms: list[str]) -> bool:
    if not match_terms:
        return False
    command = process.command.lower()
    return all(term.lower() in command for term in match_terms)


def terminate_process(process: ProcessInfo, kill_after_seconds: int, dry_run: bool) -> str:
    if dry_run:
        return f"演练模式：将终止 PID {process.pid}（{process.command}）"

    os.kill(process.pid, signal.SIGTERM)
    deadline = time.monotonic() + kill_after_seconds
    while time.monotonic() < deadline:
        try:
            os.kill(process.pid, 0)
        except ProcessLookupError:
            return f"已用 SIGTERM 终止 PID {process.pid}"
        time.sleep(1)

    os.kill(process.pid, signal.SIGKILL)
    return f"SIGTERM 等待超时后已用 SIGKILL 强制结束 PID {process.pid}"


def check_processes(
    config: dict[str, Any],
    state: dict[str, Any],
    now: float,
    processes: list[ProcessInfo] | None = None,
) -> list[Finding]:
    rules = config.get("processes", [])
    if not rules:
        return []

    findings: list[Finding] = []
    cpu_hot_since = state.setdefault("cpu_hot_since", {})
    seen_hot_keys: set[str] = set()

    process_list = processes if processes is not None else collect_processes()
    for process in process_list:
        if process.pid == os.getpid():
            continue

        for rule in rules:
            match_terms = [str(term) for term in rule.get("match", [])]
            if not process_matches(process, match_terms):
                continue

            rule_name = str(rule.get("name") or ",".join(match_terms))
            action = str(rule.get("action", "alert")).lower()
            process_key = f"{rule_name}:{process.pid}"
            reasons: list[str] = []

            max_runtime = int(rule.get("max_runtime_seconds", 0) or 0)
            if max_runtime and process.elapsed_seconds >= max_runtime:
                reasons.append(f"运行时间 {process.elapsed_seconds}秒 >= {max_runtime}秒")

            max_cpu = float(rule.get("max_cpu_percent", 0) or 0)
            cpu_grace = int(rule.get("cpu_grace_seconds", 0) or 0)
            if max_cpu and process.cpu_percent >= max_cpu:
                seen_hot_keys.add(process_key)
                hot_since = float(cpu_hot_since.setdefault(process_key, now))
                if now - hot_since >= cpu_grace:
                    reasons.append(f"CPU {process.cpu_percent:.1f}% >= {max_cpu:.1f}%，已持续 {int(now - hot_since)}秒")
            else:
                cpu_hot_since.pop(process_key, None)

            if "D" in process.stat:
                reasons.append("进程处于不可中断睡眠状态")

            if not reasons:
                continue

            message = (
                f"进程规则“{rule_name}”命中 PID {process.pid}："
                f"{'；'.join(reasons)}；命令={process.command}"
            )

            if action in {"terminate", "kill"}:
                kill_after_seconds = int(rule.get("kill_after_seconds", 30))
                try:
                    cleanup_result = terminate_process(process, kill_after_seconds, bool(config.get("dry_run", True)))
                    message = f"{message}；清理结果={cleanup_result}"
                except ProcessLookupError:
                    message = f"{message}；清理结果=进程已退出"
                except PermissionError as exc:
                    message = f"{message}；清理结果=权限不足：{exc}"
                except OSError as exc:
                    message = f"{message}；清理结果=失败：{exc}"

            findings.append(Finding("CRITICAL", f"process:{process_key}", message))

    for process_key in list(cpu_hot_since):
        if process_key not in seen_hot_keys:
            cpu_hot_since.pop(process_key, None)

    return findings


def collect_metrics_snapshot(config: dict[str, Any], processes: list[ProcessInfo], now: int) -> MetricsSnapshot:
    cpu_count = get_cpu_count()
    load_1m: float | None
    load_per_cpu: float | None
    try:
        load_1m = get_load_average()[0]
        load_per_cpu = load_1m / cpu_count
    except OSError:
        load_1m = None
        load_per_cpu = None

    memory_stats = read_memory_stats()
    disk_paths = config.get("disk", {}).get("paths", ["/"])
    disk_stats = [read_disk_stats(str(disk_path)) for disk_path in disk_paths]
    readable_disk_stats = [stats for stats in disk_stats if stats is not None]
    max_disk_stats = max(readable_disk_stats, key=lambda stats: float(stats["percent"])) if readable_disk_stats else None

    return MetricsSnapshot(
        timestamp=now,
        load_1m=load_1m,
        load_per_cpu=load_per_cpu,
        cpu_count=cpu_count,
        temperature_celsius=read_temperature_celsius(),
        memory_percent=float(memory_stats["memory_percent"]) if memory_stats["memory_percent"] is not None else None,
        max_disk_percent=float(max_disk_stats["percent"]) if max_disk_stats else None,
        memory_total_bytes=int(memory_stats["memory_total_bytes"]) if memory_stats["memory_total_bytes"] is not None else None,
        memory_used_bytes=int(memory_stats["memory_used_bytes"]) if memory_stats["memory_used_bytes"] is not None else None,
        swap_total_bytes=int(memory_stats["swap_total_bytes"]) if memory_stats["swap_total_bytes"] is not None else None,
        swap_used_bytes=int(memory_stats["swap_used_bytes"]) if memory_stats["swap_used_bytes"] is not None else None,
        disk_total_bytes=int(max_disk_stats["total_bytes"]) if max_disk_stats else None,
        disk_used_bytes=int(max_disk_stats["used_bytes"]) if max_disk_stats else None,
        process_count=len(processes),
        watched_process_count=count_watched_processes(processes, config.get("processes", [])),
    )


def should_alert(finding: Finding, state: dict[str, Any], cooldown_seconds: int, now: float) -> bool:
    alerts = state.setdefault("alerts", {})
    last_alert = float(alerts.get(finding.key, 0))
    if now - last_alert < cooldown_seconds:
        return False
    alerts[finding.key] = now
    return True


def send_webhook(webhook_url: str, finding: Finding) -> None:
    payload = json.dumps(
        {"severity": finding.severity, "key": finding.key, "message": finding.message},
        ensure_ascii=True,
    ).encode("utf-8")
    request = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        response.read()


def send_email(email_config: dict[str, Any], finding: Finding) -> None:
    recipients = email_config.get("to") or []
    if not recipients:
        return

    message = EmailMessage()
    message["Subject"] = f"[{finding.severity}] ops-monitor {finding.key}"
    message["From"] = email_config.get("from", "ops-monitor@localhost")
    message["To"] = ", ".join(recipients)
    message.set_content(finding.message)

    smtp_host = email_config.get("smtp_host", "127.0.0.1")
    smtp_port = int(email_config.get("smtp_port", 25))
    smtp_timeout = int(email_config.get("smtp_timeout_seconds", 15))
    smtp_security = str(email_config.get("security", "none")).lower()
    smtp_username = str(email_config.get("username") or email_config.get("smtp_username") or "")
    smtp_password = str(email_config.get("password") or email_config.get("smtp_password") or "")
    password_env = str(email_config.get("password_env") or "")
    if not smtp_password and password_env:
        smtp_password = os.environ.get(password_env, "")

    if smtp_security not in {"none", "starttls", "ssl"}:
        raise ValueError("email.security must be one of: none, starttls, ssl")

    context = ssl.create_default_context()
    smtp_class = smtplib.SMTP_SSL if smtp_security == "ssl" else smtplib.SMTP
    smtp_kwargs: dict[str, Any] = {"timeout": smtp_timeout}
    if smtp_security == "ssl":
        smtp_kwargs["context"] = context

    with smtp_class(smtp_host, smtp_port, **smtp_kwargs) as smtp:
        if smtp_security == "starttls":
            smtp.starttls(context=context)
        if smtp_username:
            smtp.login(smtp_username, smtp_password)
        smtp.send_message(message)


def emit_alert(finding: Finding, config: dict[str, Any]) -> None:
    LOG.warning("[%s] %s", finding.severity, finding.message)
    alerts_config = config.get("alerts", {})

    webhook_url = str(alerts_config.get("webhook_url") or "")
    if webhook_url:
        try:
            send_webhook(webhook_url, finding)
        except OSError as exc:
            LOG.error("发送 Webhook 告警失败: %s", exc)

    email_config = alerts_config.get("email", {})
    if email_config.get("enabled"):
        try:
            send_email(email_config, finding)
        except (OSError, smtplib.SMTPException) as exc:
            LOG.error("发送邮件告警失败: %s", exc)


def run_checks(
    config: dict[str, Any],
    state: dict[str, Any],
    processes: list[ProcessInfo] | None = None,
) -> list[Finding]:
    now = time.time()
    process_list = processes if processes is not None else collect_processes()
    findings: list[Finding] = []
    findings.extend(check_load(config))
    findings.extend(check_temperature(config))
    findings.extend(check_memory(config))
    findings.extend(check_disk(config))
    findings.extend(check_processes(config, state, now, process_list))
    return findings


def run_once(config: dict[str, Any], state: dict[str, Any]) -> int:
    now = time.time()
    now_int = int(now)
    cooldown_seconds = int(config.get("alerts", {}).get("cooldown_seconds", 300))
    processes = collect_processes()
    findings = run_checks(config, state, processes)
    history_db = str(config.get("history_db") or "")
    if history_db:
        db_path = Path(history_db)
        snapshot = collect_metrics_snapshot(config, processes, now_int)
        save_history_sample(
            db_path,
            snapshot,
            findings,
            processes,
            int(config.get("finding_dedup_seconds", 600)),
        )
        prune_history(db_path, int(config.get("history_retention_days", 30)), now_int)

    for finding in findings:
        if should_alert(finding, state, cooldown_seconds, now):
            emit_alert(finding, config)
        else:
            LOG.debug("suppressed alert during cooldown: %s", finding.key)

    if not findings:
        LOG.info("ops monitor check completed without findings")
        return 0

    return 2 if any(finding.severity == "CRITICAL" for finding in findings) else 1


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Monitor and clean up stuck system jobs.")
    parser.add_argument("-c", "--config", default="ops_monitor/config.example.json", help="JSON config path")
    parser.add_argument("--once", action="store_true", help="run a single check and exit")
    parser.add_argument("--dry-run", action="store_true", help="override config and avoid terminating processes")
    parser.add_argument("--no-dry-run", action="store_true", help="allow configured cleanup actions")
    parser.add_argument("-v", "--verbose", action="store_true", help="enable debug logging")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    config = load_config(Path(args.config))

    if args.dry_run:
        config["dry_run"] = True
    if args.no_dry_run:
        config["dry_run"] = False

    setup_logging(config.get("log_file"), args.verbose)
    state_path = Path(config.get("state_file", "/var/lib/ops-monitor/state.json"))
    state = load_state(state_path)

    LOG.info("starting ops monitor: dry_run=%s once=%s", config.get("dry_run", True), args.once)
    if args.once:
        exit_code = run_once(config, state)
        save_state(state_path, state)
        return exit_code

    interval_seconds = int(config.get("interval_seconds", 60))
    while True:
        try:
            run_once(config, state)
            save_state(state_path, state)
        except Exception:
            LOG.exception("监控循环执行失败")
        time.sleep(interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
