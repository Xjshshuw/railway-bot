#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
لینک‌ساز VLESS+Reality — لینک‌های درست هر ۴ سرور با TCP proxy.
اسم هر کانفیگ = لوکیشن سرور (پرچم + کشور + شهر) تا توی کلاینت قابل تشخیص باشد.

استفاده:
    python3 xui-link-maker.py <UUID>
    یا
    export XUI_UUID="..." && python3 xui-link-maker.py

نکته: لینک‌هایی که خود پنل 3x-ui می‌سازد کار نمی‌کنند چون:
  - دامنه‌های .up.railway.app TLS خود Railway را تحمیل می‌کنند (x509 mismatch)
  - پورت اینباند (443) با پورت TCP proxy فرق دارد
  این اسکریپت آدرس TCP proxy + پورت درست را استفاده می‌کند.
"""

import json
import os
import sys

SNI = "is1-ssl.mzstatic.com"
FP = "ios"
TYPE = "tcp"

# fallback (استفادهٔ دستی) — در حالت ربات، SERVERS_JSON از ستاپ واقعی می‌آید
DEFAULT_SERVERS = [
    {"name": "NL", "host": "reseau.proxy.rlwy.net", "port": 25816, "pbk": "BRmgS2SxcaLw-cUXm6buHTCdE6wP1nWHU_qPkmKuzGA", "sid": "6fd63174", "label": "🇳🇱 Netherlands (Amsterdam)"},
    {"name": "SG", "host": "turntable.proxy.rlwy.net", "port": 16139, "pbk": "0Tyvs8SuDmRyHym-dj-fxxOtJ8xVIsFdh0Dby6zEnUE", "sid": "96726748", "label": "🇸🇬 Singapore"},
    {"name": "US-VA", "host": "autorack.proxy.rlwy.net", "port": 58343, "pbk": "j5JvDvTAvjar_b_M2RNmeGlIoCss9zNgtbqN5GspAnA", "sid": "e7be5aa5", "label": "🇺🇸 USA (Virginia)"},
    {"name": "US-CA", "host": "reseau.proxy.rlwy.net", "port": 54117, "pbk": "ewVcmLWfMq3xIyOrmDApg7FstfHhQuHUaB_wDHPbzHA", "sid": "73548b14", "label": "🇺🇸 USA (California)"},
]


def main():
    uuid_val = os.environ.get("XUI_UUID", "")
    if len(sys.argv) > 1:
        uuid_val = sys.argv[1]
    if not uuid_val:
        print("❌ UUID را بده:  python3 xui-link-maker.py <UUID>")
        return 1

    # سرورها: اول SERVERS_JSON (از ربات — داده‌های واقعی ستاپ)، وگرنه fallback
    servers = DEFAULT_SERVERS
    raw = os.environ.get("SERVERS_JSON", "")
    if raw:
        try:
            servers = json.loads(raw)
        except Exception as e:
            print(f"⚠️ SERVERS_JSON خوانده نشد ({e}) — از fallback استفاده می‌شود")

    print(f"🔗 لینک‌های اتصال (UUID: {uuid_val})\n" + "=" * 55)
    for s in servers:
        name = s["name"]
        host = s["host"]
        port = s["port"]
        pbk = s["pbk"]
        sid = s["sid"]
        label = s.get("label", name)
        # اسم کانفیگ = لوکیشن (با پرچم) — URL-encode فاصله‌ها
        tag = label.replace(" ", "%20")
        link = (f"vless://{uuid_val}@{host}:{port}"
                f"?encryption=none&security=reality&sni={SNI}&fp={FP}"
                f"&pbk={pbk}&sid={sid}&type={TYPE}&headerType=none"
                f"#{tag}")
        print(f"\n{label}:")
        print(f"  {link}")
    print("\n")
    print("📌 اسم هر کانفیگ توی v2rayNG = لوکیشن (پرچم + کشور)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
