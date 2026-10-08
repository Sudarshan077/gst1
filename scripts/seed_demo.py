"""Seed a demo user + GSTINs against the running GST backend (dev mode).

Run with the BACKEND venv, from the repo root, while the backend is up on :8084:
    backend/.venv/Scripts/python.exe scripts/seed_demo.py

Re-running reuses the same email; GSTIN create returns 200/409.
Clear the OTP rate limit first if you have already run this >5x this hour:
    /d/farmer_app/tools/redis/redis-cli.exe -p 6380 del "otp_rl:demo.tony@example.com"
"""

import json
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8084/api/v1"
EMAIL = "demo.tony@example.com"
CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def call(path, payload=None, token=None, method=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method or ("POST" if data else "GET")
    )
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:400]


def make_gstin(state: str, pan_body: str, entity: str = "1") -> str:
    """Mod-36 checksum-valid GSTIN: PAN == GSTIN[2:12]. Never invent one."""
    first14 = f"{state}{pan_body}{entity}Z"
    total = 0
    for i, ch in enumerate(first14):
        prod = CHARSET.index(ch) * (1 if i % 2 == 0 else 2)
        total += prod // 36 + prod % 36
    return first14 + CHARSET[(36 - total % 36) % 36]


def login() -> str:
    st, body = call("/auth/otp/request", {"identifier": EMAIL, "purpose": "LOGIN"})
    if st != 200:
        st, body = call("/auth/otp/request", {"identifier": EMAIL, "purpose": "REGISTER"})
    if st != 200:
        raise SystemExit(f"otp request failed ({st}): {body}")
    st, body = call("/auth/otp/verify", {"identifier": EMAIL, "otp": body["data"]["dev_otp"]})
    if st != 200:
        raise SystemExit(f"otp verify failed ({st}): {body}")
    return body["data"]["access_token"]


def main() -> None:
    token = login()
    # filing_scheme is pattern-constrained: REGULAR_MONTHLY | QRMP | COMPOSITION
    accounts = [
        (make_gstin("27", "AAPFU0939F"), "Sunrise Traders Pvt Ltd", "REGULAR_MONTHLY"),
        (make_gstin("29", "AABCU9603R"), "Karnataka Components LLP", "QRMP"),
        (make_gstin("07", "AAACR5055K"), "Delhi Retail House", "REGULAR_MONTHLY"),
        (make_gstin("33", "AAGCP1234M"), "Chennai Textiles Co", "COMPOSITION"),
    ]
    for gstin, name, scheme in accounts:
        st, body = call(
            "/gst-accounts",
            {"gstin": gstin, "legal_name": name, "filing_scheme": scheme},
            token,
        )
        print(f"{gstin} {scheme} -> {st} {str(body)[:120]}")
    print("--- /auth/me ---")
    print(json.dumps(call("/auth/me", token=token)[1], indent=1))


if __name__ == "__main__":
    main()
