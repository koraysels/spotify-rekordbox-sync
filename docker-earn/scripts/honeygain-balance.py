#!/usr/bin/env python3
"""Toon je actuele Honeygain-saldo vanaf de command line.

Leest HONEYGAIN_EMAIL / HONEYGAIN_PASSWORD uit de omgeving of uit ./.env,
haalt een token op en print het saldo plus wat je vandaag hebt verdiend.

    ./scripts/honeygain-balance.py

Alleen stdlib, dus geen extra image of pip install nodig.
"""

import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

API = "https://dashboard.honeygain.com/api/v1"


def load_env() -> None:
    """Vul os.environ aan met waarden uit een .env naast deze repo-map."""
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if not env_file.is_file():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def request(path: str, payload: dict | None = None, token: str | None = None) -> dict:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(f"{API}{path}", data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30, context=ssl.create_default_context()) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")[:400]
        sys.exit(f"Honeygain API gaf HTTP {exc.code} op {path}: {body}")
    except urllib.error.URLError as exc:
        sys.exit(f"Kan Honeygain niet bereiken: {exc.reason}")


def usd(cents) -> str:
    try:
        return f"$ {float(cents) / 100:.2f}"
    except (TypeError, ValueError):
        return "onbekend"


def main() -> None:
    load_env()
    email = os.environ.get("HONEYGAIN_EMAIL")
    password = os.environ.get("HONEYGAIN_PASSWORD")
    if not email or not password:
        sys.exit("Zet HONEYGAIN_EMAIL en HONEYGAIN_PASSWORD in .env of in je omgeving.")

    token = request("/users/tokens", {"email": email, "password": password})["data"]["access_token"]

    balances = request("/users/balances", token=token).get("data", {})
    payout = balances.get("payout", {})
    realtime = balances.get("realtime", {})

    print(f"Uitbetaalbaar saldo : {usd(payout.get('usd_cents'))}")
    print(f"Waarvan nog niet uitbetaald (realtime): {usd(realtime.get('usd_cents'))}")

    stats = request("/users/stats/today", token=token).get("data", {})
    if stats:
        traffic = stats.get("gathering", {}).get("bytes")
        credits = stats.get("gathering", {}).get("credits")
        if traffic is not None:
            print(f"Vandaag gedeeld     : {traffic / 1024 ** 3:.2f} GB")
        if credits is not None:
            print(f"Vandaag verdiend    : {credits} credits (~{usd(credits)})")


if __name__ == "__main__":
    main()
