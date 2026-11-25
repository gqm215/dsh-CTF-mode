#!/usr/bin/env python3
"""ctfy_pow.py — ALTCHA-style proof-of-work solver for CTFy's human check.

CTFy gates `POST /instances` behind a human check (`428 human_check_required`,
provider `pow`). The browser solves it with the ALTCHA widget; this module does
the same in plain Python so the CTF mode adapter can act as a well-behaved client
(the platform explicitly allows agents: `agents_allowed=true`).

Protocol (verified against the deployed frontend worker
`/assets/pbkdf2-CIq9Xt-Y.js` and the `X-Human-Check` header):

1. ``GET /api/v1/human-check/challenge?point=<point>`` returns
   ``{parameters:{algorithm,cost,keyLength,keyPrefix,nonce,salt,expiresAt,data},
      signature}`` (all hex strings are hex-encoded bytes).
2. For counter = 0, 1, 2, ...:
     password = nonce_bytes || uint32_be(counter)
     key      = PBKDF2-HMAC-SHA256(password, salt=salt_bytes,
                                   iterations=cost, dklen=keyLength)
   stop when ``key`` starts with ``keyPrefix`` bytes.
3. Token = base64(JSON({"challenge":{"parameters":...,"signature":...},
                        "solution":{"counter":N,"derivedKey":hex,"time":ms}}))
   and is sent as the ``X-Human-Check`` request header.

Never prints or persists the team key.
"""
from __future__ import annotations

import base64
import hashlib
import json
import time

HASHES = {
    "PBKDF2/SHA-256": "sha256",
    "PBKDF2/SHA-384": "sha384",
    "PBKDF2/SHA-512": "sha512",
}


def _unhex(s: str) -> bytes:
    s = (s or "").strip()
    if len(s) % 2:
        s = "0" + s
    return bytes.fromhex(s)


def solve(parameters: dict, max_counter: int = 200000) -> dict:
    """Return {counter, derivedKey(hex), time(ms), attempts}."""
    algo = parameters.get("algorithm")
    if algo not in HASHES:
        raise ValueError(f"unsupported PoW algorithm: {algo!r}")
    cost = int(parameters.get("cost") or 0)
    key_length = int(parameters.get("keyLength") or 32)
    prefix_hex = (parameters.get("keyPrefix") or "").lower()
    if not prefix_hex:
        raise ValueError("challenge has no keyPrefix")
    prefix = _unhex(prefix_hex)
    nonce = _unhex(parameters["nonce"])
    salt = _unhex(parameters["salt"])
    t0 = time.time()
    for counter in range(max_counter):
        password = nonce + counter.to_bytes(4, "big")
        key = hashlib.pbkdf2_hmac(HASHES[algo], password, salt, cost, key_length)
        if key.startswith(prefix):
            return {"counter": counter, "derivedKey": key.hex(),
                    "time": round((time.time() - t0) * 1000, 1),
                    "attempts": counter + 1}
    raise RuntimeError(f"no solution within {max_counter} counters")


def token_from_challenge(challenge: dict, solution: dict) -> str:
    payload = {
        "challenge": {
            "parameters": challenge["parameters"],
            "signature": challenge.get("signature", ""),
        },
        "solution": {
            "counter": solution["counter"],
            "derivedKey": solution["derivedKey"],
            "time": solution.get("time", 0),
        },
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return base64.b64encode(raw).decode()


def solve_token(client, point: str) -> tuple[str, dict]:
    """Fetch a challenge for `point` and return (token, solution)."""
    code, challenge = client.get(f"/human-check/challenge?point={point}")
    if code != 200 or not isinstance(challenge, dict) or "parameters" not in challenge:
        raise RuntimeError(f"challenge fetch failed HTTP {code}: {str(challenge)[:300]}")
    exp = challenge["parameters"].get("expiresAt")
    if exp and time.time() > float(exp):
        raise RuntimeError("challenge already expired")
    sol = solve(challenge["parameters"])
    return token_from_challenge(challenge, sol), sol
