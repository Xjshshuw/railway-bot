#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
3x-ui Client Creator
====================
ساخت کلاینت در پنل اصلی (اینباند VLESS+Reality پورت 443) با اسم دلخواه کاربر
و خروجی لینک ساب (فرمت اصلی + فرمت https بدون پورت).

استفاده:
    export PANELS="xui-nl=https://...;xui-sg=https://..."
    export MAIN_PANEL="xui-nl"
    export CLIENT_NAME="اسم دلخواه"
    python3 xui-client-create.py

خروجی:
    UUID=<uuid>
    SUB_LINK=<لینک ساب اصلی مثلاً http://host:port/sub/xxx>
    SUB_LINK_HTTPS=<https://host/sub/xxx>
"""

import json
import os
import sys
import uuid as uuid_mod
import urllib.parse
import urllib.request
import urllib.error


def _parse_panels():
    raw = os.environ.get("PANELS", "")
    panels = {}
    if raw:
        for part in raw.split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                panels[k.strip()] = v.strip()
    return panels


PANELS = _parse_panels()
MAIN_PANEL = os.environ.get("MAIN_PANEL", "xui-nl")
USERNAME = os.environ.get("XUI_USERNAME", "admin")
PASSWORD = os.environ.get("XUI_PASSWORD", "admin")
CLIENT_NAME = os.environ.get("CLIENT_NAME", "").strip()
PORT = 443


def req(base, path, method="GET", data=None, cookie=None, csrf=None, form=False, timeout=20):
    url = base + path
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
        "Accept": "application/json",
    }
    body = None
    if data is not None:
        if form:
            body = urllib.parse.urlencode(data).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
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
    status, _, body = req(base, "/managepanel/csrf-token", cookie=sess)
    try:
        csrf = json.loads(body).get("obj", "")
    except Exception:
        pass
    return sess, csrf, ""


def to_https_no_port(url):
    """http://host:port/sub/xxx → https://host/sub/xxx"""
    p = urllib.parse.urlparse(url)
    host = p.hostname or ""
    return urllib.parse.urlunparse(("https", host, p.path or "", "", p.query, ""))


def main():
    if not CLIENT_NAME:
        print("❌ CLIENT_NAME را ست کن!")
        return 1
    if MAIN_PANEL not in PANELS:
        print(f"❌ پنل اصلی «{MAIN_PANEL}» در PANELS نیست")
        return 1

    base = PANELS[MAIN_PANEL]
    print(f"🔐 لاگین به {MAIN_PANEL} ({base})...")
    sess, csrf, err = login(base)
    if not sess:
        print(f"❌ لاگین نشد: {err}")
        return 1

    # اینباند پورت 443 (Reality)
    status, body = req(base, "/managepanel/panel/api/inbounds/list", cookie=sess, csrf=csrf)
    if status != 200:
        print(f"❌ لیست اینباند ({status}): {body[:150]}")
        return 1
    inbounds = json.loads(body).get("obj", [])
    ib = next((x for x in inbounds if isinstance(x, dict) and x.get("port") == PORT), None)
    if not ib:
        print(f"❌ اینباند پورت {PORT} پیدا نشد")
        return 1

    client_id = str(uuid_mod.uuid4())
    settings = {
        "clients": [{
            "id": client_id,
            "email": CLIENT_NAME,
            "limitIp": 0,
            "totalGB": 0,
            "expiryTime": 0,
            "enable": True,
            "tgId": "",
            "subId": "",
            "reset": 0,
        }]
    }

    print(f"👤 ساخت کلاینت «{CLIENT_NAME}» روی اینباند id={ib['id']}...")
    status, body = req(base, "/managepanel/panel/api/inbounds/addClient",
                       method="POST",
                       data={"id": ib["id"], "settings": json.dumps(settings)},
                       cookie=sess, csrf=csrf, form=True)
    if status != 200:
        print(f"❌ addClient ({status}): {body[:200]}")
        return 1
    try:
        resp = json.loads(body)
    except Exception:
        resp = {}
    if not resp.get("success"):
        print(f"❌ addClient رد شد: {body[:250]}")
        return 1

    # لینک ساب — اول از پاسخ addClient، بعد از لیست
    sub = ""
    obj = resp.get("obj")
    if isinstance(obj, dict):
        sub = obj.get("sub") or ""
    if not sub:
        status, body = req(base, "/managepanel/panel/api/inbounds/list", cookie=sess, csrf=csrf)
        try:
            inbounds = json.loads(body).get("obj", [])
        except Exception:
            inbounds = []
        for x in inbounds:
            if isinstance(x, dict) and x.get("port") == PORT:
                for c in (x.get("settings") or {}).get("clients", []):
                    if c.get("id") == client_id:
                        sub = c.get("sub") or ""
                        break

    print(f"UUID={client_id}")
    if not sub:
        print("✅ کلاینت ساخته شد ولی لینک ساب برنگشت — از پنل چک کن.")
        return 0
    print(f"SUB_LINK={sub}")
    print(f"SUB_LINK_HTTPS={to_https_no_port(sub)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
