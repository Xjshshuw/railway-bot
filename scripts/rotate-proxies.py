#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
چرخش TCP Proxy — هوشمند (دامنه‌های تأیید) یا رندوم (تست اتصال)
=============================================================
برای هر سرویس 3x-ui، TCP Proxy فعلی را حذف و یکی جدید می‌سازد:
  - هوشمند: تا رسیدن به یکی از دامنه‌های GOOD (لیست تأیید) حلقه می‌زند
  - رندوم:  اولین دامنه‌ای که اتصال TCP آن OK باشد را نگه می‌دارد
            (دامنه همیشه تصادفی است — Railway خودش انتخاب می‌کند؛
             فقط فیلتر می‌کنیم که وصل‌شدنی باشد)

ورودی (Environment):
  RAILWAY_TOKEN   توکن اکانت Railway
  ENV_ID          شناسه Environment
  SERVICE_IDS     JSON: {"xui-nl": "svc-id", ...}
  TARGET_DOMAINS  کاما جدا (خالی = رندوم) — مثل: monorail,nozomi
  PORT            پورت اپلیکیشن (پیش‌فرض 443)
  MAX_TRIES       سقف تلاش به ازای هر سرویس (پیش‌فرض 30)
  COOLDOWN        ثانیه بین سیکل‌ها (پیش‌فرض 8)

خروجی (قابل پارس توسط ربات): به ازای هر موفقیت یک خط
  PROXY_RESULT: <name>=<domain>:<port>
