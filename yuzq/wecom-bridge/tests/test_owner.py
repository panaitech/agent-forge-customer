# 职责：校验 owner_id 生成规则符合设计方案。
from app.identity.owner import af_owner_id


def test_owner_format():
    assert af_owner_id("wwcorp", "zhangsan") == "wecom:wwcorp:zhangsan"


def test_owner_strip():
    assert af_owner_id(" ww ", " u1 ") == "wecom:ww:u1"
