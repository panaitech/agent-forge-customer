# 职责：校验入站 msg_id 幂等占位与 session/run 绑定。
from pathlib import Path

from app.pipeline.inbound import TaskStore


def test_claim_once(tmp_path: Path):
    store = TaskStore(tmp_path / "t.sqlite3")
    first = store.claim("m1", "u1", "YZQ-1")
    assert first.is_new is True
    assert first.task_no == "YZQ-1"
    second = store.claim("m1", "u1", "YZQ-2")
    assert second.is_new is False
    assert second.task_no == "YZQ-1"
    store.bind_run("m1", "ses_abc", "trn_xyz")
    third = store.claim("m1", "u1", "YZQ-3")
    assert third.session_id == "ses_abc"
    assert third.run_id == "trn_xyz"
