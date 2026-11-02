# 职责：身份解析——按规则建档、例外覆盖、消息路径兜底 upsert。
"""身份链接业务逻辑。"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings
from app.identity.owner import af_owner_id
from app.identity.store import IdentityStore, Link


class IdentityDenied(Exception):
    """成员不可用（禁用 / 例外停用）。"""


@dataclass
class ResolvedIdentity:
    """回调路径解析后的业务身份。"""

    corp_id: str
    userid: str
    tenant_id: str
    owner_id: str
    role: str
    display_name: str | None


class IdentityService:
    def __init__(self, settings: Settings, store: IdentityStore) -> None:
        self.settings = settings
        self.store = store
        self.exceptions = settings.load_exceptions()

    def _role_for(self, userid: str) -> str:
        exc = self.exceptions.get(userid) or {}
        role = exc.get("role")
        if isinstance(role, str) and role.strip():
            return role.strip()
        return self.settings.af_default_role

    def _forced_disabled(self, userid: str) -> bool:
        exc = self.exceptions.get(userid) or {}
        return str(exc.get("status", "")).lower() == "disabled"

    def build_link(
        self,
        userid: str,
        *,
        display_name: str | None = None,
        status: str = "active",
    ) -> Link:
        corp = self.settings.wecom_corp_id
        tenant = self.settings.af_tenant_id
        if not corp or not tenant:
            raise ValueError("wecom_corp_id and af_tenant_id must be configured")
        if self._forced_disabled(userid):
            status = "disabled"
        return Link(
            corp_id=corp,
            userid=userid,
            af_tenant_id=tenant,
            af_owner_id=af_owner_id(corp, userid),
            af_role=self._role_for(userid),
            status=status,  # type: ignore[arg-type]
            display_name=display_name,
        )

    def ensure_member(
        self,
        userid: str,
        *,
        display_name: str | None = None,
    ) -> ResolvedIdentity:
        """查链接表；无行则按同一规则兜底 upsert。禁用则抛 IdentityDenied。"""
        corp = self.settings.wecom_corp_id
        if self._forced_disabled(userid):
            link = self.build_link(userid, display_name=display_name, status="disabled")
            self.store.upsert(link)
            raise IdentityDenied(f"userid disabled by exception: {userid}")

        row = self.store.get(corp, userid)
        if row is None:
            if not self.settings.identity_auto_provision:
                raise IdentityDenied(f"userid not provisioned: {userid}")
            row = self.build_link(userid, display_name=display_name, status="active")
            self.store.upsert(row)
        elif display_name and display_name != row.display_name:
            row.display_name = display_name
            self.store.upsert(row)

        if row.status != "active":
            raise IdentityDenied(f"userid not active: {userid}")

        return ResolvedIdentity(
            corp_id=row.corp_id,
            userid=row.userid,
            tenant_id=row.af_tenant_id,
            owner_id=row.af_owner_id,
            role=row.af_role,
            display_name=row.display_name,
        )

    def import_userids(self, userids: list[str], names: dict[str, str] | None = None) -> int:
        """S0 过渡：可见范围成员批量导入（仍用同一 owner 规则）。"""
        names = names or {}
        links = [
            self.build_link(uid, display_name=names.get(uid), status="active")
            for uid in userids
            if uid.strip()
        ]
        return self.store.upsert_many(links)
