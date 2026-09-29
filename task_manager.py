"""
IronTrader Task Manager
Persistent, thread-safe background task state machine backed by SQLite (WAL mode).
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from logger_config import get_logger
from runtime_paths import application_data_dir

logger = get_logger(__name__)

_DEFAULT_RETENTION_SEC = 24 * 3600  # 24小时
_DEFAULT_MAX_TASKS = 100

# 状态约定（扫描器、回测、低吸/英雄扫描共用）
ACTIVE_STATUSES = ("pending", "queued", "running", "cancelling")
TERMINAL_STATUSES = ("completed", "finished", "failed", "cancelled", "canceled", "interrupted")
_ACTIVE_SQL = ", ".join(f"'{s}'" for s in ACTIVE_STATUSES)
_TERMINAL_SQL = ", ".join(f"'{s}'" for s in TERMINAL_STATUSES)


def _row_get(row: sqlite3.Row, key: str) -> Any:
    try:
        return row[key]
    except (IndexError, KeyError):
        return None


class TaskManager:
    """SQLite-backed Task Manager for asynchronous jobs."""

    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            output_dir = application_data_dir() / "outputs"
            output_dir.mkdir(parents=True, exist_ok=True)
            db_path = output_dir / "tasks.db"
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._local = threading.local()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(str(self.db_path), timeout=30.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            conn.execute("PRAGMA busy_timeout = 5000;")
            self._local.conn = conn
        return self._local.conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._get_connection()
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    params_json TEXT,
                    status TEXT NOT NULL,
                    phase TEXT,
                    message TEXT,
                    total INTEGER DEFAULT 0,
                    done INTEGER DEFAULT 0,
                    percent REAL DEFAULT 0.0,
                    matched INTEGER DEFAULT 0,
                    started_at REAL,
                    finished_at REAL,
                    cancel_requested INTEGER DEFAULT 0,
                    cancel_supported INTEGER DEFAULT 0,
                    output_path TEXT,
                    result_json TEXT,
                    error TEXT,
                    created_at REAL
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_kind ON tasks(kind);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at);")
            # 轻量迁移：owner_pid（进程心跳，用于识别僵尸任务）、errors（扫描失败条数）
            for ddl in (
                "ALTER TABLE tasks ADD COLUMN owner_pid INTEGER;",
                "ALTER TABLE tasks ADD COLUMN errors INTEGER DEFAULT 0;",
            ):
                try:
                    conn.execute(ddl)
                except sqlite3.OperationalError:
                    pass  # 列已存在
            conn.commit()
        self.mark_interrupted_tasks()

    def mark_interrupted_tasks(self) -> int:
        """启动时调用：把非本进程遗留的进行中任务标记为 interrupted（僵尸任务）。"""
        now = time.time()
        pid = os.getpid()
        with self._lock:
            conn = self._get_connection()
            cur = conn.execute(
                f"""
                UPDATE tasks
                SET status = 'interrupted', finished_at = ?,
                    error = '进程重启，任务中断'
                WHERE status IN ({_ACTIVE_SQL})
                AND (owner_pid IS NULL OR owner_pid != ?)
                """,
                (now, pid),
            )
            count = cur.rowcount
            conn.commit()
        if count:
            logger.info(f"标记 {count} 个遗留任务为 interrupted")
        return count

    @staticmethod
    def _to_snapshot(row: sqlite3.Row) -> Dict[str, Any]:
        started_at = float(row["started_at"] or 0)
        finished_at = row["finished_at"]
        end_time = float(finished_at) if finished_at else time.time()
        elapsed_sec = round(max(0.0, end_time - started_at), 1) if started_at else 0.0

        total = int(row["total"] or 0)
        done = int(row["done"] or 0)
        if row["status"] in ("completed", "finished"):
            percent = 100.0
        elif total > 0:
            percent = round(min(100.0, max(0.0, done / total * 100.0)), 1)
        else:
            percent = float(row["percent"] or 0.0)

        params = {}
        if row["params_json"]:
            try:
                params = json.loads(row["params_json"])
            except Exception:
                params = {}

        result = None
        if row["result_json"]:
            try:
                result = json.loads(row["result_json"])
            except Exception:
                result = None

        return {
            "id": row["id"],
            "kind": row["kind"],
            "params": params,
            "status": row["status"],
            "phase": row["phase"] or "",
            "message": row["message"] or "",
            "total": total,
            "done": done,
            "percent": percent,
            "matched": int(row["matched"] or 0),
            "errors": int(_row_get(row, "errors") or 0),
            "started_at": started_at,
            "started_at_text": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started_at)) if started_at else "",
            "finished_at": float(finished_at) if finished_at else None,
            "elapsed_sec": elapsed_sec,
            "cancel_requested": bool(row["cancel_requested"]),
            "cancel_supported": bool(row["cancel_supported"]),
            "output_path": row["output_path"],
            "result": result,
            "error": row["error"],
            "created_at": float(row["created_at"] or 0),
        }

    def create_task(
        self,
        kind: str,
        params: Optional[Dict[str, Any]] = None,
        cancel_supported: bool = False,
        task_id: Optional[str] = None,
        status: str = "pending",
        phase: str = "queued",
        message: str = "等待执行",
    ) -> Dict[str, Any]:
        now = time.time()
        tid = task_id or uuid4().hex
        params_json = json.dumps(params or {}, ensure_ascii=False)
        with self._lock:
            conn = self._get_connection()
            conn.execute(
                """
                INSERT INTO tasks (
                    id, kind, params_json, status, phase, message,
                    total, done, percent, matched, started_at, finished_at,
                    cancel_requested, cancel_supported, output_path,
                    result_json, error, created_at, owner_pid
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tid, kind, params_json, status, phase, message,
                    0, 0, 0.0, 0, now, None,
                    0, 1 if cancel_supported else 0, None,
                    None, None, now, os.getpid(),
                ),
            )
            conn.commit()
            return self.get_task(tid)  # type: ignore[return-value]

    def update_task(self, task_id: str, **updates: Any) -> Optional[Dict[str, Any]]:
        fields = []
        values = []
        allowed = {
            "status", "phase", "message", "total", "done", "percent",
            "matched", "errors", "started_at", "finished_at", "cancel_requested",
            "cancel_supported", "output_path", "result", "error",
        }

        for k, v in updates.items():
            if k not in allowed:
                continue
            if k == "result":
                fields.append("result_json = ?")
                values.append(json.dumps(v, ensure_ascii=False) if v is not None else None)
            elif k in ("cancel_requested", "cancel_supported"):
                fields.append(f"{k} = ?")
                values.append(1 if v else 0)
            else:
                fields.append(f"{k} = ?")
                values.append(v)

        if not fields:
            return self.get_task(task_id)

        values.append(task_id)
        with self._lock:
            conn = self._get_connection()
            query = f"UPDATE tasks SET {', '.join(fields)} WHERE id = ?"
            conn.execute(query, tuple(values))
            conn.commit()

        return self.get_task(task_id)

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            conn = self._get_connection()
            cur = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
            row = cur.fetchone()
            if not row:
                return None
            return self._to_snapshot(row)

    def get_active_task(self, kind: Optional[str] = None) -> Optional[Dict[str, Any]]:
        with self._lock:
            conn = self._get_connection()
            if kind:
                cur = conn.execute(
                    f"""
                    SELECT * FROM tasks
                    WHERE kind = ? AND status IN ({_ACTIVE_SQL})
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (kind,),
                )
            else:
                cur = conn.execute(
                    f"""
                    SELECT * FROM tasks
                    WHERE status IN ({_ACTIVE_SQL})
                    ORDER BY created_at DESC LIMIT 1
                    """
                )
            row = cur.fetchone()
            if not row:
                return None
            return self._to_snapshot(row)

    def is_cancel_requested(self, task_id: str) -> bool:
        with self._lock:
            conn = self._get_connection()
            cur = conn.execute("SELECT cancel_requested FROM tasks WHERE id = ?", (task_id,))
            row = cur.fetchone()
            if not row:
                return False
            return bool(row["cancel_requested"])

    def request_cancel(
        self,
        task_id: str,
        *,
        require_supported: bool = True,
        message: str = "正在取消...",
    ) -> bool:
        """请求取消：进行中的任务标记 cancel_requested 并进入 cancelling，由执行线程在检查点退出。"""
        with self._lock:
            conn = self._get_connection()
            cur = conn.execute("SELECT status, cancel_supported FROM tasks WHERE id = ?", (task_id,))
            row = cur.fetchone()
            if not row or row["status"] in TERMINAL_STATUSES:
                return False
            if require_supported and not row["cancel_supported"]:
                return False
            conn.execute(
                "UPDATE tasks SET cancel_requested = 1, status = 'cancelling', phase = '取消中', message = ? "
                "WHERE id = ?",
                (message, task_id),
            )
            conn.commit()
            return True

    def get_latest_task(self, kind: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            conn = self._get_connection()
            cur = conn.execute(
                "SELECT * FROM tasks WHERE kind = ? ORDER BY created_at DESC LIMIT 1", (kind,)
            )
            row = cur.fetchone()
            return self._to_snapshot(row) if row else None

    def list_tasks(self, kind: Optional[str] = None, limit: int = 30) -> List[Dict[str, Any]]:
        with self._lock:
            conn = self._get_connection()
            if kind:
                cur = conn.execute(
                    "SELECT * FROM tasks WHERE kind = ? ORDER BY created_at DESC LIMIT ?",
                    (kind, limit),
                )
            else:
                cur = conn.execute("SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,))
            return [self._to_snapshot(r) for r in cur.fetchall()]

    def cleanup_tasks(
        self, retention_sec: float = _DEFAULT_RETENTION_SEC, max_tasks: int = _DEFAULT_MAX_TASKS
    ) -> int:
        now = time.time()
        cutoff = now - retention_sec
        deleted_count = 0
        with self._lock:
            conn = self._get_connection()
            # 1. 删除超过 retention_sec 的已终态任务
            cur = conn.execute(
                f"""
                DELETE FROM tasks
                WHERE status IN ({_TERMINAL_SQL})
                AND finished_at IS NOT NULL AND finished_at < ?
                """,
                (cutoff,),
            )
            deleted_count += cur.rowcount

            # 2. 超出 max_tasks 限制的旧任务淘汰
            cur = conn.execute("SELECT COUNT(*) as cnt FROM tasks")
            total = cur.fetchone()["cnt"]
            if total > max_tasks:
                excess = total - max_tasks
                conn.execute(
                    f"""
                    DELETE FROM tasks WHERE id IN (
                        SELECT id FROM tasks
                        WHERE status IN ({_TERMINAL_SQL})
                        ORDER BY created_at ASC LIMIT ?
                    )
                    """,
                    (excess,),
                )
            conn.commit()
        return deleted_count


# 全局单例任务管理器
default_task_manager = TaskManager()