"""

import json
import os
import socket
import sys
import time
import urllib.request

# ── تنظیمات ────────────────────────────────────────────
TOKEN = os.environ.get("RAILWAY_TOKEN", "")
URL = "https://backboard.railway.com/graphql/v2"
ENV = os.environ.get("ENV_ID", "")

# دامنه‌های تأیید (همان لیست ۱۲تایی)
GOOD_DOMAINS = os.environ.get(
    "GOOD_DOMAINS",
    "monorail,nozomi,turntable,trolley,reseau,autorack,metro,hopper,kodama,interchange,switchyard,junction"
)
_TARGET_RAW = [d.strip() for d in os.environ.get("TARGET_DOMAINS", GOOD_DOMAINS).split(",") if d.strip()]
TARGET_DOMAINS = set()
for _d in _TARGET_RAW:
    _d = _d.rstrip(".")
    if _d and not _d.endswith(".proxy.rlwy.net"):
        _d = _d + ".proxy.rlwy.net"
    if _d:
        TARGET_DOMAINS.add(_d)

APPLICATION_PORT = int(os.environ.get("PORT", "443"))
MAX_TRIES = int(os.environ.get("MAX_TRIES", "30"))
COOLDOWN = float(os.environ.get("COOLDOWN", "8"))
CONNECT_TIMEOUT = float(os.environ.get("CONNECT_TIMEOUT", "5"))

# سرویس‌ها: JSON {"name": "service-id", ...}
try:
    SERVICES = json.loads(os.environ.get("SERVICE_IDS", "{}"))
except Exception as e:
    print(f"❌ SERVICE_IDS معتبر نیست: {e}", flush=True)
    sys.exit(2)


# ══════════ Railway GraphQL ══════════
def gql(query, variables=None):
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(URL, data=body, headers={
        "Authorization": "Bearer " + TOKEN,
        "Content-Type": "application/json",
        "User-Agent": "railway-cli/5.30.4",
        "Accept": "*/*",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def _check(r):
    if "data" not in r:
        print(f"  !! API error: {json.dumps(r)[:300]}", flush=True)
        return None
    return r["data"]


def list_proxies(service_id):
    q = ('query($e: String!, $s: String!) { '
         'tcpProxies(environmentId: $e, serviceId: $s) '
         '{ id domain proxyPort applicationPort syncStatus } }')
    data = _check(gql(q, {"e": ENV, "s": service_id}))
    return (data or {}).get("tcpProxies", [])


def delete_proxy(proxy_id):
    data = _check(gql('mutation($id: String!) { tcpProxyDelete(id: $id) }', {"id": proxy_id}))
    return bool(data and data.get("tcpProxyDelete"))


def create_proxy(service_id):
    r = gql('mutation($input: TCPProxyCreateInput!) { '
            'tcpProxyCreate(input: $input) { id domain proxyPort applicationPort syncStatus } }',
            {"input": {
                "applicationPort": APPLICATION_PORT,
                "environmentId": ENV,
                "serviceId": service_id,
            }})
    data = _check(r)
    return (data or {}).get("tcpProxyCreate") or {}


def ensure_no_live_proxies(service_id, timeout=150):
    deadline = time.time() + timeout
    while time.time() < deadline:
        proxies = list_proxies(service_id)
        live = [p for p in proxies if p.get("syncStatus") not in ("DELETED", "DELETING")]
        if not live:
            return True
        time.sleep(4)
    return False


def wait_proxy_active(service_id, timeout=240):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        proxies = list_proxies(service_id)
        live = [p for p in proxies if p.get("syncStatus") == "ACTIVE"]
        if len(live) == 1:
            return live[0]
        if live:
            last = live[0]
        time.sleep(5)
    return last


def test_connectivity(domain, port):
    try:
        s = socket.create_connection((domain, port), timeout=CONNECT_TIMEOUT)
        s.close()
        return True
    except Exception:
        return False


# ── حلقه چرخش یک سرویس ──
def rotate_service(name, service_id, max_tries):
    """حذف و ساخت متوالی تا رسیدن به هدف. برمی‌گرداند (domain, port) یا None."""
    seen = set()
    print(f"\n===== {name} ({service_id}) =====", flush=True)
    for attempt in range(1, max_tries + 1):
        # ۱) حذف پروکسی‌های غیرهدف
        proxies = list_proxies(service_id)
        for p in proxies:
            if p.get("domain") not in TARGET_DOMAINS and p.get("syncStatus") not in ("DELETED", "DELETING"):
                print(f"  [{attempt}] deleting {p['id'][:8]} ({p.get('domain')}:{p.get('proxyPort')})", flush=True)
                delete_proxy(p["id"])
        if proxies and not ensure_no_live_proxies(service_id):
            print(f"  [{attempt}] WARN: proxies still present after delete wait", flush=True)
            time.sleep(10)
        time.sleep(max(COOLDOWN - 2, 3))

        # ۲) ساخت پروکسی جدید
        created = create_proxy(service_id)
        if not created:
            print(f"  [{attempt}] create FAILED, retrying...", flush=True)
            time.sleep(COOLDOWN)
            continue
        domain = (created.get("domain") or "?").rstrip(".")
        seen.add(domain)
        print(f"  [{attempt}] created -> {domain}:{created.get('proxyPort')}", flush=True)

        # ۳) منتظر ACTIVE
        proxy = wait_proxy_active(service_id, timeout=240)
        if proxy:
            final_domain = (proxy.get("domain") or "").rstrip(".")
            if final_domain and final_domain != domain:
                seen.add(final_domain)
                domain = final_domain
                print(f"  [{attempt}] -> final {domain}:{proxy.get('proxyPort')}", flush=True)

        # ۴) شرط موفقیت
        proxy_port = (proxy or created).get("proxyPort") or APPLICATION_PORT
        hit = False
        if TARGET_DOMAINS:
            if domain in TARGET_DOMAINS:
                hit = True
        else:
            ok = test_connectivity(domain, proxy_port)
            print(f"  [{attempt}] connectivity {domain}:{proxy_port} -> {'OK ✓' if ok else 'FAIL ✗'}", flush=True)
            if ok:
                hit = True

        if hit:
            if TARGET_DOMAINS:
                print(f"  *** TARGET HIT: {name} -> {domain}:{proxy_port} ***", flush=True)
            else:
                print(f"  *** GOOD DOMAIN FOUND: {name} -> {domain}:{proxy_port} ***", flush=True)
            print(f"PROXY_RESULT: {name}={domain}:{proxy_port}", flush=True)
            return (domain, proxy_port)

        time.sleep(COOLDOWN)

    print(f"  ✗ {name}: NOT REACHED after {max_tries} tries. seen: {sorted(seen)}", flush=True)
    return None


def main():
    if not TOKEN or not ENV:
        print("❌ RAILWAY_TOKEN و ENV_ID را تنظیم کن!", flush=True)
        return 2
    if not SERVICES:
        print("❌ SERVICE_IDS (JSON) را تنظیم کن!", flush=True)
        return 2

    mode = "هوشمند" if TARGET_DOMAINS else "رندوم"
    print(f"🎯 حالت: {mode} — {len(SERVICES)} سرویس (پورت {APPLICATION_PORT})", flush=True)
    if TARGET_DOMAINS:
        print(f"   اهداف: {sorted(TARGET_DOMAINS)}", flush=True)

    results = {}
    for name, svc in SERVICES.items():
        res = rotate_service(name, svc, MAX_TRIES)
        results[name] = res
        time.sleep(2)

    ok = [n for n, r in results.items() if r]
    print(f"\n===== SUMMARY =====\nموفق: {len(ok)}/{len(results)} — {', '.join(ok) or 'هیچ‌کدام'}", flush=True)
    return 0 if len(ok) == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
