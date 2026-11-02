# 职责：企业微信回调 Token 验签与 EncodingAESKey AES 加解密（对齐官方 WXBizMsgCrypt）。
"""企微回调验签 / 加解密。

算法依据企业微信「接收消息与事件」文档：
- 签名：Token、timestamp、nonce、Encrypt 四串字典序拼接后 SHA1
- 密钥：EncodingAESKey + '=' 做 Base64，得到 32 字节 AES key；IV 取 key 前 16 字节
- 明文结构：16 字节随机 + 4 字节网络序 msg 长度 + msg + receiveid(corp_id)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import socket
import struct
import xml.etree.ElementTree as ET

from Crypto.Cipher import AES


class CryptError(Exception):
    """验签或加解密失败。"""


def _sha1_sign(token: str, timestamp: str, nonce: str, encrypt: str) -> str:
    parts = sorted([token, timestamp, nonce, encrypt])
    return hashlib.sha1("".join(parts).encode("utf-8")).hexdigest()


def verify_signature(
    token: str,
    timestamp: str,
    nonce: str,
    encrypt: str,
    msg_signature: str,
) -> bool:
    """比对 msg_signature；失败不得进入业务。"""
    if not msg_signature:
        return False
    expect = _sha1_sign(token, timestamp, nonce, encrypt)
    return hmac.compare_digest(expect, msg_signature)


def _pkcs7_pad(data: bytes, block: int = 32) -> bytes:
    amount = block - (len(data) % block)
    if amount == 0:
        amount = block
    return data + bytes([amount] * amount)


def _pkcs7_unpad(data: bytes) -> bytes:
    if not data:
        raise CryptError("empty ciphertext")
    amount = data[-1]
    if amount < 1 or amount > 32 or amount > len(data):
        raise CryptError("bad pkcs7 padding")
    if data[-amount:] != bytes([amount] * amount):
        raise CryptError("bad pkcs7 padding bytes")
    return data[:-amount]


def _aes_key(encoding_aes_key: str) -> bytes:
    raw = base64.b64decode(encoding_aes_key + "=")
    if len(raw) != 32:
        raise CryptError("EncodingAESKey must decode to 32 bytes")
    return raw


def decrypt(encoding_aes_key: str, encrypt: str, expect_corp_id: str | None = None) -> str:
    """解密 Encrypt，返回明文 XML/文本；可选校验 receiveid == corp_id。"""
    key = _aes_key(encoding_aes_key)
    cipher = AES.new(key, AES.MODE_CBC, key[:16])
    plain = _pkcs7_unpad(cipher.decrypt(base64.b64decode(encrypt)))
    if len(plain) < 20:
        raise CryptError("plaintext too short")
    msg_len = socket.ntohl(struct.unpack("I", plain[16:20])[0])
    end = 20 + msg_len
    if msg_len < 0 or end > len(plain):
        raise CryptError("bad msg length")
    msg = plain[20:end]
    receiveid = plain[end:].decode("utf-8")
    if expect_corp_id and receiveid and receiveid != expect_corp_id:
        raise CryptError("corp_id mismatch")
    return msg.decode("utf-8")


def encrypt_plain(encoding_aes_key: str, plaintext: str, corp_id: str) -> str:
    """加密明文（出站被动回复等场景）。"""
    key = _aes_key(encoding_aes_key)
    rand = os.urandom(16)
    raw = plaintext.encode("utf-8")
    body = rand + struct.pack("I", socket.htonl(len(raw))) + raw + corp_id.encode("utf-8")
    cipher = AES.new(key, AES.MODE_CBC, key[:16])
    return base64.b64encode(cipher.encrypt(_pkcs7_pad(body))).decode("utf-8")


# 兼容旧名
encrypt = encrypt_plain


def extract_encrypt_from_xml(body: str) -> str:
    """从回调 POST XML 取出 Encrypt 字段。"""
    root = ET.fromstring(body)
    node = root.find("Encrypt")
    if node is None or not node.text:
        raise CryptError("Encrypt missing")
    return node.text


def build_encrypted_response(
    token: str,
    encoding_aes_key: str,
    corp_id: str,
    plaintext_xml: str,
    nonce: str,
    timestamp: str,
) -> str:
    """构造加密被动回复 XML。"""
    cipher_text = encrypt_plain(encoding_aes_key, plaintext_xml, corp_id)
    signature = _sha1_sign(token, timestamp, nonce, cipher_text)
    return (
        "<xml>"
        f"<Encrypt><![CDATA[{cipher_text}]]></Encrypt>"
        f"<MsgSignature><![CDATA[{signature}]]></MsgSignature>"
        f"<TimeStamp>{timestamp}</TimeStamp>"
        f"<Nonce><![CDATA[{nonce}]]></Nonce>"
        "</xml>"
    )
