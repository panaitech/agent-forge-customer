#!/usr/bin/env python3
# 职责：拉取企微通讯录（按部门）并 upsert 身份链接；生产主路径。
"""通讯录同步（简化实现：递归部门用户列表）。

用法：
  cd wecom-bridge
  PYTHONPATH=. python scripts/sync_contacts.py --department-id 1

说明：
  - 需开通通讯录只读权限
  - 应用可见范围仍由企微侧控制；本脚本按部门拉人后统一按规则建档
  - 不在脚本内的成员不会自动 disabled（完整增量对齐可后续增强）
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_settings
from app.identity.service import IdentityService
from app.identity.store import IdentityStore


def get_token(base: str, corp_id: str, secret: str) -> str:
    with httpx.Client(timeout=30) as client:
        resp = client.get(
            f"{base}/cgi-bin/gettoken",
            params={"corpid": corp_id, "corpsecret": secret},
        )
        resp.raise_for_status()
        data = resp.json()
    if data.get("errcode", 0) != 0:
        raise RuntimeError(data)
    return data["access_token"]


def list_users(base: str, token: str, department_id: int) -> list[dict]:
    with httpx.Client(timeout=60) as client:
        resp = client.get(
            f"{base}/cgi-bin/user/list",
            params={
                "access_token": token,
                "department_id": department_id,
                "fetch_child": 1,
            },
        )
        resp.raise_for_status()
        data = resp.json()
    if data.get("errcode", 0) != 0:
        raise RuntimeError(data)
    return list(data.get("userlist") or [])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--department-id", type=int, default=1)
    args = parser.parse_args()

    settings = get_settings()
    token = get_token(settings.wecom_api_base, settings.wecom_corp_id, settings.wecom_secret)
    users = list_users(settings.wecom_api_base, token, args.department_id)

    store = IdentityStore(settings.identity_db())
    service = IdentityService(settings, store)
    userids = [u["userid"] for u in users if u.get("userid")]
    names = {u["userid"]: u.get("name") or "" for u in users if u.get("userid")}
    n = service.import_userids(userids, names)
    print(f"synced={n} department={args.department_id}")


if __name__ == "__main__":
    main()
