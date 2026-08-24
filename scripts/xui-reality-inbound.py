#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
3x-ui Reality Inbound Creator (Standard)
========================================
ساخت اینباند VLESS + TCP + Reality روی همه پنل‌ها با مشخصات ثابت.

مشخصات ثابت اینباند (که باید روی همه پنل‌ها یکسان باشد):
  - پورت:      443
  - پروتکل:    vless
  - شبکه:      tcp (raw)
  - امنیت:     reality
  - Target:    is1-ssl.mzstatic.com:443
  - serverNames: is1..is5.ssl.mzstatic.com
  - فینگرپرینت: ios
  - بقیه تنظیمات: پیش‌فرض خود پنل (دست نمی‌خورد)

نکته‌ها:
  - اگر پنل از قبل اینباند پورت 443 داشته باشد، رد می‌شود (تکراری نمی‌سازد!)
  - هر پنل یک UUID و keypair متفاوت می‌گیرد
  - پنل‌ها از متغیر محیطی PANELS خوانده می‌شوند:
      PANELS="xui-nl=https://...;xui-sg=https://...;..."
    یا اگر ست نشده باشد از PANELS_FALLBACK استفاده می‌شود

استفاده:
    export PANELS="xui-nl=https://...;xui-sg=https://..."
    python3 xui-reality-inbound.py
