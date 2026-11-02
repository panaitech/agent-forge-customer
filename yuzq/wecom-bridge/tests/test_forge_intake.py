# 职责：干跑模式下解析录入协作与启动 run 的契约。
import asyncio

import pytest

from app.config import Settings
from app.forge.client import ForgeClient, TeamNotFoundError


def test_resolve_and_start_dry():
    settings = Settings(
        dry_run_forge=True,
        af_intake_team_name="雨中情-合同录入",
    )
    client = ForgeClient(settings)

    async def run():
        team = await client.resolve_intake_team(
            tenant_id="雨中情",
            owner_id="wecom:c:u",
            role="operator",
        )
        assert team.name == "雨中情-合同录入"
        started = await client.start_team_run(
            tenant_id="雨中情",
            owner_id="wecom:c:u",
            role="operator",
            team_id=team.team_id,
            prompt="案例测试",
            files=[
                {
                    "filename": "a.pdf",
                    "mime": "application/pdf",
                    "url": "data:application/pdf;base64,xx",
                }
            ],
        )
        assert started.run_id.startswith("trn_dry_")
        assert started.session_id

    asyncio.run(run())


def test_resolve_by_id_missing():
    settings = Settings(dry_run_forge=True, af_intake_team_id="tm_nope")
    client = ForgeClient(settings)

    async def run():
        with pytest.raises(TeamNotFoundError):
            await client.resolve_intake_team(tenant_id="t", owner_id="o", role="admin")

    asyncio.run(run())
