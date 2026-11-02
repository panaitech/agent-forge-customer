# 职责：加载 WeCom Bridge 企业级绑定与密钥配置（环境变量 / .env）。
"""Bridge 运行配置。"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """企业级绑定与服务端密钥；不按业务员逐人配置。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # —— 服务 ——
    host: str = "0.0.0.0"
    port: int = 8787
    public_base_url: str = "http://127.0.0.1:8787"
    data_dir: Path = Path("data")

    # —— 企业微信自建应用 ——
    wecom_corp_id: str = Field(default="", description="企业 corp_id")
    wecom_agent_id: int = 0
    wecom_secret: str = ""
    wecom_token: str = ""
    wecom_encoding_aes_key: str = ""
    wecom_api_base: str = "https://qyapi.weixin.qq.com"

    # —— 企业级绑定：一家企微企业 ↔ 一个 AF 租户 ——
    af_tenant_id: str = Field(default="", description="Agent Forge 租户")
    af_default_role: str = "operator"
    exceptions_path: Path = Path("config/exceptions.json")
    # True：消息兜底自动建链；生产可关，仅允许同步/导入过的成员
    identity_auto_provision: bool = True

    # —— Agent Forge 机器账号 ——
    # 推荐 IDENTITY_MAP：{"wecom-bridge":{"tenant":"<tenant>","role":"admin","delegate":true}}
    af_base_url: str = "http://127.0.0.1:4196"
    af_username: str = "wecom-bridge"
    af_password: str = ""
    af_console_base_url: str = "http://127.0.0.1:4196"
    # 合同录入协作：优先 ID；空则按名称在租户下解析（须已 inject「雨中情-合同录入」）
    af_intake_team_id: str = ""
    af_intake_team_name: str = "雨中情-合同录入"
    # 启动后轮询 run：阶段 L1、HITL 待确认、终态通知
    run_poll_interval_sec: float = 5.0
    run_poll_max_sec: int = 28800

    # —— ticket / 管理 ——
    ticket_secret: str = "change-me-ticket-secret"
    ticket_ttl_sec: int = 1800
    # 空则禁用 /admin/*；非空则要求头 X-Bridge-Admin-Token
    bridge_admin_token: str = ""

    # —— 附件 ——
    media_max_bytes: int = 20 * 1024 * 1024

    # —— 行为开关 ——
    dry_run_forge: bool = False
    dry_run_wecom_send: bool = False

    def identity_db(self) -> Path:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return self.data_dir / "wecom_identity.sqlite3"

    def attachments_dir(self) -> Path:
        path = self.data_dir / "attachments"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def load_exceptions(self) -> dict[str, dict]:
        path = self.exceptions_path
        if not path.is_file():
            return {}
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {}
        out: dict[str, dict] = {}
        for key, val in raw.items():
            if isinstance(val, dict):
                out[str(key)] = val
        return out


@lru_cache
def get_settings() -> Settings:
    return Settings()


def clear_settings_cache() -> None:
    get_settings.cache_clear()