"""

import base64
import json
import os
import sys
import time
import urllib.request
import urllib.error
import uuid

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives import serialization

# ── تنظیمات ثابت ───────────────────────────────────────
PORT = 443
PROTOCOL = "vless"
NETWORK = "tcp"
SECURITY = "reality"
TARGET = "is1-ssl.mzstatic.com:443"
SERVER_NAMES = [
    "is3-ssl.mzstatic.com",
    "is1-ssl.mzstatic.com",
    "is4-ssl.mzstatic.com",
    "is2-ssl.mzstatic.com",
    "is5-ssl.mzstatic.com",
]
FINGERPRINT = "ios"
REMARK = "VLESS-Reality-443"

# نام لوکیشنی هر پنل — برای اینکه توی پنل/ساب اسم درست دیده شود
# نام پنل (کلید PANELS) → اسم لوکیشن (پرچم + کشور + شهر)
LOCATION_NAMES = {
    "xui-nl":    "🇳🇱 Netherlands (Amsterdam)",
    "xui-sg":    "🇸🇬 Singapore",
    "xui-us-va": "🇺🇸 USA (Virginia)",
    "xui-us-ca": "🇺🇸 USA (California)",
}

def location_name(name):
    """اسم لوکیشنی پنل — اگر در نقشه نبود همان نام را برمی‌گرداند."""
    return LOCATION_NAMES.get(name, name)

USERNAME = os.environ.get("XUI_USERNAME", "admin")
PASSWORD = os.environ.get("XUI_PASSWORD", "admin")

# پنل‌ها: از env، یا فالبک پیش‌فرض
PANELS_FALLBACK = {
    "xui-nl": "https://xui-nl-production-a29c.up.railway.app",
    "xui-sg": "https://xui-sg-production-434c.up.railway.app",
    "xui-us-va": "https://xui-us-va-production-3d26.up.railway.app",
    "xui-us-ca": "https://xui-us-ca-production-4c58.up.railway.app",
}


def parse_panels():
    raw = os.environ.get("PANELS", "")
    panels = {}
    if raw:
        for part in raw.split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                panels[k.strip()] = v.strip()
    return panels or PANELS_FALLBACK


PANELS = parse_panels()


def gen_keypair():
    """تولید X25519 keypair برای Reality."""
    priv = X25519PrivateKey.generate()
    priv_b64 = base64.urlsafe_b64encode(priv.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
        serialization.NoEncryption())).decode().rstrip("=")
    pub_b64 = base64.urlsafe_b64encode(priv.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode().rstrip("=")
    return priv_b64, pub_b64


def gen_short_id():
    """شناسه کوتاه reality (8 کاراکتر hex)."""
    return os.urandom(4).hex()


def req(base, path, method="GET", data=None, cookie=None, csrf=None, timeout=20):
    url = base + path
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
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


def login(base):
    resp = urllib.request.urlopen(urllib.request.Request(
        base + "/managepanel/", headers={"User-Agent": "Mozilla/5.0"}), timeout=15)
    cookie = resp.headers.get("Set-Cookie", "").split(";")[0]
    resp.close()
    status, _, body = req(base, "/managepanel/csrf-token", cookie=cookie)
    csrf1 = json.loads(body).get("obj", "")
    status, hdrs, body = req(base, "/managepanel/login", method="POST",
                             data={"username": USERNAME, "password": PASSWORD},
                             cookie=cookie, csrf=csrf1)
    if status != 200:
        return None, None
    sess = hdrs.get("Set-Cookie", "").split(";")[0] if hdrs.get("Set-Cookie") else cookie
    status, _, body = req(base, "/managepanel/csrf-token", cookie=sess)
    csrf = json.loads(body).get("obj", "")
    return sess, csrf


def has_port443(base, cookie, csrf):
    """چک: آیا پنل از قبل اینباند پورت 443 دارد؟ (جلوگیری از تکرار)"""
    status, _, body = req(base, "/managepanel/panel/api/inbounds/list", cookie=cookie, csrf=csrf)
    try:
        inbounds = json.loads(body).get("obj", [])
        for ib in inbounds:
            if isinstance(ib, dict) and ib.get("port") == PORT:
                return True, ib
    except Exception:
        pass
    return False, None


def build_inbound(priv=None, pub=None, short_id=None, client_id=None, name=""):
    """ساخت payload اینباند.

    اگر priv/pub/short_id داده شود (کلید مشترک از پنل اصلی)، همه پنل‌ها
    همان کلید را می‌گیرند → «۴ تا در، ۱ قفل مشترک» — لینک روی همه کار می‌کند.
    remark از location_name(name) گرفته می‌شود تا اسم لوکیشن در پنل/ساب دیده شود.
    """
    if not (priv and pub and short_id):
        priv, pub = gen_keypair()
        short_id = gen_short_id()
    if not client_id:
        client_id = str(uuid.uuid4())

    inbound = {
        "enable": True,
        "remark": location_name(name) if name else REMARK,
        "listen": "",
        "port": PORT,
        "protocol": PROTOCOL,
        "expiryTime": 0,
        "total": 0,
        "settings": {
            "clients": [{"id": client_id, "email": "amir"}],
            "decryption": "none",
            "fallbacks": []
        },
        "streamSettings": {
            "network": NETWORK,
            "security": SECURITY,
            "realitySettings": {
                "show": False,
                "dest": TARGET,
                "serverNames": SERVER_NAMES,
                "privateKey": priv,
                "shortIds": [short_id],
                "settings": {
                    "publicKey": pub,
                    "fingerprint": FINGERPRINT,
                    "serverName": "",
                    "spiderX": ""
                },
                "xver": 0
            }
        },
        "sniffing": {"enabled": True, "destOverride": ["http", "tls"]}
    }
    return inbound, client_id, pub, short_id


def main():
    print(f"🔐 ساخت اینباند استاندارد (VLESS+Reality :{PORT} → {TARGET})\n" + "=" * 55)
    print("🧬 حالت: کلید مشترک — همه پنل‌ها یک privateKey می‌گیرند (۴ در، ۱ قفل)\n")

    # نام پنل اصلی (مرجع کلیدها) — از env یا اولین پنل
    main_name = os.environ.get("MAIN_PANEL", "")
    if not main_name:
        main_name = next(iter(PANELS))
    results = {}

    # ۱) ساخت/خواندن اینباند روی پنل اصلی → کلید مرجع
    print(f"[{main_name}] (پنل اصلی — مرجع کلیدها)")
    sess, csrf = login(PANELS[main_name])
    if not sess:
        print(f"  ❌ لاگین ناموفق — بدون مرجع کلید ادامه نمی‌دهم")
        return 1
    exists, ib = has_port443(PANELS[main_name], sess, csrf)
    if exists:
        rs = ib.get("streamSettings", {}).get("realitySettings", {})
        master = {
            "priv": rs.get("privateKey"),
            "pub": rs.get("settings", {}).get("publicKey"),
            "sid": (rs.get("shortIds") or [""])[0],
        }
        clients = ib.get("settings", {}).get("clients", [])
        master["uuid"] = clients[0]["id"] if clients else str(uuid.uuid4())
        print(f"  ⏭️ اینباند 443 از قبل هست — کلیدهایش مرجع شدند")
    else:
        print(f"  📡 ساخت اینباند مرجع...")
        inbound, client_id, pub, short_id = build_inbound(name=main_name)
        status, _, body = req(PANELS[main_name], "/managepanel/panel/api/inbounds/add",
                              method="POST", data=inbound, cookie=sess, csrf=csrf)
        if status != 200 or '"success":true' not in body:
            print(f"  ❌ خطا ({status}): {body[:200]}")
            return 1
        rs = inbound["streamSettings"]["realitySettings"]
        master = {
            "priv": rs["privateKey"],
            "pub": rs["settings"]["publicKey"],
            "sid": short_id,
            "uuid": client_id,
        }
        print(f"  ✅ اینباند مرجع ساخته شد! (UUID: {client_id})")
    print(f"  🔑 PublicKey: {master['pub']}")
    print(f"  🏷 ShortId: {master['sid']}")
    results[main_name] = {"uuid": master["uuid"], "pub": master["pub"],
                          "short_id": master["sid"],
                          "address": PANELS[main_name].replace("https://", "")}
    time.sleep(1)

    # ۲) ساخت روی بقیه پنل‌ها با همان کلید مشترک
    for name, base in PANELS.items():
        if name == main_name:
            continue
        print(f"\n[{name}] لاگین...")
        sess, csrf = login(base)
        if not sess:
            print(f"  ❌ لاگین ناموفق")
            continue
        print(f"  ✅ لاگین موفق")

        exists, ib = has_port443(base, sess, csrf)
        if exists:
            print(f"  ⏭️ اینباند 443 از قبل هست (id={ib.get('id')} | {ib.get('remark')}) — رد شد")
            # اگر هست ولی کلیدش فرق دارد، آپدیتش کن به کلید مشترک
            rs = ib.get("streamSettings", {}).get("realitySettings", {})
            if rs.get("settings", {}).get("publicKey") != master["pub"]:
                print(f"  🔄 کلید اینباند با مرجع فرق دارد — هماهنگ می‌کنم...")
                ib["streamSettings"]["realitySettings"]["privateKey"] = master["priv"]
                ib["streamSettings"]["realitySettings"]["settings"]["publicKey"] = master["pub"]
                ib["streamSettings"]["realitySettings"]["shortIds"] = [master["sid"]]
                status, _, body = req(base, f"/managepanel/panel/api/inbounds/update/{ib.get('id')}",
                                      method="POST", data=ib, cookie=sess, csrf=csrf)
                ok = status == 200 and '"success":true' in body
                print(f"  {'✅ هماهنگ شد!' if ok else '❌ ' + body[:120]}")
            results[name] = {"skipped": True, "inbound": ib}
            continue

        print(f"  📡 ساخت اینباند با کلید مشترک...")
        inbound, client_id, pub, short_id = build_inbound(
            priv=master["priv"], pub=master["pub"], short_id=master["sid"], name=name)
        status, _, body = req(base, "/managepanel/panel/api/inbounds/add",
                              method="POST", data=inbound, cookie=sess, csrf=csrf)
        if status == 200 and '"success":true' in body:
            print(f"  ✅ اینباند ساخته شد! (کلید مشترک ✓)")
            results[name] = {"uuid": client_id, "pub": pub, "short_id": short_id,
                             "address": base.replace("https://", "")}
        else:
            print(f"  ❌ خطا ({status}): {body[:200]}")
        time.sleep(1)

    print(f"\n{'=' * 55}\n📋 خلاصه (همه با کلید مشترک):")
    for name, info in results.items():
        if info.get("skipped"):
            print(f"\n⏭️ {name}: اینباند از قبل بود")
            continue
        print(f"\n🔗 {name}:")
        print(f"   vless://{info['uuid']}@{info['address']}:{PORT}?encryption=none&security=reality&sni=is1-ssl.mzstatic.com&fp={FINGERPRINT}&pbk={info['pub']}&sid={info['short_id']}&type=tcp&headerType=none#VLESS-Reality-{name}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
