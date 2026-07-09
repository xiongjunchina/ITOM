"""GLID：26 位全局唯一主键（ULID，Crockford Base32，时间有序）。"""
import os
import time

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_glid() -> str:
    ts = int(time.time() * 1000)
    chars = []
    for _ in range(10):
        chars.append(_ALPHABET[ts & 0x1F])
        ts >>= 5
    chars.reverse()
    rand = int.from_bytes(os.urandom(10), "big")
    tail = []
    for _ in range(16):
        tail.append(_ALPHABET[rand & 0x1F])
        rand >>= 5
    tail.reverse()
    return "".join(chars) + "".join(tail)
