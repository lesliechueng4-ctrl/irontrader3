import time
from pathlib import Path
from task_manager import TaskManager


def test_task_manager_lifecycle(tmp_path: Path):
    db_file = tmp_path / "test_tasks.db"
    tm = TaskManager(db_path=db_file)

    # 1. 创建任务
    task = tm.create_task("wash_pattern", params={"workers": 4}, cancel_supported=True)
    assert task["status"] == "pending"
    assert task["kind"] == "wash_pattern"
    assert task["params"] == {"workers": 4}
    assert task["cancel_supported"] is True
    assert task["cancel_requested"] is False

    task_id = task["id"]

    # 2. 查询活跃任务
    active = tm.get_active_task("wash_pattern")
    assert active is not None
    assert active["id"] == task_id

    # 3. 更新进度
    tm.update_task(task_id, status="running", phase="扫描中", done=50, total=100)
    snap = tm.get_task(task_id)
    assert snap["status"] == "running"
    assert snap["done"] == 50
    assert snap["percent"] == 50.0

    # 4. 请求取消
    assert tm.is_cancel_requested(task_id) is False
    assert tm.request_cancel(task_id) is True
    assert tm.is_cancel_requested(task_id) is True

    # 5. 完成任务
    tm.update_task(
        task_id,
        status="completed",
        result={"matched_stocks": ["600000"]},
        finished_at=time.time(),
    )
    final_snap = tm.get_task(task_id)
    assert final_snap["status"] == "completed"
    assert final_snap["percent"] == 100.0
    assert final_snap["result"] == {"matched_stocks": ["600000"]}

    # 6. 不再是活跃任务
    assert tm.get_active_task("wash_pattern") is None

    # 7. 任务列表
    task_list = tm.list_tasks(limit=10)
    assert len(task_list) == 1
    assert task_list[0]["id"] == task_id


def test_task_manager_cleanup(tmp_path: Path):
    db_file = tmp_path / "test_cleanup.db"
    tm = TaskManager(db_path=db_file)

    now = time.time()
    for i in range(5):
        t = tm.create_task(f"test_{i}")
        tm.update_task(
            t["id"],
            status="completed",
            finished_at=now - 10000 + i,
        )

    # 清理 5000 秒前的任务
    deleted = tm.cleanup_tasks(retention_sec=5000, max_tasks=10)
    assert deleted == 5
    assert len(tm.list_tasks()) == 0


def test_scanner_statuses_and_cancel_are_persisted(tmp_path: Path):
    tm = TaskManager(db_path=tmp_path / "t.db")
    task = tm.create_task("wash_pattern", cancel_supported=True, status="queued", phase="排队中", message="等待")
    assert tm.get_active_task("wash_pattern")["id"] == task["id"]  # queued 也算进行中

    tm.update_task(task["id"], status="running", errors=3)
    assert tm.get_task(task["id"])["errors"] == 3

    assert tm.request_cancel(task["id"], message="正在停止") is True
    snap = tm.get_task(task["id"])
    assert snap["status"] == "cancelling" and snap["cancel_requested"] is True
    assert tm.get_active_task("wash_pattern") is not None  # cancelling 仍在进行中

    tm.update_task(task["id"], status="cancelled", finished_at=time.time())
    assert tm.request_cancel(task["id"]) is False  # 已结束的任务不能再取消
    assert tm.get_latest_task("wash_pattern")["status"] == "cancelled"


def test_restart_marks_other_process_tasks_interrupted(tmp_path: Path):
    db = tmp_path / "t.db"
    tm = TaskManager(db_path=db)
    task = tm.create_task("backtest", status="queued")
    conn = tm._get_connection()
    conn.execute("UPDATE tasks SET owner_pid = -1 WHERE id = ?", (task["id"],))
    conn.commit()

    TaskManager(db_path=db)  # 模拟重启
    assert tm.get_task(task["id"])["status"] == "interrupted"
