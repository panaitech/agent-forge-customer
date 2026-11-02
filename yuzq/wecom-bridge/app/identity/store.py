# 职责：物化表 wecom_identity_link 的 SQLite 存储（同步结果，非主数据录入表）。
"""身份链接表存储。"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal

Status = Literal["active", "disabled"]


@dataclass
class Link:
    """企微成员与 AF 租户/归属/角色的链接行。"""

    corp_id: str
    userid: str
    af_tenant_id: str
    af_owner_id: str
    af_role: str
    status: Status
    display_name: str | None = None
    synced_at: int = 0


class IdentityStore:
    """本地 SQLite 物化 wecom_identity_link。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS wecom_identity_link (
                  corp_id TEXT NOT NULL,
                  userid TEXT NOT NULL,
                  af_tenant_id TEXT NOT NULL,
                  af_owner_id TEXT NOT NULL,
                  af_role TEXT NOT NULL,
                  status TEXT NOT NULL,
                  display_name TEXT,
                  synced_at INTEGER NOT NULL,
                  PRIMARY KEY (corp_id, userid)
                )
                """
            )
            # 索引：按归属反查（审计/运维）
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_link_owner
                ON wecom_identity_link (af_owner_id)
                """
            )

    def upsert(self, link: Link) -> None:
        now = link.synced_at or int(time.time())
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO wecom_identity_link (
                  corp_id, userid, af_tenant_id, af_owner_id, af_role,
                  status, display_name, synced_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(corp_id, userid) DO UPDATE SET
                  af_tenant_id=excluded.af_tenant_id,
                  af_owner_id=excluded.af_owner_id,
                  af_role=excluded.af_role,
                  status=excluded.status,
                  display_name=excluded.display_name,
                  synced_at=excluded.synced_at
                """,
                (
                    link.corp_id,
                    link.userid,
                    link.af_tenant_id,
                    link.af_owner_id,
                    link.af_role,
                    link.status,
                    link.display_name,
                    now,
                ),
            )

    def upsert_many(self, links: Iterable[Link]) -> int:
        count = 0
        for link in links:
            self.upsert(link)
            count += 1
        return count

    def get(self, corp_id: str, userid: str) -> Link | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT * FROM wecom_identity_link
                WHERE corp_id=? AND userid=?
                """,
                (corp_id, userid),
            ).fetchone()
        if not row:
            return None
        return Link(
            corp_id=row["corp_id"],
            userid=row["userid"],
            af_tenant_id=row["af_tenant_id"],
            af_owner_id=row["af_owner_id"],
            af_role=row["af_role"],
            status=row["status"],  # type: ignore[arg-type]
            display_name=row["display_name"],
            synced_at=row["synced_at"],
        )

    def set_status(self, corp_id: str, userid: str, status: Status) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE wecom_identity_link
                SET status=?, synced_at=?
                WHERE corp_id=? AND userid=?
                """,
                (status, int(time.time()), corp_id, userid),
            )

    def list_active(self, corp_id: str) -> list[Link]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM wecom_identity_link
                WHERE corp_id=? AND status='active'
                ORDER BY userid
                """,
                (corp_id,),
            ).fetchall()
        return [
            Link(
                corp_id=r["corp_id"],
                userid=r["userid"],
                af_tenant_id=r["af_tenant_id"],
                af_owner_id=r["af_owner_id"],
                af_role=r["af_role"],
                status=r["status"],  # type: ignore[arg-type]
                display_name=r["display_name"],
                synced_at=r["synced_at"],
            )
            for r in rows
        ]
