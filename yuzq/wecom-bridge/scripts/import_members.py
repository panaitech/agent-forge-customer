#!/usr/bin/env python3
# 职责：S0 过渡方案——按可见范围 userid 列表批量导入身份链接（同一 owner 规则）。
"""批量导入企微成员到 wecom_identity_link。

用法：
  cd wecom-bridge
  PYTHONPATH=. python scripts/import_members.py --file members.txt
  # members.txt 每行一个 userid，或 userid,显示名
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_settings
from app.identity.service import IdentityService
from app.identity.store import IdentityStore


def load_file(path: Path) -> tuple[list[str], dict[str, str]]:
    userids: list[str] = []
    names: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "," in line:
            uid, name = line.split(",", 1)
            uid, name = uid.strip(), name.strip()
            userids.append(uid)
            if name:
                names[uid] = name
        else:
            userids.append(line)
    return userids, names


def main() -> None:
    parser = argparse.ArgumentParser(description="Import WeCom visible members into identity link")
    parser.add_argument("--file", required=True, help="userid list file")
    args = parser.parse_args()

    settings = get_settings()
    if not settings.wecom_corp_id or not settings.af_tenant_id:
        raise SystemExit("WECOM_CORP_ID and AF_TENANT_ID required")

    store = IdentityStore(settings.identity_db())
    service = IdentityService(settings, store)
    userids, names = load_file(Path(args.file))
    n = service.import_userids(userids, names)
    print(f"imported={n} db={settings.identity_db()}")


if __name__ == "__main__":
    main()
