"""SQLite storage for HomeMonitor.

One connection per operation keeps threading simple; WAL mode plus a process
write lock avoids "database is locked" bursts from heartbeat/metric traffic.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from common.protocol import json_dumps

DEFAULT_SETTINGS: dict[str, int] = {
    "heartbeat_interval": 5,
    "metrics_interval": 5,
    "offline_after": 15,
    "retention_days": 7,
    "events_retention_days": 30,
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    hostname      TEXT NOT NULL DEFAULT '',
    os_name       TEXT NOT NULL DEFAULT 'Unknown',
    os_version    TEXT NOT NULL DEFAULT '',
    arch          TEXT NOT NULL DEFAULT '',
    model         TEXT NOT NULL DEFAULT '',
    category      TEXT NOT NULL DEFAULT 'other',
    agent_version TEXT NOT NULL DEFAULT '',
    approved      INTEGER NOT NULL DEFAULT 0,
    revoked       INTEGER NOT NULL DEFAULT 0,
    ip            TEXT,
    created_at    REAL NOT NULL,
    last_seen     REAL,
    last_heartbeat REAL
);

CREATE TABLE IF NOT EXISTS agents (
    device_id      TEXT PRIMARY KEY REFERENCES devices(id) ON DELETE CASCADE,
    token_hash     TEXT NOT NULL,
    registered_at  REAL NOT NULL,
    last_heartbeat REAL
);

CREATE TABLE IF NOT EXISTS device_network (
    device_id  TEXT PRIMARY KEY REFERENCES devices(id) ON DELETE CASCADE,
    ts         REAL NOT NULL,
    ssid       TEXT,
    signal_pct REAL,
    ip         TEXT,
    gateway    TEXT,
    dns        TEXT,
    interface  TEXT,
    link_mbps  REAL
);

CREATE TABLE IF NOT EXISTS metrics (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id        TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    ts               REAL NOT NULL,
    cpu_pct          REAL,
    cpu_cores        INTEGER,
    cpu_freq_mhz     REAL,
    cpu_temp_c       REAL,
    load1            REAL,
    load5            REAL,
    load15           REAL,
    ram_pct          REAL,
    ram_used_mb      REAL,
    ram_total_mb     REAL,
    swap_pct         REAL,
    gpu_pct          REAL,
    gpu_temp_c       REAL,
    gpu_name         TEXT,
    gpu_mem_used_mb  REAL,
    gpu_mem_total_mb REAL,
    disk_pct         REAL,
    disk_read_bps    REAL,
    disk_write_bps   REAL,
    net_up_bps       REAL,
    net_down_bps     REAL,
    net_rx_bytes     REAL,
    net_tx_bytes     REAL,
    battery_pct      REAL,
    battery_charging INTEGER,
    uptime_s         REAL,
    processes_json   TEXT,
    disks_json       TEXT
);
CREATE INDEX IF NOT EXISTS ix_metrics_device_ts ON metrics(device_id, ts);

CREATE TABLE IF NOT EXISTS network_stats (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id  TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    ts         REAL NOT NULL,
    up_bps     REAL,
    down_bps   REAL,
    rx_bytes   REAL,
    tx_bytes   REAL
);
CREATE INDEX IF NOT EXISTS ix_network_device_ts ON network_stats(device_id, ts);

CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id  TEXT REFERENCES devices(id) ON DELETE CASCADE,
    ts         REAL NOT NULL,
    kind       TEXT NOT NULL,
    detail     TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS ix_events_device_ts ON events(device_id, ts);

CREATE TABLE IF NOT EXISTS alerts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id    TEXT REFERENCES devices(id) ON DELETE CASCADE,
    ts           REAL NOT NULL,
    kind         TEXT NOT NULL DEFAULT 'system',
    severity     TEXT NOT NULL DEFAULT 'warning',
    title        TEXT NOT NULL,
    detail       TEXT NOT NULL DEFAULT '',
    acknowledged INTEGER NOT NULL DEFAULT 0,
    resolved_at  REAL
);
CREATE INDEX IF NOT EXISTS ix_alerts_ts ON alerts(ts);
CREATE INDEX IF NOT EXISTS ix_alerts_device ON alerts(device_id, resolved_at);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

METRIC_COLUMNS = (
    "ts",
    "cpu_pct",
    "cpu_cores",
    "cpu_freq_mhz",
    "cpu_temp_c",
    "load1",
    "load5",
    "load15",
    "ram_pct",
    "ram_used_mb",
    "ram_total_mb",
    "swap_pct",
    "gpu_pct",
    "gpu_temp_c",
    "gpu_name",
    "gpu_mem_used_mb",
    "gpu_mem_total_mb",
    "disk_pct",
    "disk_read_bps",
    "disk_write_bps",
    "net_up_bps",
    "net_down_bps",
    "net_rx_bytes",
    "net_tx_bytes",
    "battery_pct",
    "battery_charging",
    "uptime_s",
    "processes_json",
    "disks_json",
)


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._write_lock = threading.RLock()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.executescript(SCHEMA)
            conn.executemany(
                "INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)",
                [(key, str(value)) for key, value in DEFAULT_SETTINGS.items()],
            )
            conn.commit()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=10000")
        try:
            yield conn
        finally:
            conn.close()

    # ------------------------------------------------------------------ settings
    def get_settings(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
        stored = {row["key"]: row["value"] for row in rows}
        result: dict[str, int] = {}
        for key, default in DEFAULT_SETTINGS.items():
            try:
                result[key] = int(stored.get(key, default))
            except (TypeError, ValueError):
                result[key] = default
        return result

    def set_setting(self, key: str, value: Any) -> None:
        if key not in DEFAULT_SETTINGS:
            raise KeyError(key)
        with self._write_lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value)),
            )
            conn.commit()

    # ------------------------------------------------------------------ devices
    def register_device(
        self, info: dict[str, Any], token_hash: str, ip: str | None, now: float
    ) -> dict[str, Any]:
        with self._write_lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO devices
                  (id, name, hostname, os_name, os_version, arch, model, category,
                   agent_version, approved, revoked, ip, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  name=excluded.name,
                  hostname=excluded.hostname,
                  os_name=excluded.os_name,
                  os_version=excluded.os_version,
                  arch=excluded.arch,
                  model=excluded.model,
                  category=excluded.category,
                  agent_version=excluded.agent_version,
                  ip=excluded.ip,
                  approved=0,
                  revoked=0
                """,
                (
                    info["id"],
                    info["name"],
                    info["hostname"],
                    info["os"],
                    info["os_version"],
                    info["arch"],
                    info["model"],
                    info["category"],
                    info["agent_version"],
                    ip,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO agents(device_id, token_hash, registered_at)
                VALUES (?, ?, ?)
                ON CONFLICT(device_id) DO UPDATE SET
                  token_hash=excluded.token_hash,
                  registered_at=excluded.registered_at
                """,
                (info["id"], token_hash, now),
            )
            conn.execute(
                "INSERT INTO events(device_id, ts, kind, detail) VALUES (?, ?, ?, ?)",
                (info["id"], now, "pairing_requested", "Waiting for approval on the controller"),
            )
            conn.commit()
        return self.get_device(info["id"]) or {}

    def get_device(self, device_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM devices WHERE id=?", (device_id,)).fetchone()
            latest = conn.execute(
                "SELECT * FROM metrics WHERE device_id=? ORDER BY ts DESC, id DESC LIMIT 1",
                (device_id,),
            ).fetchone()
            network = conn.execute(
                "SELECT * FROM device_network WHERE device_id=?", (device_id,)
            ).fetchone()
        if row is None:
            return None
        return self._device_dict(
            row, latest, self.get_settings()["offline_after"], network=network
        )

    def device_auth(self, device_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT a.token_hash, d.approved, d.revoked
                FROM agents a JOIN devices d ON d.id = a.device_id
                WHERE a.device_id=?
                """,
                (device_id,),
            ).fetchone()
        return dict(row) if row else None

    def touch_heartbeat(
        self,
        device_id: str,
        now: float,
        ip: str | None,
        agent_version: str | None = None,
        network: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        with self._write_lock, self._connect() as conn:
            if agent_version:
                conn.execute(
                    "UPDATE devices SET last_seen=?, last_heartbeat=?, ip=?, agent_version=? WHERE id=?",
                    (now, now, ip, agent_version, device_id),
                )
            else:
                conn.execute(
                    "UPDATE devices SET last_seen=?, last_heartbeat=?, ip=? WHERE id=?",
                    (now, now, ip, device_id),
                )
            conn.execute(
                "UPDATE agents SET last_heartbeat=? WHERE device_id=?", (now, device_id)
            )
            if network:
                # Replace the whole row: switching to a tether or another
                # network must not retain the previous SSID/gateway.
                conn.execute(
                    """
                    INSERT INTO device_network
                      (device_id, ts, ssid, signal_pct, ip, gateway, dns, interface, link_mbps)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(device_id) DO UPDATE SET
                      ts=excluded.ts,
                      ssid=excluded.ssid,
                      signal_pct=excluded.signal_pct,
                      ip=excluded.ip,
                      gateway=excluded.gateway,
                      dns=excluded.dns,
                      interface=excluded.interface,
                      link_mbps=excluded.link_mbps
                    """,
                    (
                        device_id,
                        now,
                        network.get("ssid"),
                        network.get("signal_pct"),
                        network.get("ip"),
                        network.get("gateway"),
                        network.get("dns"),
                        network.get("interface"),
                        network.get("link_mbps"),
                    ),
                )
            conn.commit()
        return self.get_device(device_id)

    def ingest_metrics(self, device_id: str, metrics: dict[str, Any], now: float) -> None:
        disks = metrics.get("disks") or []
        disk_pct = metrics.get("disk_pct")
        if disk_pct is None and disks:
            values = [d["percent"] for d in disks if d.get("percent") is not None]
            disk_pct = max(values) if values else None

        values = {
            **metrics,
            "ts": now,
            "disk_pct": disk_pct,
            "processes_json": json_dumps(metrics.get("processes") or []),
            "disks_json": json_dumps(disks),
        }
        placeholders = ", ".join("?" for _ in METRIC_COLUMNS)
        columns = ", ".join(METRIC_COLUMNS)

        with self._write_lock, self._connect() as conn:
            conn.execute(
                f"INSERT INTO metrics(device_id, {columns}) VALUES (?, {placeholders})",
                (device_id, *[values.get(column) for column in METRIC_COLUMNS]),
            )
            conn.execute(
                """
                INSERT INTO network_stats(device_id, ts, up_bps, down_bps, rx_bytes, tx_bytes)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    device_id,
                    now,
                    metrics.get("net_up_bps"),
                    metrics.get("net_down_bps"),
                    metrics.get("net_rx_bytes"),
                    metrics.get("net_tx_bytes"),
                ),
            )
            conn.execute(
                "UPDATE devices SET last_seen=?, last_heartbeat=? WHERE id=?",
                (now, now, device_id),
            )
            conn.execute(
                "UPDATE agents SET last_heartbeat=? WHERE device_id=?", (now, device_id)
            )
            conn.commit()

    def set_approved(self, device_id: str) -> dict[str, Any] | None:
        now = time.time()
        with self._write_lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE devices SET approved=1, revoked=0 WHERE id=?", (device_id,)
            )
            if cur.rowcount:
                conn.execute(
                    "INSERT INTO events(device_id, ts, kind, detail) VALUES (?, ?, ?, ?)",
                    (device_id, now, "approved", "Device approved for monitoring"),
                )
            conn.commit()
        return self.get_device(device_id)

    def set_revoked(self, device_id: str) -> dict[str, Any] | None:
        now = time.time()
        with self._write_lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE devices SET approved=0, revoked=1 WHERE id=?", (device_id,)
            )
            if cur.rowcount:
                conn.execute(
                    "INSERT INTO events(device_id, ts, kind, detail) VALUES (?, ?, ?, ?)",
                    (device_id, now, "revoked", "Device access revoked"),
                )
                conn.execute(
                    "UPDATE alerts SET resolved_at=? "
                    "WHERE device_id=? AND resolved_at IS NULL",
                    (now, device_id),
                )
            conn.commit()
        return self.get_device(device_id)

    def delete_device(self, device_id: str) -> bool:
        with self._write_lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM devices WHERE id=?", (device_id,))
            conn.commit()
            return cur.rowcount > 0

    def list_devices(self, now: float | None = None) -> list[dict[str, Any]]:
        now = time.time() if now is None else now
        offline_after = self.get_settings()["offline_after"]
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM devices ORDER BY created_at ASC").fetchall()
            latest_rows = conn.execute(
                """
                SELECT m.* FROM metrics m
                JOIN (SELECT device_id, MAX(id) AS max_id FROM metrics GROUP BY device_id) x
                  ON x.max_id = m.id
                """
            ).fetchall()
            network_rows = conn.execute("SELECT * FROM device_network").fetchall()
        latest_by_device = {row["device_id"]: row for row in latest_rows}
        network_by_device = {row["device_id"]: row for row in network_rows}
        return [
            self._device_dict(
                row,
                latest_by_device.get(row["id"]),
                offline_after,
                now,
                network_by_device.get(row["id"]),
            )
            for row in rows
        ]

    def history(self, device_id: str, minutes: int, max_points: int = 240) -> list[dict[str, Any]]:
        since = time.time() - max(1, minutes) * 60
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT ts, cpu_pct, ram_pct, gpu_pct, gpu_temp_c, cpu_temp_c,
                       net_up_bps, net_down_bps, disk_pct, battery_pct, ram_used_mb
                FROM metrics
                WHERE device_id=? AND ts>=?
                ORDER BY ts DESC LIMIT 2000
                """,
                (device_id, since),
            ).fetchall()
        points = [dict(row) for row in reversed(rows)]
        if len(points) <= max_points:
            return points
        stride = len(points) / max_points
        sampled = [points[min(len(points) - 1, int(i * stride))] for i in range(max_points)]
        sampled[-1] = points[-1]
        return sampled

    def events(self, limit: int = 50, device_id: str | None = None) -> list[dict[str, Any]]:
        query = (
            "SELECT e.*, d.name AS device_name FROM events e "
            "LEFT JOIN devices d ON d.id=e.device_id "
        )
        params: list[Any] = []
        if device_id:
            query += "WHERE e.device_id=? "
            params.append(device_id)
        query += "ORDER BY e.ts DESC LIMIT ?"
        params.append(max(1, min(limit, 500)))
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def alerts(self, limit: int = 50, include_resolved: bool = True) -> list[dict[str, Any]]:
        query = (
            "SELECT a.*, d.name AS device_name FROM alerts a "
            "LEFT JOIN devices d ON d.id=a.device_id "
        )
        if not include_resolved:
            query += "WHERE a.resolved_at IS NULL "
        query += "ORDER BY a.resolved_at IS NOT NULL, a.ts DESC LIMIT ?"
        with self._connect() as conn:
            rows = conn.execute(query, (max(1, min(limit, 500)),)).fetchall()
        return [dict(row) for row in rows]

    def acknowledge_alert(self, alert_id: int) -> bool:
        with self._write_lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE alerts SET acknowledged=1 WHERE id=?", (alert_id,)
            )
            conn.commit()
            return cur.rowcount > 0

    def apply_status_transitions(
        self, previous: dict[str, str], now: float | None = None
    ) -> tuple[list[dict[str, Any]], dict[str, str]]:
        """Compare heartbeat-derived status to the last pass, record transitions."""
        now = time.time() if now is None else now
        offline_after = self.get_settings()["offline_after"]
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, name, approved, revoked, last_heartbeat FROM devices"
            ).fetchall()
        current: dict[str, str] = {}
        new_events: list[dict[str, Any]] = []
        for row in rows:
            device_id = row["id"]
            status = status_for(
                bool(row["approved"]), bool(row["revoked"]), row["last_heartbeat"], now, offline_after
            )
            current[device_id] = status
            prior = previous.get(device_id)
            if prior not in {"online", "offline"} or status == prior:
                continue
            if status == "offline":
                new_events.append(
                    {
                        "device_id": device_id,
                        "kind": "offline",
                        "detail": f"No heartbeat for more than {offline_after}s",
                        "severity": "warning",
                        "title": f"{row['name']} is offline",
                    }
                )
            elif status == "online" and prior == "offline":
                new_events.append(
                    {
                        "device_id": device_id,
                        "kind": "online",
                        "detail": "Heartbeat restored",
                        "severity": "info",
                        "title": f"{row['name']} is back online",
                    }
                )

        if new_events:
            with self._write_lock, self._connect() as conn:
                for event in new_events:
                    conn.execute(
                        "INSERT INTO events(device_id, ts, kind, detail) VALUES (?, ?, ?, ?)",
                        (event["device_id"], now, event["kind"], event["detail"]),
                    )
                    if event["kind"] == "offline":
                        conn.execute(
                            """
                            INSERT INTO alerts(device_id, ts, kind, severity, title, detail)
                            VALUES (?, ?, 'offline', ?, ?, ?)
                            """,
                            (
                                event["device_id"],
                                now,
                                event["severity"],
                                event["title"],
                                event["detail"],
                            ),
                        )
                    elif event["kind"] == "online":
                        conn.execute(
                            "UPDATE alerts SET resolved_at=? "
                            "WHERE device_id=? AND kind='offline' AND resolved_at IS NULL",
                            (now, event["device_id"]),
                        )
                conn.commit()
        return new_events, current

    def prune(self, now: float | None = None) -> dict[str, int]:
        now = time.time() if now is None else now
        settings = self.get_settings()
        metric_cutoff = now - settings["retention_days"] * 86400
        event_cutoff = now - settings["events_retention_days"] * 86400
        deleted = {"metrics": 0, "network_stats": 0, "events": 0, "alerts": 0}
        with self._write_lock, self._connect() as conn:
            deleted["metrics"] = conn.execute(
                "DELETE FROM metrics WHERE ts < ?", (metric_cutoff,)
            ).rowcount
            deleted["network_stats"] = conn.execute(
                "DELETE FROM network_stats WHERE ts < ?", (metric_cutoff,)
            ).rowcount
            deleted["events"] = conn.execute(
                "DELETE FROM events WHERE ts < ?", (event_cutoff,)
            ).rowcount
            deleted["alerts"] = conn.execute(
                "DELETE FROM alerts WHERE resolved_at IS NOT NULL AND resolved_at < ?",
                (event_cutoff,),
            ).rowcount
            conn.commit()
            if deleted["metrics"] > 5000:
                try:
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                except sqlite3.Error:
                    pass
        return deleted

    def stats(self) -> dict[str, Any]:
        with self._connect() as conn:
            device_count = conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0]
            online_rows = conn.execute(
                "SELECT approved, revoked, last_heartbeat FROM devices"
            ).fetchall()
            metric_count = conn.execute("SELECT COUNT(*) FROM metrics").fetchone()[0]
            oldest = conn.execute("SELECT MIN(ts) FROM metrics").fetchone()[0]
        offline_after = self.get_settings()["offline_after"]
        now = time.time()
        statuses = {
            status_for(
                bool(row["approved"]), bool(row["revoked"]), row["last_heartbeat"], now, offline_after
            )
            for row in online_rows
        }
        return {
            "db_path": str(self.path),
            "db_bytes": self.path.stat().st_size if self.path.exists() else 0,
            "device_count": device_count,
            "metric_rows": metric_count,
            "oldest_metric_ts": oldest,
            "online": sum(
                1
                for row in online_rows
                if status_for(
                    bool(row["approved"]),
                    bool(row["revoked"]),
                    row["last_heartbeat"],
                    now,
                    offline_after,
                )
                == "online"
            ),
            "has_offline": "offline" in statuses,
        }

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _device_dict(
        row: sqlite3.Row,
        latest: sqlite3.Row | None,
        offline_after: int,
        now: float | None = None,
        network: sqlite3.Row | None = None,
    ) -> dict[str, Any]:
        now = time.time() if now is None else now
        status = status_for(
            bool(row["approved"]), bool(row["revoked"]), row["last_heartbeat"], now, offline_after
        )
        network_info = None
        if network is not None:
            network_info = {
                key: network[key]
                for key in ("ssid", "signal_pct", "ip", "gateway", "dns", "interface", "link_mbps")
                if network[key] is not None
            } or None
        device = {
            "id": row["id"],
            "name": row["name"],
            "hostname": row["hostname"],
            "os_name": row["os_name"],
            "os_version": row["os_version"],
            "arch": row["arch"],
            "model": row["model"],
            "category": row["category"],
            "agent_version": row["agent_version"],
            "approved": bool(row["approved"]),
            "revoked": bool(row["revoked"]),
            "ip": row["ip"],
            "created_at": row["created_at"],
            "last_seen": row["last_seen"],
            "last_heartbeat": row["last_heartbeat"],
            "status": status,
            "latest": metric_to_dict(latest),
            "network": network_info,
        }
        return device


def status_for(
    approved: bool,
    revoked: bool,
    last_heartbeat: float | None,
    now: float,
    offline_after: int,
) -> str:
    if revoked:
        return "revoked"
    if not approved:
        return "pending"
    if last_heartbeat and now - last_heartbeat <= offline_after:
        return "online"
    return "offline"


def metric_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    metric = dict(row)
    metric.pop("device_id", None)
    for key, fallback in (("processes_json", []), ("disks_json", [])):
        raw = metric.pop(key, None)
        try:
            metric[key.removesuffix("_json")] = json.loads(raw) if raw else fallback
        except (TypeError, ValueError):
            metric[key.removesuffix("_json")] = fallback
    return metric
