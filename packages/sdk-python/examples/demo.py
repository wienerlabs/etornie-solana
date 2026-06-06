"""Live demo: PYTHONPATH=. python examples/demo.py
Env: ETORNIE_API_URL, ETORNIE_TEST_EMAIL, ETORNIE_TEST_PASSWORD
"""
from __future__ import annotations

import os

from etornie import EtornieApiError, EtornieClient

base_url = os.environ["ETORNIE_API_URL"]
email = os.environ["ETORNIE_TEST_EMAIL"]
password = os.environ["ETORNIE_TEST_PASSWORD"]

with EtornieClient(base_url) as etornie:
    tokens = etornie.auth.login(email, password)
    print("login ok, token len:", len(tokens.access_token))

    me = etornie.auth.me()
    print(f"me: {me.email} | role: {me.role} | id: {me.id[:8]}…")

    cases, total = etornie.cases.list(limit=5)
    print("cases.list -> total:", total, "| returned:", len(cases))

    export_bytes = etornie.data_export.download("json")
    print("data_export(json) -> bytes:", len(export_bytes))

    try:
        etornie.cases.get("00000000-0000-0000-0000-000000000000")
    except EtornieApiError as err:
        print("error handling ok -> EtornieApiError status:", err.status_code)

print("PYTHON SDK DEMO OK")
