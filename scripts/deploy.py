#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
3x-ui Multi-Region Deployer
===========================
ساخت خودکار ۴ سرویس 3x-ui روی Railway + دامنه‌ی خودکار با پورت 3000.

هر سرویس:
  1) از ریپوی 3xui-multi-region ساخته می‌شود
  2) روی ریجن مشخص (هلند/سنگاپور/ویرجینیا/کالیفرنیا) می‌نشیند
  3) یک دامنه‌ی .up.railway.app با targetPort=3000 می‌گیرد

استفاده:
    export RAILWAY_TOKEN="توکن_اکانت"
    python3 deploy.py                 # همه‌ی سرویس‌ها
    python3 deploy.py xui-nl          # فقط یکی

متغیرها:
    WORKSPACE_ID  (پیش‌فرض: workspace اول حساب)
    PROJECT_ID    (پیش‌فرض: ساخت پروژه‌ی جدید 3xui-multi-region)
    REPO          (پیش‌فرض: Djsjsnsjcjx/railway-3xui-service)
    BRANCH        (پیش‌فرض: main)
    TARGET_PORT   (پیش‌فرض: 3000)
"""

import json
import os
import sys
import urllib.request

TOKEN = os.environ.get("RAILWAY_TOKEN", "")
URL = "https://backboard.railway.com/graphql/v2"
REPO = os.environ.get("REPO", "Djsjsnsjcjx/railway-3xui-service")
BRANCH = os.environ.get("BRANCH", "main")
TARGET_PORT = int(os.environ.get("TARGET_PORT", "3000"))

# (نام سرویس, ریجن, توضیح)
SERVICES = [
    ("xui-nl",     "ams", "🇳🇱 هلند (Amsterdam)"),
    ("xui-sg",     "sin", "🇸🇬 سنگاپور (Singapore)"),
    ("xui-us-va",  "iad", "🇺🇸 آمریکا شرق (Virginia)"),
    ("xui-us-ca",  "sfo", "🇺🇸 آمریکا غرب (San Francisco)"),
]


def gql(query, variables=None):
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(URL, data=body, headers={
        "Authorization": "Bearer " + TOKEN,
        "Content-Type": "application/json",
        "User-Agent": "railway-cli/5.30.4",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def find_workspace():
    d = gql("{ me { workspaces { id name } } }")
    ws = d["data"]["me"]["workspaces"]
    wid = os.environ.get("WORKSPACE_ID")
    if wid:
        return wid
    if ws:
        return ws[0]["id"]
    raise SystemExit("❌ هیچ workspace ای پیدا نشد.")


def find_or_create_project(wid):
    pid = os.environ.get("PROJECT_ID", "")
    if pid:
        return pid
    # دنبال پروژه‌ی موجود با همین اسم بگرد
    d = gql('query($wid: String!){ projects(workspaceId: $wid) { edges { node { id name } } } }',
            {"wid": wid})
    for e in d["data"]["projects"]["edges"]:
        if e["node"]["name"] == "3xui-multi-region":
            print(f"📦 پروژه‌ی موجود: {e['node']['id']}")
            return e["node"]["id"]
    # ساخت پروژه‌ی جدید
    d = gql('mutation($input: ProjectCreateInput!){ projectCreate(input: $input) { id name } }',
            {"input": {"name": "3xui-multi-region", "workspaceId": wid}})
    if "errors" in d:
        raise SystemExit(f"❌ ساخت پروژه: {d['errors'][0]['message']}")
    print(f"📦 پروژه ساخته شد: {d['data']['projectCreate']['id']}")
    return d["data"]["projectCreate"]["id"]


def find_env_id(pid):
    d = gql('query($pid: String!){ environments(projectId: $pid) { edges { node { id name } } } }',
            {"pid": pid})
    envs = d["data"]["environments"]["edges"]
    for e in envs:
        if e["node"]["name"] == "production":
            return e["node"]["id"]
    if envs:
        return envs[0]["node"]["id"]
    raise SystemExit("❌ هیچ environment ای پیدا نشد.")


def create_service(pid, name):
    """ساخت سرویس — اگر سرویس با همین اسم در پروژه هست، دوباره نمی‌سازد.

    نکته: Railway برای اکانت‌های جدید سقف ۲۵ ساخت سرویس در روز دارد؛
    بازیافت سرویس‌های موجود مانع هدر رفتن این سهمیه می‌شود.
    """
    try:
        d = gql('query($id: String!){ project(id: $id) { services { edges { node { id name } } } } }',
                {"id": pid})
        for e in (d.get("data") or {}).get("project", {}).get("services", {}).get("edges", []):
            if e["node"]["name"] == name:
                print(f"  ♻️ سرویس موجود: {name} → {e['node']['id']}")
                return e["node"]["id"]
    except Exception as e:
        print(f"  ⚠️ بررسی سرویس‌های موجود نشد: {e}")
    d = gql(
        'mutation($input: ServiceCreateInput!){ serviceCreate(input: $input) { id name } }',
        {"input": {
            "name": name,
            "projectId": pid,
            "source": {"repo": REPO},
            "branch": BRANCH,
        }})
    if "errors" in d:
        raise SystemExit(f"❌ ساخت سرویس {name}: {d['errors'][0]['message']}")
    return d["data"]["serviceCreate"]["id"]


def set_region(env_id, svc_id, region):
    """تنظیم ریجن — اگر SKIP_REGION=1 باشد رد می‌شود (کاربر دستی تنظیم می‌کند)."""
    if os.environ.get("SKIP_REGION") == "1":
        print("  ⏭️ ریجن: رد شد (SKIP_REGION=1 — کاربر دستی تنظیم می‌کند)")
        return False
    d = gql(
        'mutation($e: String!, $s: String!, $input: ServiceInstanceUpdateInput!){ '
        'serviceInstanceUpdate(environmentId: $e, serviceId: $s, input: $input) }',
        {"e": env_id, "s": svc_id, "input": {"region": region}})
    if "errors" in d:
        print(f"  ⚠️ ریجن: {d['errors'][0]['message']}")
        return False
    return True


def create_domain(env_id, svc_id):
    d = gql(
        'mutation($input: ServiceDomainCreateInput!){ serviceDomainCreate(input: $input) { id domain } }',
        {"input": {
            "environmentId": env_id,
            "serviceId": svc_id,
            "targetPort": TARGET_PORT,
        }})
    if "errors" in d:
        print(f"  ⚠️ دامنه: {d['errors'][0]['message']}")
        return None
    return d["data"]["serviceDomainCreate"]["domain"]


def create_volume(env_id, svc_id, region, mount_path="/etc/x-ui"):
    """ساخت Volume برای حفظ تنظیمات پنل — روی mount_path."""
    d = gql(
        'mutation($input: VolumeCreateInput!){ volumeCreate(input: $input) { id } }',
        {"input": {
            "environmentId": env_id,
            "projectId": os.environ.get("PROJECT_ID", ""),
            "serviceId": svc_id,
            "region": region,
            "mountPath": mount_path,
        }})
    if "errors" in d:
        print(f"  ⚠️ ولوم: {d['errors'][0]['message']}")
        return None
    return d["data"]["volumeCreate"]["id"]


def main():
    if not TOKEN:
        print("❌ RAILWAY_TOKEN را ست کن!")
        return 2

    only = sys.argv[1] if len(sys.argv) > 1 else None

    wid = find_workspace()
    print(f"🏢 Workspace: {wid}")
    pid = find_or_create_project(wid)
    env_id = find_env_id(pid)
    print(f"🌍 Environment: {env_id}")

    results = []
    for name, region, label in SERVICES:
        if only and name != only:
            continue
        print(f"\n🚀 {name} ({label})")
        try:
            svc_id = create_service(pid, name)
            print(f"  ✅ سرویس: {svc_id}")
            if set_region(env_id, svc_id, region):
                print(f"  ✅ ریجن: {region}")
            domain = create_domain(env_id, svc_id)
            if domain:
                print(f"  ✅ دامنه: https://{domain}  (پورت {TARGET_PORT})")
                results.append((name, domain))
            else:
                results.append((name, "دامنه نشد (شاید پلن)"))
            vol_id = create_volume(env_id, svc_id, region)
            if vol_id:
                print(f"  ✅ ولوم: {vol_id}  (مونت روی /etc/x-ui)")
            else:
                print("  ⚠️ ولوم ساخته نشد — تنظیمات بعد از ری‌دیپلوی پاک می‌شوند!")
        except SystemExit as e:
            print(f"  {e}")
            results.append((name, "خطا"))

    print("\n===== SUMMARY =====")
    for name, domain in results:
        print(f"{name}: {domain}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
