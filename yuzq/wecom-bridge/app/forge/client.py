# 职责：以机器账号调用 Agent Forge API；delegate 场景下用头传入业务 tenant/owner；启动录入协作。
"""Agent Forge HTTP 客户端。"""

from __future__ import annotations

import logging
import mimetypes
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from app.config import Settings

log = logging.getLogger("forge.client")


class OwnerMismatchError(RuntimeError):
    """会话归属与预期业务 owner 不一致（IDENTITY_MAP 未开 delegate 等）。"""


class TeamNotFoundError(RuntimeError):
    """租户下找不到配置的录入协作。"""


@dataclass
class SandboxObject:
    """sandbox.upload 返回。"""

    rel: str
    data_url: str
    filename: str
    mime: str


@dataclass
class TeamRef:
    """协作摘要。"""

    team_id: str
    name: str
    mode: str | None = None
    enabled: bool = True


@dataclass
class TeamRunRef:
    """一次协作运行。"""

    run_id: str
    session_id: str
    status: str
    stage: int
    team_id: str
    raw: dict[str, Any]


@dataclass
class ApprovalRef:
    """待办审批工单。"""

    approval_id: str
    session_id: str
    status: str
    team_run_id: str | None
    title: str | None = None


class ForgeClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _auth(self) -> tuple[str, str]:
        return (self.settings.af_username, self.settings.af_password)

    def _headers(self, tenant_id: str, owner_id: str, role: str) -> dict[str, str]:
        return {
            "X-AgentForge-Tenant-Id": tenant_id,
            "X-AgentForge-Owner-Id": owner_id,
            "X-AgentForge-Role": role,
        }

    def _base(self) -> str:
        return self.settings.af_base_url.rstrip("/")

    async def upload_sandbox(
        self,
        *,
        tenant_id: str,
        owner_id: str,
        role: str,
        session_id: str | None,
        path: Path,
        file_name: str,
    ) -> SandboxObject:
        """multipart 上传到 /sandbox/upload；session_id 可空（启动协作前先落文件）。"""
        mime = mimetypes.guess_type(file_name)[0] or "application/octet-stream"
        if self.settings.dry_run_forge:
            fake = f"data:{mime};base64,dryrun"
            log.info("dry_run sandbox.upload file=%s", file_name)
            return SandboxObject(rel=f"dry/{file_name}", data_url=fake, filename=file_name, mime=mime)

        url = f"{self._base()}/sandbox/upload"
        data: dict[str, str] = {"filename": file_name}
        if session_id:
            data["session_id"] = session_id
        async with httpx.AsyncClient(timeout=120) as client:
            with path.open("rb") as fh:
                resp = await client.post(
                    url,
                    data=data,
                    files={"file": (file_name, fh, mime)},
                    auth=self._auth(),
                    headers=self._headers(tenant_id, owner_id, role),
                )
            if resp.status_code >= 400:
                raise RuntimeError(f"sandbox.upload failed: {resp.status_code} {resp.text}")
            info = resp.json()
        return SandboxObject(
            rel=str(info.get("rel") or ""),
            data_url=str(info.get("data_url") or ""),
            filename=str(info.get("filename") or file_name),
            mime=str(info.get("mime") or mime),
        )

    async def list_teams(
        self,
        *,
        tenant_id: str,
        owner_id: str,
        role: str,
    ) -> list[TeamRef]:
        if self.settings.dry_run_forge:
            return [
                TeamRef(
                    team_id="tm_dry_intake",
                    name=self.settings.af_intake_team_name,
                    mode="pipeline",
                    enabled=True,
                )
            ]
        url = f"{self._base()}/team"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                url,
                auth=self._auth(),
                headers=self._headers(tenant_id, owner_id, role),
            )
            if resp.status_code >= 400:
                raise RuntimeError(f"team.list failed: {resp.status_code} {resp.text}")
            rows = resp.json()
        out: list[TeamRef] = []
        if not isinstance(rows, list):
            return out
        for row in rows:
            if not isinstance(row, dict):
                continue
            tid = row.get("id") or row.get("team_id")
            name = row.get("name")
            if not tid or not name:
                continue
            out.append(
                TeamRef(
                    team_id=str(tid),
                    name=str(name),
                    mode=str(row.get("mode") or "") or None,
                    enabled=bool(row.get("enabled", True)),
                )
            )
        return out

    async def resolve_intake_team(
        self,
        *,
        tenant_id: str,
        owner_id: str,
        role: str,
    ) -> TeamRef:
        """按 AF_INTAKE_TEAM_ID 或名称解析「雨中情-合同录入」协作。"""
        configured = (self.settings.af_intake_team_id or "").strip()
        want = (self.settings.af_intake_team_name or "").strip()
        teams = await self.list_teams(tenant_id=tenant_id, owner_id=owner_id, role=role)
        if configured:
            for team in teams:
                if team.team_id == configured:
                    return team
            raise TeamNotFoundError(f"intake team id not found: {configured}")
        for team in teams:
            if team.name == want and team.enabled:
                return team
        raise TeamNotFoundError(
            f"intake team not found by name={want!r}; inject demo team or set AF_INTAKE_TEAM_ID"
        )

    async def start_team_run(
        self,
        *,
        tenant_id: str,
        owner_id: str,
        role: str,
        team_id: str,
        prompt: str,
        files: list[dict[str, str]] | None = None,
    ) -> TeamRunRef:
        """POST /team/:teamID/run —— pipeline 会在服务端后台接力执行。"""
        if self.settings.dry_run_forge:
            rid = f"trn_dry_{uuid.uuid4().hex[:10]}"
            sid = f"ses_dry_{uuid.uuid4().hex[:10]}"
            log.info("dry_run team.run.start team=%s run=%s", team_id, rid)
            return TeamRunRef(
                run_id=rid,
                session_id=sid,
                status="running",
                stage=0,
                team_id=team_id,
                raw={"dry": True},
            )

        url = f"{self._base()}/team/{team_id}/run"
        body: dict[str, Any] = {"prompt": prompt}
        if files:
            body["files"] = files
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                url,
                json=body,
                auth=self._auth(),
                headers={**self._headers(tenant_id, owner_id, role), "Content-Type": "application/json"},
            )
            if resp.status_code >= 400:
                raise RuntimeError(f"team.run.start failed: {resp.status_code} {resp.text}")
            data = resp.json()
        run = data.get("run") if isinstance(data, dict) else None
        if not isinstance(run, dict):
            raise RuntimeError(f"team.run.start missing run: {data}")
        rid = run.get("id")
        sid = data.get("sessionID") or run.get("root_session_id")
        if not rid or not sid:
            raise RuntimeError(f"team.run.start missing ids: {data}")
        actual_owner = run.get("owner_id")
        if actual_owner and str(actual_owner) != owner_id:
            raise OwnerMismatchError(
                f"run owner mismatch: want={owner_id} got={actual_owner}; "
                "set AGENTFORGE_IDENTITY_MAP delegate=true for the bridge machine user"
            )
        return TeamRunRef(
            run_id=str(rid),
            session_id=str(sid),
            status=str(run.get("status") or "running"),
            stage=int(run.get("stage") or 0),
            team_id=str(run.get("team_id") or team_id),
            raw=run,
        )

    async def get_team_run(
        self,
        *,
        tenant_id: str,
        owner_id: str,
        role: str,
        run_id: str,
    ) -> TeamRunRef:
        if self.settings.dry_run_forge:
            return TeamRunRef(
                run_id=run_id,
                session_id=f"ses_for_{run_id}",
                status="running",
                stage=0,
                team_id="tm_dry_intake",
                raw={"dry": True},
            )
        url = f"{self._base()}/team-run/{run_id}"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                url,
                auth=self._auth(),
                headers=self._headers(tenant_id, owner_id, role),
            )
            if resp.status_code >= 400:
                raise RuntimeError(f"team.run.get failed: {resp.status_code} {resp.text}")
            data = resp.json()
        run = data.get("run") if isinstance(data, dict) else None
        if not isinstance(run, dict):
            raise RuntimeError(f"team.run.get missing run: {data}")
        return TeamRunRef(
            run_id=str(run.get("id") or run_id),
            session_id=str(run.get("root_session_id") or ""),
            status=str(run.get("status") or ""),
            stage=int(run.get("stage") or 0),
            team_id=str(run.get("team_id") or ""),
            raw=run,
        )

    async def list_pending_approvals(
        self,
        *,
        tenant_id: str,
        owner_id: str,
        role: str,
        run_id: str | None = None,
    ) -> list[ApprovalRef]:
        """列出 pending HITL；可按 team_run_id 过滤。"""
        if self.settings.dry_run_forge:
            return []
        url = f"{self._base()}/approval"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                url,
                params={"status": "pending"},
                auth=self._auth(),
                headers=self._headers(tenant_id, owner_id, role),
            )
            if resp.status_code >= 400:
                raise RuntimeError(f"approval.list failed: {resp.status_code} {resp.text}")
            rows = resp.json()
        out: list[ApprovalRef] = []
        if not isinstance(rows, list):
            return out
        for row in rows:
            if not isinstance(row, dict):
                continue
            tr = row.get("team_run_id")
            if run_id and tr and str(tr) != run_id:
                continue
            if run_id and not tr:
                continue
            aid = row.get("id") or row.get("approvalID")
            sid = row.get("session_id") or row.get("sessionID")
            if not aid or not sid:
                continue
            out.append(
                ApprovalRef(
                    approval_id=str(aid),
                    session_id=str(sid),
                    status=str(row.get("status") or "pending"),
                    team_run_id=str(tr) if tr else None,
                    title=str(row.get("title") or row.get("tool") or "") or None,
                )
            )
        return out
