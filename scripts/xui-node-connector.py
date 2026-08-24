#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
3x-ui Multi-Region Node Connector
=================================
لاگین به هر ۴ پنل 3x-ui، ساخت API Token برای هر کدام، و اتصال ۳ نود ریموت
به پنل اصلی (xui-nl) — همه از طریق API داخلی 3x-ui.

استفاده:
    python3 xui-node-connector.py
"""

import json
import sys
import time
import urllib.request
import urllib.error


# پنلها از متغیر محیطی PANELS خوانده میشوند — فرمت:
#   PANELS="xui-nl=https://...;xui-sg=https://...;..."
#   MAIN_PANEL="xui-nl"
#   REMOTE_NODES="xui-sg,xui-us-va,xui-us-ca"
import os

def _parse_panels():
    raw = os.environ.get("PANELS", "")
    panels = {}
    if raw:
        for part in raw.split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                panels[k.strip()] = v.strip()
    return panels

PANELS = _parse_panels() or {
    "xui-nl": "https://xui-nl-production-a29c.up.railway.app",
    "xui-sg": "https://xui-sg-production-434c.up.railway.app",
    "xui-us-va": "https://xui-us-va-production-3d26.up.railway.app",
    "xui-us-ca": "https://xui-us-ca-production-4c58.up.railway.app",
}

MAIN_PANEL = os.environ.get("MAIN_PANEL", "xui-nl")  # پنل مرکزی
REMOTE_NODES = [n.strip() for n in os.environ.get("REMOTE_NODES", "xui-sg,xui-us-va,xui-us-ca").split(",") if n.strip()]  # نودهای ریموت
USERNAME = os.environ.get("XUI_USERNAME", "admin")
PASSWORD = os.environ.get("XUI_PASSWORD", "admin")


def req(base, path, method="GET", data=None, cookie=None, csrf=None, timeout=15):
    url = base + path
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
        "Accept": "application/json",
    }
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    if cookie:
        headers["Cookie"] = cookie
    if csrf:
        headers["X-CSRF-Token"] = csrf
    r = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, dict(resp.headers), resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode()
    except Exception as e:
        return 0, {}, str(e)


def get_cookie(headers):
    sc = headers.get("Set-Cookie", "")
    return sc.split(";")[0] if sc else ""


def login(base):
    """لاگین به پنل و برگرداندن (کوکی سشن، csrf)."""
    status, hdrs, _ = req(base, "/managepanel/")
    cookie = get_cookie(hdrs)
    if not cookie:
        return None, None, f"کوکی نگرفتیم ({status})"
    status, _, body = req(base, "/managepanel/csrf-token", cookie=cookie)
    csrf = ""
    try:
        csrf = json.loads(body).get("obj", "")
    except Exception:
        pass
    status, hdrs, body = req(base, "/managepanel/login", method="POST",
                             data={"username": USERNAME, "password": PASSWORD},
                             cookie=cookie, csrf=csrf)
    if status != 200:
        return None, None, f"لاگین ناموفق ({status}): {body[:150]}"
    try:
        ok = json.loads(body).get("success")
        if not ok:
            return None, None, f"لاگین رد شد: {body[:150]}"
    except Exception:
        pass
    sess = get_cookie(hdrs) or cookie
    # CSRF تازه بعد از لاگین (توکن قبلی با سشن جدید نامعتبر است)
    status, _, body = req(base, "/managepanel/csrf-token", cookie=sess)
    try:
        csrf = json.loads(body).get("obj", "")
    except Exception:
        pass
    return sess, csrf, ""


def api_call(base, cookie, path, method="GET", data=None, csrf=None):
    status, _, body = req(base, path, method=method, data=data, cookie=cookie, csrf=csrf)
    return status, body


def create_api_token(base, cookie, csrf):
    """ساخت API Token و برگرداندن مقدار آن."""
    status, body = api_call(base, cookie, "/managepanel/panel/api/setting/apiTokens/create",
                            method="POST", data={"name": "hermes-connect", "enabled": True}, csrf=csrf)
    if status != 200:
        return None, f"ساخت توکن ناموفق ({status}): {body[:150]}"
    try:
        obj = json.loads(body).get("obj")
        # obj می‌تواند خود توکن باشد یا شامل token باشد
        if isinstance(obj, dict):
            token = obj.get("token") or obj.get("apiToken") or obj.get("value") or obj.get("secret") or ""
            return token, ""
        return obj, ""
    except Exception as e:
        return None, f"پاسخ نامعتبر: {e}"


def list_api_tokens(base, cookie):
    status, body = api_call(base, cookie, "/managepanel/panel/api/setting/apiTokens")
    try:
        obj = json.loads(body).get("obj")
        return obj
    except Exception:
        return None


def add_node(base, cookie, node_cfg, csrf=None):
    status, body = api_call(base, cookie, "/managepanel/panel/api/nodes/add",
                            method="POST", data=node_cfg, csrf=csrf)
    if status != 200:
        return False, f"({status}) {body[:150]}"
    try:
        ok = json.loads(body).get("success")
        return bool(ok), body[:150]
    except Exception:
        return False, body[:150]


def main():
    print("🔐 اتصال نودهای چند-ریجن 3x-ui\n" + "=" * 45)

    # 1) لاگین به همه پنل‌ها
    sessions = {}
    csrfs = {}
    for name, base in PANELS.items():
        print(f"\n[{name}] لاگین...")
        sess, csrf, err = login(base)
        if not sess:
            print(f"  ❌ {err}")
            continue
        sessions[name] = sess
        csrfs[name] = csrf
        print(f"  ✅ لاگین موفق")

    if MAIN_PANEL not in sessions:
        print("\n❌ پنل اصلی در دسترس نیست — متوقف می‌شوم")
        return 1

    # 2) ساخت API Token برای هر پنل
    tokens = {}
    for name in list(PANELS.keys()):
        if name not in sessions:
            continue
        print(f"\n[{name}] ساخت API Token...")
        # توکن قبلی با اسم hermes-connect را حذف کن (مقدارش را نمی‌دانیم)
        existing = list_api_tokens(PANELS[name], sessions[name])
        if isinstance(existing, list):
            for t in existing:
                if isinstance(t, dict) and t.get("name") == "hermes-connect":
                    api_call(PANELS[name], sessions[name],
                             f"/managepanel/panel/api/setting/apiTokens/delete/{t.get('id')}",
                             method="POST", data={}, csrf=csrfs.get(name, ""))
                    print(f"  🗑 توکن قبلی (id={t.get('id')}) حذف شد")
        token, err = create_api_token(PANELS[name], sessions[name], csrfs.get(name, ""))
        if token:
            tokens[name] = token
            print(f"  ✅ توکن: {str(token)[:30]}...")
        else:
            print(f"  ⚠️ {err}")

    # 3) اضافه کردن نودهای ریموت به پنل اصلی
    print(f"\n{'=' * 45}\n🖥 افزودن نودها به پنل اصلی ({MAIN_PANEL})")
    main_base = PANELS[MAIN_PANEL]
    main_cookie = sessions[MAIN_PANEL]

    for node_name in REMOTE_NODES:
        base = PANELS[node_name]
        token = tokens.get(node_name)
        if not token:
            print(f"\n[{node_name}] ⚠️ توکن در دسترس نیست — رد شد")
            continue
        cfg = {
            "name": node_name,
            "remark": f"3x-ui {node_name}",
            "scheme": "https",
            "address": base.replace("https://", ""),
            "port": 443,
            "basePath": "/managepanel/",
            "apiToken": token,
            "clearApiToken": False,
            "enable": True,
            "allowPrivateAddress": False,
        }
        print(f"\n[{node_name}] افزودن نود...")
        ok, msg = add_node(main_base, main_cookie, cfg, csrfs.get(MAIN_PANEL, ""))
        if ok:
            print(f"  ✅ نود {node_name} اضافه شد!")
        else:
            print(f"  ❌ {msg}")
        time.sleep(1)

    # 4) لیست نهایی نودها
    print(f"\n{'=' * 45}\n📋 لیست نهایی نودها:")
    status, body = api_call(main_base, main_cookie, "/managepanel/panel/api/nodes/list")
    try:
        nodes = json.loads(body).get("obj")
        if not nodes:
            print("  (خالی)")
        for n in nodes:
            if isinstance(n, dict):
                print(f"  • {n.get('name')} — {n.get('address')}:{n.get('port')} — enable={n.get('enable')}")
    except Exception as e:
        print(f"  خطا: {e} | {body[:200]}")

    print("\n🎉 تمام شد!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
