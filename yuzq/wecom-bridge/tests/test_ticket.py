# 职责：校验 ticket 签发、校验与过期。
import time

import pytest

from app.config import Settings
from app.ticket import token as ticket


def test_issue_and_verify():
    settings = Settings(ticket_secret="sec", ticket_ttl_sec=60)
    tok = ticket.issue(
        settings,
        tenant_id="t1",
        owner_id="wecom:c:u",
        session_id="ses_1",
        run_id="trn_1",
    )
    payload = ticket.verify(settings, tok)
    assert payload.tenant_id == "t1"
    assert payload.owner_id == "wecom:c:u"
    assert payload.session_id == "ses_1"
    assert payload.run_id == "trn_1"


def test_expired():
    settings = Settings(ticket_secret="sec", ticket_ttl_sec=-1)
    tok = ticket.issue(
        settings,
        tenant_id="t1",
        owner_id="o1",
        session_id="s1",
    )
    time.sleep(0.01)
    with pytest.raises(ticket.TicketError):
        ticket.verify(settings, tok)
