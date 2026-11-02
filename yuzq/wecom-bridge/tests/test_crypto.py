# 职责：校验企微验签与 AES 加解密往返。
import base64
import hashlib
import os

from app.crypto import wecom_crypt as crypt


def _aes_key_b64() -> str:
    # 32 字节随机 → 标准 EncodingAESKey（去掉尾部 =）
    raw = os.urandom(32)
    return base64.b64encode(raw).decode().rstrip("=")


def test_encrypt_decrypt_roundtrip():
    key = _aes_key_b64()
    corp = "wwtestcorp"
    plain = "<xml><ToUserName><![CDATA[wwtestcorp]]></ToUserName><FromUserName><![CDATA[alice]]></FromUserName><MsgType><![CDATA[text]]></MsgType><Content><![CDATA[hello]]></Content></xml>"
    enc = crypt.encrypt(key, plain, corp)
    out = crypt.decrypt(key, enc, expect_corp_id=corp)
    assert out == plain


def test_verify_signature():
    token = "tok"
    ts = "1710000000"
    nonce = "nonce1"
    encrypt = "abcdef"
    parts = sorted([token, ts, nonce, encrypt])
    expect = hashlib.sha1("".join(parts).encode()).hexdigest()
    assert crypt.verify_signature(token, ts, nonce, encrypt, expect)
    assert not crypt.verify_signature(token, ts, nonce, encrypt, "deadbeef")
