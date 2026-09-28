"""CarrotPilot parameter synchronizer.

- Syncs settings catalog and current values from Carrot server (port 7000) or carrot_settings.json to Cloudflare Worker.
- Polls Cloudflare Worker for pending parameter changes requested by Home Assistant.
- Applies requested parameter changes locally via http://127.0.0.1:7000/api/param_set (without bypassing server validation).
- Acknowledges applied parameter changes back to Cloudflare Worker.
"""
from __future__ import annotations
from contextlib import contextmanager
import json
import logging
import math
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
LOCAL_SERVER_URL = "http://127.0.0.1:7000"


def _http_request(url: str, data: dict | None = None, headers: dict | None = None, timeout: float = 10.0, verbose: bool = True) -> dict | None:
    req_headers = {"User-Agent": "CarrotHA/0.3.0", "Accept": "application/json"}
    if headers:
        req_headers.update(headers)

    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        req_headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=body, headers=req_headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if verbose:
            print(f"[param_sync] HTTP {exc.code} for {url}: {exc.reason}", flush=True)
        return None
    except Exception as exc:
        if verbose:
            print(f"[param_sync] Request error for {url}: {exc}", flush=True)
        return None


def fetch_local_settings_snapshot() -> dict | None:
    """Fetch catalog and current values from local carrot server or directly from file."""
    # 1. Try local carrot_server on port 7000 (silent on failure to avoid spam)
    try:
        res = _http_request(f"{LOCAL_SERVER_URL}/api/settings/snapshot", timeout=4.0, verbose=False)
        if res and res.get("ok"):
            print("[param_sync] loaded settings snapshot from local carrot_server (:7000)", flush=True)
            return res
    except Exception:
        pass

    # 2. Fallback to direct carrot_settings.json reading if port 7000 is down or not responding
    candidate_paths = [
        Path("/data/openpilot/openpilot/selfdrive/carrot_settings.json"),
        Path("/data/openpilot/selfdrive/carrot_settings.json"),
        Path("/data/carrot/carrot_settings.json"),
        Path(__file__).resolve().parent.parent / "openpilot" / "selfdrive" / "carrot_settings.json",
    ]
    settings_file = None
    for p in candidate_paths:
        if p.exists():
            settings_file = p
            break

    if settings_file:
        try:
            data = json.loads(settings_file.read_text(encoding="utf-8"))
            params_list = data.get("params", [])
            values = {}

            # Read current values directly via openpilot Params
            try:
                from openpilot.common.params import Params
                p = Params()
                for item in params_list:
                    name = item.get("name")
                    if name:
                        raw = p.get(name)
                        if raw is not None:
                            val_str = raw.decode("utf-8", errors="ignore").strip()
                            try:
                                values[name] = float(val_str) if "." in val_str else int(val_str)
                            except ValueError:
                                values[name] = val_str
                        else:
                            values[name] = item.get("default", 0)
            except Exception as e:
                for item in params_list:
                    if item.get("name"):
                        values[item["name"]] = item.get("default", 0)

            print(f"[param_sync] loaded {len(values)} settings from {settings_file}", flush=True)
            return {
                "ok": True,
                "settings": {
                    "categories": data.get("menu", []),
                    "params": params_list,
                },
                "values": values
            }
        except Exception as e:
            print(f"[param_sync] fallback read error from {settings_file}: {e}", flush=True)

    print("[param_sync] WARNING: could not load settings snapshot from :7000 or file", flush=True)
    return None


def apply_local_param(name: str, value: any) -> dict | None:
    """Use the validated server API and read back the actual stored value."""
    snapshot = _http_request(f"{LOCAL_SERVER_URL}/api/settings/snapshot", timeout=4.0, verbose=False)
    if not snapshot or not snapshot.get("ok"):
        return None
    catalog = snapshot.get("settings", {})
    items = [item for group in catalog.get("items_by_group", {}).values() for item in group]
    definition = next((item for item in items if item.get("name") == name), None)
    if definition is None:
        return None
    try:
        numeric = float(value)
        if not math.isfinite(numeric) or not float(definition["min"]) <= numeric <= float(definition["max"]):
            return None
    except (TypeError, ValueError, KeyError):
        return None
    res = _http_request(
        f"{LOCAL_SERVER_URL}/api/param_set",
        data={"name": name, "value": value, "source": "ha"},
        timeout=4.0, verbose=False,
    )
    if not res or not res.get("ok"):
        return None
    actual = _http_request(
        f"{LOCAL_SERVER_URL}/api/params_bulk?names={urllib.parse.quote(name)}",
        timeout=4.0, verbose=False,
    )
    if actual and actual.get("ok") and name in actual.get("values", {}):
        return {"value": actual["values"][name]}
    return None


