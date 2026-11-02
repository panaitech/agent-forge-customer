# 职责：校验身份链接建档、例外禁用与消息兜底。
from pathlib import Path

import pytest

from app.config import Settings
from app.identity.service import IdentityDenied, IdentityService
from app.identity.store import IdentityStore


def test_ensure_member_creates_link(tmp_path: Path):
    exc = tmp_path / "exceptions.json"
    exc.write_text("{}", encoding="utf-8")
    settings = Settings(
        wecom_corp_id="wwc",
        af_tenant_id="tenant-yuzq",
        af_default_role="operator",
        data_dir=tmp_path / "data",
        exceptions_path=exc,
    )
    store = IdentityStore(settings.identity_db())
    svc = IdentityService(settings, store)
    ident = svc.ensure_member("zhangsan", display_name="张三")
    assert ident.owner_id == "wecom:wwc:zhangsan"
    assert ident.tenant_id == "tenant-yuzq"
    assert ident.role == "operator"
    # 再次调用不改规则
    again = svc.ensure_member("zhangsan")
    assert again.owner_id == ident.owner_id


def test_exception_disabled(tmp_path: Path):
    exc = tmp_path / "exceptions.json"
    exc.write_text('{"bob":{"status":"disabled"}}', encoding="utf-8")
    settings = Settings(
        wecom_corp_id="wwc",
        af_tenant_id="tenant-yuzq",
        data_dir=tmp_path / "data",
        exceptions_path=exc,
    )
    store = IdentityStore(settings.identity_db())
    svc = IdentityService(settings, store)
    with pytest.raises(IdentityDenied):
        svc.ensure_member("bob")


def test_auto_provision_off(tmp_path: Path):
    exc = tmp_path / "exceptions.json"
    exc.write_text("{}", encoding="utf-8")
    settings = Settings(
        wecom_corp_id="wwc",
        af_tenant_id="tenant-yuzq",
        data_dir=tmp_path / "data",
        exceptions_path=exc,
        identity_auto_provision=False,
    )
    store = IdentityStore(settings.identity_db())
    svc = IdentityService(settings, store)
    with pytest.raises(IdentityDenied):
        svc.ensure_member("newbie")