class ProcessedQueueStore:
    """Persistent SQLite store for processed parameter change requests to guarantee idempotency."""

    def __init__(self, path: Path | str):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS processed_queue (
                    queue_id INTEGER PRIMARY KEY,
                    device_id TEXT NOT NULL,
                    param_name TEXT NOT NULL,
                    requested_val TEXT NOT NULL,
                    actual_val TEXT NOT NULL,
                    status TEXT NOT NULL,
                    processed_at REAL NOT NULL,
                    acked INTEGER NOT NULL DEFAULT 0
                )
            """)
        self.prune()

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=20)
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, queue_id: int) -> dict | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT queue_id, param_name, actual_val, status, acked FROM processed_queue WHERE queue_id = ?",
                (queue_id,)
            ).fetchone()
            if row:
                return {
                    "queue_id": row[0],
                    "param_name": row[1],
                    "actual_val": row[2],
                    "status": row[3],
                    "acked": bool(row[4])
                }
            return None

    def record(self, queue_id: int, device_id: str, param_name: str, requested_val: any, actual_val: any, status: str):
        now = time.time()
        with self.connect() as db:
            db.execute("""
                INSERT INTO processed_queue (queue_id, device_id, param_name, requested_val, actual_val, status, processed_at, acked)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0)
                ON CONFLICT(queue_id) DO UPDATE SET
                    actual_val = excluded.actual_val,
                    status = excluded.status,
                    processed_at = excluded.processed_at
            """, (queue_id, device_id, param_name, str(requested_val), str(actual_val), status, now))
        self.prune()

    def mark_acked(self, queue_ids: list[int]):
        if not queue_ids:
            return
        with self.connect() as db:
            placeholders = ",".join("?" for _ in queue_ids)
            db.execute(f"UPDATE processed_queue SET acked = 1 WHERE queue_id IN ({placeholders})", queue_ids)

    def prune(self, max_records: int = 500, max_age_days: int = 30):
        """Keep database tiny by pruning old/excess processed queue records."""
        cutoff = time.time() - (max_age_days * 86400)
        try:
            with self.connect() as db:
                db.execute("DELETE FROM processed_queue WHERE processed_at < ?", (cutoff,))
                db.execute("""
                    DELETE FROM processed_queue WHERE queue_id NOT IN (
                        SELECT queue_id FROM processed_queue ORDER BY queue_id DESC LIMIT ?
                    )
                """, (max_records,))
        except Exception as err:
            print(f"[param_sync] prune error: {err}", flush=True)


def run_param_sync(config: dict, store: ProcessedQueueStore | None = None):
    """Main loop for parameter synchronization with idempotency guarantee."""
    cloud_url = config.get("url", "").rstrip("/")
    token = config.get("token", "")
    device_id = config.get("device", "")

    if not cloud_url or not token or not device_id:
        print("[param_sync] missing connection config; aborting sync", flush=True)
        return

    if store is None:
        store = ProcessedQueueStore(BASE / "state" / "param_sync.sqlite3")

    headers = {"Authorization": f"Bearer {token}"}
    last_catalog_sync = 0.0
    CATALOG_SYNC_INTERVAL = 180.0  # Sync full catalog every 3 minutes

    print(f"[param_sync] starting CarrotPilot parameter sync loop for device: {device_id}", flush=True)
    print(f"[param_sync] target Cloudflare Worker: {cloud_url}", flush=True)

    while True:
        now = time.time()

        # 1. Periodic full settings snapshot upload
        if now - last_catalog_sync >= CATALOG_SYNC_INTERVAL:
            snapshot = fetch_local_settings_snapshot()
            if snapshot and snapshot.get("settings") and snapshot.get("values"):
                sync_payload = {
                    "device_id": device_id,
                    "catalog": snapshot["settings"],
                    "values": snapshot["values"],
                }
                print(f"[param_sync] uploading {len(snapshot['values'])} parameters to Cloudflare...", flush=True)
                res = _http_request(
                    f"{cloud_url}/api/settings/sync",
                    data=sync_payload,
                    headers=headers,
                    timeout=15.0
                )
                if res and res.get("ok"):
                    last_catalog_sync = now
                    print(f"[param_sync] settings snapshot synced to cloud successfully! ({len(snapshot['values'])} params)", flush=True)
                else:
                    print(f"[param_sync] settings sync response: {res}", flush=True)
            else:
                print("[param_sync] no settings snapshot available to upload", flush=True)

        # 2. Poll for pending parameter changes from Home Assistant
        pending_res = _http_request(
            f"{cloud_url}/api/params/pending?device_id={urllib.parse.quote(device_id)}",
            headers=headers,
            timeout=10.0,
            verbose=False
        )

        if pending_res and pending_res.get("ok"):
            pending_list = pending_res.get("pending", [])
            if pending_list:
                applied_ids = []
                current_values = {}
                any_new_applied = False

                for item in pending_list:
                    item_id = item.get("id")
                    param_name = item.get("param_name")
                    raw_val = item.get("param_value")
                    if item_id is None or not param_name:
                        continue

                    # Idempotency check: if this queue_id was already processed, do NOT re-apply
                    existing = store.get(item_id)
                    if existing:
                        if existing["status"] == "applied":
                            applied_ids.append(item_id)
                            val = existing["actual_val"]
                            try:
                                val = float(val) if "." in val else int(val)
                            except (ValueError, TypeError):
                                pass
                            current_values[param_name] = val
                            print(f"[param_sync] queue item {item_id} ({param_name}) already applied ({existing['actual_val']}); skipping local write and resending ACK", flush=True)
                        continue

                    parsed_val = raw_val
                    if isinstance(raw_val, str):
                        if raw_val.lower() == "true":
                            parsed_val = 1
                        elif raw_val.lower() == "false":
                            parsed_val = 0
                        else:
                            try:
                                if "." in raw_val:
                                    parsed_val = float(raw_val)
                                else:
                                    parsed_val = int(raw_val)
                            except ValueError:
                                parsed_val = raw_val

                    success = apply_local_param(param_name, parsed_val)
                    if success and "value" in success:
                        actual_val = success["value"]
                        store.record(item_id, device_id, param_name, parsed_val, actual_val, "applied")
                        applied_ids.append(item_id)
                        current_values[param_name] = actual_val
                        any_new_applied = True
                        print(f"[param_sync] applied param {param_name} = {parsed_val} (verified: {actual_val})", flush=True)
                    else:
                        store.record(item_id, device_id, param_name, parsed_val, "", "failed")
                        print(f"[param_sync] rejected or failed param {param_name} = {parsed_val}", flush=True)

                if applied_ids:
                    # If new parameter was applied, upload fresh snapshot immediately
                    if any_new_applied:
                        try:
                            fresh_snapshot = fetch_local_settings_snapshot()
                            if fresh_snapshot and fresh_snapshot.get("settings") and fresh_snapshot.get("values"):
                                _http_request(
                                    f"{cloud_url}/api/settings/sync",
                                    data={
                                        "device_id": device_id,
                                        "catalog": fresh_snapshot["settings"],
                                        "values": fresh_snapshot["values"],
                                    },
                                    headers=headers,
                                    timeout=15.0,
                                    verbose=False
                                )
                                last_catalog_sync = now
                        except Exception as e:
                            print(f"[param_sync] immediate snapshot sync error: {e}", flush=True)

                    ack_payload = {
                        "device_id": device_id,
                        "applied_ids": applied_ids,
                        "current_values": current_values
                    }
                    ack_res = _http_request(
                        f"{cloud_url}/api/params/ack",
                        data=ack_payload,
                        headers=headers,
                        timeout=10.0
                    )
                    if ack_res and ack_res.get("ok"):
                        store.mark_acked(applied_ids)
                        print(f"[param_sync] acknowledged {len(applied_ids)} applied params to cloud successfully", flush=True)
                    else:
                        print(f"[param_sync] WARNING: failed to acknowledge {len(applied_ids)} params to cloud (will retry ACK on next poll)", flush=True)

        # Poll interval: 3 seconds
        time.sleep(3)


def start_param_sync_thread(config: dict) -> threading.Thread:
    thread = threading.Thread(target=run_param_sync, args=(config,), daemon=True, name="CarrotParamSync")
    thread.start()
    return thread


if __name__ == "__main__":
    conn_file = BASE / "connection.json"
    if not conn_file.exists():
        conn_file = Path("/data/id4-collector/connection.json")
    if conn_file.exists():
        conf = json.loads(conn_file.read_text())
        run_param_sync(conf)
    else:
        print(f"connection.json not found at {conn_file}")
