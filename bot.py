#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🤖 Railway 3x-ui Bot — نسخه ۳ (چند اکانت + TCP Proxy)
======================================================
ربات تلگرامی که کل فرایند راه‌اندازی 3x-ui چند-ریجن روی Railway را انجام می‌دهد:

  مرحله ۱: کاربر توکن Railway می‌دهد (چند اکانت قابل ثبت است)
  مرحله ۲: ساخت پروژه + ۴ سرویس (بدون ریجن)
  مرحله ۳: کاربر ریجن‌ها را در داشبورد تنظیم می‌کند
  مرحله ۴: اتصال نودها به پنل مرکزی
  مرحله ۵: ساخت اینباند VLESS+Reality (کلید مشترک)
  مرحله ۶: TCP proxy + روتیت به دامنه خوب + Host ها
  مرحله ۷: تحویل لینک‌ها

امکانات اضافه:
  👥 مدیریت چند اکانت Railway (افزودن / سوییچ / حذف)
  🌐 چرخش TCP Proxy بعد از ستاپ — هوشمند (دامنه‌های تأیید) یا رندوم،
     برای همه ریجن‌ها یا تک‌ریجن (همان سیستم Kolkolz/railway-tcp-proxy-rotator)

اجرا روی Railway (Docker) — متغیر محیطی BOT_TOKEN لازم است.
"""

import asyncio
import html
import json
import logging
import os
import re
import subprocess
import sys
import time
import urllib.request
import urllib.error
from urllib.parse import quote, unquote

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# ── تنظیمات ────────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
SCRIPT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts")
RAILWAY_URL = "https://backboard.railway.com/graphql/v2"
REPO = os.environ.get("REPO", "Djsjsnsjcjx/railway-3xui-service")
BRANCH = os.environ.get("BRANCH", "main")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ── ذخیره وضعیت کاربران (در حافظه — ساده) ─────────────
# user_id → {
#   "accounts": { name: {token, workspace_id, project_id, env_id, domains,
#                        panel_urls, reality_keys, proxy_map, servers_json,
#                        service_ids, awaiting_client_name} },
#   "active_account": name,
#   "awaiting_acc_name": bool, "pending_acc_name": str, "awaiting_acc_token": bool,
# }
USERS = {}

# دامنه‌های تأیید (همان لیست ۱۲تایی rotator)
GOOD_DOMAINS = "monorail,nozomi,turntable,trolley,reseau,autorack,metro,hopper,kodama,interchange,switchyard,junction"

LABELS = {
    "xui-nl": "🇳🇱 هلند (Amsterdam)",
    "xui-sg": "🇸🇬 سنگاپور (Singapore)",
    "xui-us-va": "🇺🇸 آمریکا (Virginia)",
    "xui-us-ca": "🇺🇸 آمریکا (California)",
}

# ══════════════ استایل / UI ══════════════
HTML = ParseMode.HTML
SEP = "━" * 24
SEP2 = "┄" * 24
TOTAL_STEPS = 7


def esc(t):
    """فرار از کاراکترهای HTML (برای ورودی کاربر و خروجی اسکریپت‌ها)."""
    return html.escape(str(t))


def bar(step):
    """نوار پیشرفت ▰▱"""
    step = max(0, min(TOTAL_STEPS, int(step)))
    return "▰" * step + "▱" * (TOTAL_STEPS - step)


def card(title, body, emoji="✨", footer=None):
    """یک «کارت» شیک برای پیام‌ها."""
    lines = [f"{emoji} <b>{esc(title)}</b>", SEP, body]
    if footer:
        lines += [SEP2, footer]
    return "\n".join(lines)


def pre(text):
    """بلوک کد monospace امن."""
    return "<pre>" + esc(text) + "</pre>"


# ══════════════ اکانت‌ها ══════════════
def get_acc(user):
    """اکانت فعال کاربر — دیکشنری وضعیت آن اکانت."""
    if not user:
        return None
    name = user.get("active_account") or ""
    return user.get("accounts", {}).get(name) or {}


def cb(prefix, value):
    """ساخت callback_data امن — مقدار URL-encode می‌شود."""
    return f"{prefix}:{quote(str(value), safe='')}"


def uncb(data):
    """استخراج مقدار از callback_data."""
    return unquote(data.split(":", 1)[1])


# ── منوها ────────────────────────────────────────────
MAIN_MENU = ReplyKeyboardMarkup([
    [KeyboardButton("🚀 شروع Setup")],
    [KeyboardButton("👥 اکانت‌ها"), KeyboardButton("🌐 TCP Proxy")],
    [KeyboardButton("👤 ساخت کلاینت"), KeyboardButton("📋 وضعیت")],
    [KeyboardButton("🆘 راهنما"), KeyboardButton("🔄 ریست")],
    [KeyboardButton("❌ لغو")],
], resize_keyboard=True)

CONTINUE_KBD = InlineKeyboardMarkup([[
    InlineKeyboardButton("✅ ریجن‌ها تنظیم شد — ادامه", callback_data="cont_setup"),
]])

CLIENT_KBD = InlineKeyboardMarkup([[
    InlineKeyboardButton("👤 ساخت کلاینت", callback_data="menu_client"),
]])

WELCOME_KBD = InlineKeyboardMarkup([
    [InlineKeyboardButton("🚀 شروع Setup", callback_data="start_setup")],
    [InlineKeyboardButton("📋 وضعیت", callback_data="menu_status"),
     InlineKeyboardButton("🆘 راهنما", callback_data="menu_help")],
])


def accounts_kbd(user):
    """کیبورد inline مدیریت اکانت‌ها.

    نکته: callback_data تلگرام حداکثر ۶۴ بایت است — اسم‌های فارسی URL-encode
    شده از آن رد می‌شوند، پس به هر اسم یک کلید کوتاه (a1, a2, ...) می‌دهیم
    و نگاشت را در user['cb_names'] نگه می‌داریم.
    """
    names = list(user.get("accounts", {}))
    cb_map = {}
    rows = []
    for i, name in enumerate(names, 1):
        key = f"a{i}"
        cb_map[key] = name
        active = "🟢" if name == user.get("active_account") else "○"
        rows.append([
            InlineKeyboardButton(f"{active} {name}", callback_data=cb("acc_switch", key)),
            InlineKeyboardButton("🗑 حذف", callback_data=cb("acc_del", key)),
        ])
    user["cb_names"] = cb_map
    rows.append([
        InlineKeyboardButton("➕ افزودن اکانت", callback_data="acc_add"),
        InlineKeyboardButton("🔙 بازگشت", callback_data="acc_back"),
    ])
    return InlineKeyboardMarkup(rows)


def acc_name_from_key(user, key):
    """تبدیل کلید کوتاه callback به اسم واقعی اکانت."""
    if not user:
        return key or ""
    return (user.get("cb_names") or {}).get(key) or key or ""


# ══════════════ Railway GraphQL ══════════════
def gql(token, query, variables=None):
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(RAILWAY_URL, data=body, headers={
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
        "User-Agent": "railway-cli/5.30.4",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def get_workspace_id(token):
    d = gql(token, "{ me { workspaces { id name } } }")
    ws = d["data"]["me"]["workspaces"]
    if not ws:
        return None
    # workspace اول — یا اونی که اسمش پروژه‌های 3xui داره
    for w in ws:
        if "xui" in w["name"].lower():
            return w["id"]
    return ws[0]["id"]


def create_project(token, wid, name="3xui-multi-region"):
    d = gql(token, 'mutation($input: ProjectCreateInput!){ projectCreate(input: $input) { id name } }',
            {"input": {"name": name, "workspaceId": wid}})
    if "errors" in d:
        raise Exception(d["errors"][0]["message"])
    return d["data"]["projectCreate"]["id"]


def get_env_id(token, pid):
    d = gql(token, 'query($pid: String!){ environments(projectId: $pid) { edges { node { id name } } } }',
            {"pid": pid})
    envs = d["data"]["environments"]["edges"]
    for e in envs:
        if e["node"]["name"] == "production":
            return e["node"]["id"]
    return envs[0]["node"]["id"] if envs else None


def get_project_url(token, pid):
    """ساخت لینک داشبورد پروژه."""
    return f"https://railway.app/project/{pid}"


def find_or_create_project(token, wid):
    """پروژه 3xui-multi-region با کمتر از ۴ سرویس xui را پیدا کن؛ وگرنه بساز.

    قبلاً هر /setup یک پروژه جدید می‌ساخت — برای اکانت‌های جدید که سقف
    ۲۵ ساخت سرویس در روز دارند، این یعنی هدر رفتن سریع سهمیه. حالا
    پروژه‌ی ناقص قبلی بازیافت می‌شود و فقط سرویس‌های کم‌شده ساخته می‌شوند.
    """
    d = gql(token, 'query($wid: String!){ projects(workspaceId: $wid) { edges { node { id name createdAt } } } }',
            {"wid": wid})
    projs = [e["node"] for e in d["data"]["projects"]["edges"]
             if e["node"]["name"] == "3xui-multi-region"]
    for p in sorted(projs, key=lambda x: x.get("createdAt") or "", reverse=True):
        try:
            dd = gql(token, 'query($id: String!){ project(id: $id) { services { edges { node { id name } } } } }',
                     {"id": p["id"]})
            svcs = dd["data"]["project"]["services"]["edges"]
            xui_count = sum(1 for e in svcs if (e["node"]["name"] or "").startswith("xui-"))
        except Exception:
            continue
        if xui_count < 4:
            return p["id"]
    return create_project(token, wid)


# ══════════════ اجرای اسکریپت‌ها ══════════════
def run_script(script, env_extra, timeout=900):
    """اجرای یکی از اسکریپت‌های پوشه scripts و برگرداندن خروجی."""
    env = dict(os.environ)
    env.update(env_extra)
    script_path = os.path.join(SCRIPT_DIR, script)
    proc = subprocess.run(
        [sys.executable, script_path],
        capture_output=True, text=True, env=env, timeout=timeout,
    )
    return proc.returncode, proc.stdout, proc.stderr


def extract_lines(text, patterns):
    """استخراج خطوطی که با الگوها مطابقت دارند."""
    out = []
    for line in (text or "").splitlines():
        for p in patterns:
            if p in line:
                out.append(line.strip())
                break
    return out


# ══════════════ هندلرهای تلگرام ══════════════
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = (update.effective_user.first_name or "دوست عزیز")
    text = card(
        "ربات راه‌انداز 3x-ui | Railway",
        f"سلام {esc(name)} 👋\n\n"
        "این ربات کل فرایند ساخت زیرساخت چند-ریجن را خودکار انجام می‌دهد:\n\n"
        "📦 <b>۱.</b> ساخت پروژه + ۴ سرویس (🇳🇱 🇸🇬 🇺🇸)\n"
        "🔗 <b>۲.</b> اتصال نودها به پنل مرکزی\n"
        "🛡️ <b>۳.</b> اینباند VLESS + Reality (کلید مشترک)\n"
        "🌐 <b>۴.</b> TCP Proxy + دامنه خوب\n"
        "🎁 <b>۵.</b> تحویل لینک‌ها\n\n"
        "👥 <b>اکانت‌ها:</b> می‌توانی چند اکانت Railway ثبت کنی و بین‌شان سوییچ کنی\n"
        "🌐 <b>TCP Proxy:</b> بعد از ستاپ، دامنه هر ریجن را هوشمند یا رندوم عوض کن\n\n"
        "🎯 <b>شروع:</b> اول توکن Railway را بفرست\n"
        "(<code>Railway → Settings → Tokens → New Token</code> — دسترسی Account)",
        emoji="🤖",
        footer="از دکمه‌های منو استفاده کن یا /help",
    )
    await update.effective_message.reply_text(text, parse_mode=HTML, reply_markup=MAIN_MENU)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = card(
        "راهنمای ربات",
        "🎛️ <b>دکمه‌های منو:</b>\n"
        "  🚀 <b>شروع Setup</b> — ساخت پروژه + سرویس‌ها (اکانت فعال)\n"
        "  👥 <b>اکانت‌ها</b> — افزودن / سوییچ / حذف اکانت Railway\n"
        "  🌐 <b>TCP Proxy</b> — چرخش دامنه پروکسی‌ها (هوشمند یا رندوم)\n"
        "  👤 <b>ساخت کلاینت</b> — ساخت کلاینت و لینک ساب\n"
        "  📋 <b>وضعیت</b> — وضعیت فعلی ستاپ\n"
        "  🆘 <b>راهنما</b> — همین راهنما\n"
        "  🔄 <b>ریست</b> — پاک کردن وضعیت\n"
        "  ❌ <b>لغو</b> — لغو و شروع دوباره\n\n"
        "⌨️ <b>دستورات:</b>\n"
        "  /start — منوی اصلی\n"
        "  /setup — شروع Setup\n"
        "  /continue — ادامه (بعد از تنظیم ریجن‌ها)\n"
        "  /client اسم — ساخت کلاینت\n"
        "  /status — وضعیت\n"
        "  /cancel — لغو\n\n"
        "💡 <b>نکته:</b> بعد از /setup باید ریجن سرویس‌ها را در داشبورد Railway تنظیم کنی،\n"
        "بعد دکمه «ادامه» را بزن یا /continue بفرست.\n"
        "بعد از چرخش TCP Proxy، لینک‌های قبلی نامعتبر می‌شوند — UUID را بفرست تا لینک‌های جدید بگیری.",
        emoji="🆘",
    )
    await update.effective_message.reply_text(text, parse_mode=HTML, reply_markup=MAIN_MENU)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پیام‌های متنی — دکمه‌های منو / نام اکانت / توکن / UUID.

    نکته: یک هندلر واحد است چون در python-telegram-bot v21 از هر گروه فقط
    اولین هندلرِ match شده اجرا می‌شود.
    """
    uid = update.effective_user.id
    user = USERS.get(uid)
    acc = get_acc(user)
    text = (update.effective_message.text or "").strip()

    # ۱) دکمه‌های منو
    if text == "🚀 شروع Setup":
        await setup(update, context)
        return
    if text == "👥 اکانت‌ها":
        await acc_menu(update, context)
        return
    if text == "🌐 TCP Proxy":
        await tcp_menu(update, context)
        return
    if text == "👤 ساخت کلاینت":
        await client_cmd(update, context)
        return
    if text == "📋 وضعیت":
        await status(update, context)
        return
    if text == "🆘 راهنما":
        await help_cmd(update, context)
        return
    if text == "🔄 ریست":
        USERS.pop(uid, None)
        await update.effective_message.reply_text(
            "🔄 <b>وضعیت ریست شد.</b>\nتوکن جدید بفرست یا دوباره از منو شروع کن.",
            parse_mode=HTML,
        )
        return
    if text == "❌ لغو":
        await cancel(update, context)
        return

    # ۱.۵) نام اکانت جدید (هر متنی قبول است — حداکثر ۱۲ کاراکتر برای callback_data)
    if user and user.get("awaiting_acc_name"):
        name = text[:12].strip() or "اکانت"
        if name in user.get("accounts", {}):
            await update.effective_message.reply_text(
                f"⚠️ اکانت با اسم «{esc(name)}» قبلاً هست — اسم دیگری بفرست.",
                parse_mode=HTML,
            )
            return
        user["pending_acc_name"] = name
        user["awaiting_acc_name"] = False
        user["awaiting_acc_token"] = True
        await update.effective_message.reply_text(
            f"✅ اسم «{esc(name)}» ثبت شد.\n\n"
            "حالا <b>توکن Railway</b> آن اکانت را بفرست:\n"
            "(<code>Railway → Settings → Tokens → New Token</code>)",
            parse_mode=HTML,
        )
        return

    # ۱.۷) توکن برای اکانت جدید (وقتی در حالت افزودن باشیم)
    if user and user.get("awaiting_acc_token") and len(text) >= 30:
        user["awaiting_acc_token"] = False
        name = user.pop("pending_acc_name", "اکانت")
        USERS[uid]["accounts"][name] = {"token": text}
        await update.effective_message.reply_text(
            f"⏳ در حال بررسی توکن «{esc(name)}»…",
            parse_mode=HTML,
        )
        try:
            wid = get_workspace_id(text)
            if not wid:
                USERS[uid]["accounts"].pop(name, None)
                await update.effective_message.reply_text(
                    "❌ <b>توکن معتبر نیست</b> یا دسترسی ندارد!\n"
                    "توکن جدید از Railway → Settings → Tokens بساز.",
                    parse_mode=HTML,
                )
                return
            USERS[uid]["accounts"][name]["workspace_id"] = wid
            USERS[uid]["active_account"] = name
            await update.effective_message.reply_text(
                card(
                    "اکانت اضافه شد",
                    f"✅ اکانت «{esc(name)}» ثبت و <b>فعال</b> شد!\n"
                    f"(workspace: <code>{esc(wid)}</code>)\n\n"
                    "حالا می‌توانی دکمه <b>🚀 شروع Setup</b> را بزنی.",
                    emoji="✅",
                ),
                parse_mode=HTML,
                reply_markup=MAIN_MENU,
            )
        except Exception as e:
            USERS[uid]["accounts"].pop(name, None)
            await update.effective_message.reply_text(
                f"❌ خطا در بررسی توکن: <code>{esc(str(e)[:100])}</code>",
                parse_mode=HTML,
            )
        return

    # ۲) اسم کلاینت (وقتی منتظر اسم باشیم — هر متنی قبول است)
    if acc and acc.get("awaiting_client_name") and acc.get("domains"):
        acc["awaiting_client_name"] = False
        await make_client(update, context, text)
        return

    # ۳) UUID (فقط وقتی setup کامل شده — ساخت لینک)
    if re.match(r"^[0-9a-fA-F-]{36}$", text) and acc and acc.get("domains"):
        await make_links(update, context, text)
        return

    # ۴) توکن Railway (رشته‌ی ≥۳۰ کاراکتر)
    if len(text) >= 30:
        if user is None:
            USERS[uid] = {"accounts": {}, "active_account": ""}
            user = USERS[uid]
        # اگر اکانتی نیست → اکانت پیش‌فرض؛ وگرنه یک اکانت جدید با اسم خودکار
        if not user.get("accounts"):
            name = "default"
        else:
            n = len(user["accounts"]) + 1
            name = f"account-{n}"
            while name in user["accounts"]:
                n += 1
                name = f"account-{n}"
        user["accounts"][name] = {"token": text}
        await update.effective_message.reply_text(
            "⏳ <b>توکن دریافت شد!</b> در حال بررسی…",
            parse_mode=HTML,
        )
        try:
            wid = get_workspace_id(text)
            if not wid:
                user["accounts"].pop(name, None)
                await update.effective_message.reply_text(
                    "❌ <b>توکن معتبر نیست</b> یا دسترسی ندارد!\n"
                    "توکن جدید از Railway → Settings → Tokens بساز.",
                    parse_mode=HTML,
                )
                return
            user["accounts"][name]["workspace_id"] = wid
            user["active_account"] = name
            await update.effective_message.reply_text(
                card(
                    "توکن تأیید شد",
                    f"✅ توکن معتبر است! (اکانت: <code>{esc(name)}</code> — workspace: <code>{esc(wid)}</code>)\n\n"
                    "حالا دکمه <b>🚀 شروع Setup</b> را بزن یا /setup بفرست.",
                    emoji="✅",
                ),
                parse_mode=HTML,
            )
        except Exception as e:
            user["accounts"].pop(name, None)
            await update.effective_message.reply_text(
                f"❌ خطا در بررسی توکن: <code>{esc(str(e)[:100])}</code>",
                parse_mode=HTML,
            )
        return

    await update.effective_message.reply_text(
        "⚠️ من متوجه نشدم! 🤔\n"
        "لطفاً توکن Railway خودت را بفرست، یا از دکمه‌های منو استفاده کن.",
        parse_mode=HTML,
    )


# ══════════════ مدیریت اکانت‌ها ══════════════
async def acc_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = USERS.get(uid)
    if not user or not user.get("accounts"):
        await update.effective_message.reply_text(
            "👥 هنوز اکانتی ثبت نکردی!\n\n"
            "یا توکن Railway را مستقیم بفرست، یا دکمه <b>➕ افزودن اکانت</b> را بزن.",
            parse_mode=HTML,
        )
        return
    rows = []
    active = user.get("active_account", "")
    for name in user["accounts"]:
        mark = "🟢 (فعال)" if name == active else ""
        rows.append(f"  {'●' if name == active else '○'} <code>{esc(name)}</code> {mark}")
    text = card(
        "اکانت‌های تو",
        f"تعداد: <b>{len(user['accounts'])}</b> — اکانت فعال: <b>{esc(active)}</b>\n\n"
        + "\n".join(rows)
        + "\n\nبرای سوییچ روی اسم اکانت بزن، برای حذف 🗑 را بزن.",
        emoji="👥",
    )
    await update.effective_message.reply_text(text, parse_mode=HTML, reply_markup=accounts_kbd(user))


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مسیریابی دکمه‌های inline."""
    q = update.callback_query
    data = q.data
    uid = update.effective_user.id
    user = USERS.get(uid)
    try:
        # ── چرخش پروکسی ──
        if data.startswith("proxy_"):
            await tcp_callback(update, context, data)
            return
        # ── اکانت‌ها ──
        if data == "acc_add":
            await q.answer()
            if user is None:
                USERS[uid] = {"accounts": {}, "active_account": ""}
                user = USERS[uid]
            user["awaiting_acc_name"] = True
            await q.message.reply_text(
                "✏️ <b>اسم اکانت</b> را بفرست (حداکثر ۱۲ کاراکتر).\n"
                "مثلاً: <code>اصلی</code>، <code>تست</code>، <code>کانفیگ دوم</code>",
                parse_mode=HTML,
            )
            return
        if data == "acc_back":
            await q.answer()
            try:
                await q.message.delete()
            except Exception:
                pass
            return
        if data.startswith("acc_switch:"):
            name = acc_name_from_key(user, uncb(data))
            await q.answer(f"اکانت «{name}» فعال شد ✅")
            if user and name in user.get("accounts", {}):
                user["active_account"] = name
                acc = user["accounts"][name]
                extra = ""
                if acc.get("domains"):
                    extra = f"\n🌐 پنل‌ها: {len(acc['domains'])} دامنه"
                await q.message.reply_text(
                    card(
                        "تغییر اکانت فعال",
                        f"🟢 اکانت <b>{esc(name)}</b> فعال شد." + extra
                        + "\n\nبرای ستاپ جدید دکمه 🚀 را بزن؛ اگر همین اکانت ستاپ شده، از وضعیت ببین.",
                        emoji="👥",
                    ),
                    parse_mode=HTML,
                    reply_markup=accounts_kbd(user),
                )
            return
        if data.startswith("acc_del:"):
            name = acc_name_from_key(user, uncb(data))
            await q.answer()
            await q.message.reply_text(
                f"🗑 مطمئنی اکانت <b>{esc(name)}</b> حذف شود؟\n"
                "(وضعیت ستاپ آن هم پاک می‌شود)",
                parse_mode=HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ بله، حذف کن", callback_data=cb("acc_del_yes", uncb(data)))],
                    [InlineKeyboardButton("❌ نه", callback_data=cb("acc_del_no", uncb(data)))],
                ]),
            )
            return
        if data.startswith("acc_del_yes:"):
            name = acc_name_from_key(user, uncb(data))
            await q.answer("حذف شد 🗑")
            if user and name in user.get("accounts", {}):
                user["accounts"].pop(name, None)
                if user.get("active_account") == name:
                    user["active_account"] = next(iter(user["accounts"]), "")
            await q.message.edit_text(
                card("حذف اکانت", f"🗑 اکانت <b>{esc(name)}</b> حذف شد.", emoji="🗑"),
                parse_mode=HTML,
            )
            if user and user.get("accounts"):
                await q.message.reply_text(
                    "👥 وضعیت اکانت‌ها:",
                    parse_mode=HTML,
                    reply_markup=accounts_kbd(user),
                )
            return
        if data.startswith("acc_del_no:"):
            await q.answer("لغو شد")
            try:
                await q.message.delete()
            except Exception:
                pass
            return

        # ── منو / ستاپ / وضعیت ──
        if data == "cont_setup":
            await q.answer("در حال ادامه… ⏳")
            await continue_setup(update, context)
            return
        if data == "start_setup":
            await q.answer()
            await setup(update, context)
            return
        if data == "menu_status":
            await q.answer()
            await status(update, context)
            return
        if data == "menu_client":
            await q.answer()
            await client_cmd(update, context)
            return
        if data == "menu_help":
            await q.answer()
            await help_cmd(update, context)
            return
        if data == "menu_reset":
            USERS.pop(uid, None)
            await q.answer("ریست شد ✅")
            await q.message.reply_text(
                "🔄 <b>وضعیت ریست شد.</b>\nتوکن جدید بفرست یا دوباره از منو شروع کن.",
                parse_mode=HTML,
            )
            return
        await q.answer()
    except Exception as e:
        logger.exception("خطا در callback")
        try:
            await q.message.reply_text(
                f"❌ خطا: <code>{esc(str(e)[:200])}</code>",
                parse_mode=HTML,
            )
        except Exception:
            pass


# ══════════════ TCP Proxy ══════════════
def tcp_kbd(acc, pick=None):
    """کیبورد منوی TCP Proxy — اگر pick باشد برای یک ریجن خاص."""
    rows = []
    if pick:
        rows.append([
            InlineKeyboardButton("🔀 هوشمند (دامنه تأیید)", callback_data=cb("proxy_smart", pick)),
            InlineKeyboardButton("🎲 رندوم", callback_data=cb("proxy_random", pick)),
        ])
        rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="proxy_back")])
        return InlineKeyboardMarkup(rows)
    rows.append([
        InlineKeyboardButton("🔀 هوشمند — همه", callback_data="proxy_smart_all"),
        InlineKeyboardButton("🎲 رندوم — همه", callback_data="proxy_random_all"),
    ])
    region_row = []
    for name in LABELS:
        if name in acc.get("proxy_map", {}):
            region_row.append(InlineKeyboardButton(f"↻ {name.replace('xui-', '').upper()}", callback_data=cb("proxy_pick", name)))
    if region_row:
        rows.append(region_row)
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="proxy_back")])
    return InlineKeyboardMarkup(rows)


def tcp_body(acc, extra=None):
    pm = acc.get("proxy_map", {})
    lines = []
    for name, label in LABELS.items():
        p = pm.get(name)
        if p:
            lines.append(f"  • {label} → <code>{esc(p['host'])}:{p['port']}</code>")
        else:
            lines.append(f"  • {label} → ❌ ندارد")
    body = "🌐 <b>پروکسی‌های فعلی:</b>\n" + ("\n".join(lines) if lines else "  —")
    if extra:
        body += "\n\n" + extra
    return body


async def tcp_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = USERS.get(uid)
    acc = get_acc(user)
    if not acc or not acc.get("domains") or not acc.get("proxy_map"):
        await update.effective_message.reply_text(
            "⚠️ اول Setup را کامل کن! (باید /setup و /continue اجرا شده باشد)\n"
            "بعد از آن TCP Proxyها اینجا قابل چرخش‌اند.",
            parse_mode=HTML,
        )
        return
    await update.effective_message.reply_text(
        card("چرخش TCP Proxy", tcp_body(acc), emoji="🌐",
             footer="🔀 هوشمند = رسیدن به دامنه‌های تأیید • 🎲 رندوم = دامنه تصادفی وصل‌شونده"),
        parse_mode=HTML,
        reply_markup=tcp_kbd(acc),
    )


async def tcp_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    """مسیریابی دکمه‌های TCP Proxy."""
    q = update.callback_query
    uid = update.effective_user.id
    user = USERS.get(uid)
    acc = get_acc(user)
    if not acc or not acc.get("domains") or not acc.get("proxy_map"):
        await q.answer("اول Setup را کامل کن!", show_alert=True)
        return

    # توقف چرخش در حال اجرا — باید قبل از گارد rotating باشد
    if data == "proxy_cancel":
        if acc.get("rotating"):
            acc["rotate_cancel"] = True
            await q.answer("در حال توقف… 🛑")
        else:
            await q.answer("چرخشی در جریان نیست")
        return

    if acc.get("rotating"):
        await q.answer("یک چرخش در حال انجام است — صبر کن ⏳", show_alert=True)
        return

    if data == "proxy_back":
        await q.answer()
        try:
            await q.message.delete()
        except Exception:
            pass
        return

    if data.startswith("proxy_pick:"):
        name = uncb(data)
        await q.answer()
        label = LABELS.get(name, name)
        await q.message.edit_text(
            card("انتخاب حالت چرخش", f"برای <b>{esc(label)}</b>:\n\n" + tcp_body(acc), emoji="🌐"),
            parse_mode=HTML,
            reply_markup=tcp_kbd(acc, pick=name),
        )
        return

    # اجرای چرخش
    targets = None
    region = None
    if data.startswith("proxy_smart:"):
        region = uncb(data)
        targets = GOOD_DOMAINS
    elif data.startswith("proxy_random:"):
        region = uncb(data)
        targets = ""
    elif data == "proxy_smart_all":
        targets = GOOD_DOMAINS
    elif data == "proxy_random_all":
        targets = ""
    else:
        await q.answer()
        return

    mode = "هوشمند" if targets else "رندوم"
    scope = f" {LABELS.get(region, region)}" if region else " همه ریجن‌ها"
    acc["rotating"] = True
    await q.answer(f"شروع چرخش {mode} — {scope} ⏳")

    msg = await q.message.reply_text(
        card("چرخش TCP Proxy", f"{mode} {scope}\n\n⏳ در حال اجرا… (چند دقیقه)", emoji="🌐"),
        parse_mode=HTML,
    )
    try:
        lines = await run_rotate(update, context, msg, acc, targets, region, mode, scope)
    finally:
        acc["rotating"] = False

    # پردازش نتیجه
    if "CANCELLED" in lines:
        await msg.edit_text(
            card("چرخش متوقف شد", "🛑 توسط کاربر متوقف شد.\n"
                 "هر وقت خواستی دوباره از منوی TCP Proxy تلاش کن.", emoji="🛑"),
            parse_mode=HTML,
        )
        return
    if "TIMEOUT" in lines:
        await msg.edit_text(
            card("سقف زمانی رسید", "⏱ چرخش بیشتر از حد مجاز طول کشید و متوقف شد.\n"
                 "ممکن است Railway کند باشد — بعداً دوباره تلاش کن.", emoji="⏱"),
            parse_mode=HTML,
        )
        return

    new_map = {}
    for line in lines:
        m = re.match(r"PROXY_RESULT:\s*([\w-]+)=([\w.-]+):(\d+)", line)
        if m:
            new_map[m.group(1)] = {"host": m.group(2), "port": int(m.group(3))}

    if new_map:
        acc["proxy_map"].update(new_map)
        _rebuild_servers_json(acc)
        body = tcp_body(acc, extra="✅ پروکسی‌ها چرخیدند!")
        footer = ("لینک‌های قبلی نامعتبر شدند ❗\n"
                  "UUID هر کلاینت را بفرست تا لینک‌های جدید بسازم.")
        await msg.edit_text(card("چرخش کامل شد", body, emoji="🌐", footer=footer), parse_mode=HTML)
    else:
        await msg.edit_text(
            card("چرخش ناموفق", "❌ هیچ پروکسی جدیدی ساخته نشد.\n"
                 "لاگ‌ها را ببین یا دوباره تلاش کن.", emoji="❌"),
            parse_mode=HTML,
        )


def _rebuild_servers_json(acc):
    """بازسازی servers_json از reality_keys + proxy_map جدید."""
    rk = acc.get("reality_keys") or {}
    pm = acc.get("proxy_map") or {}
    if not (rk.get("pub") and rk.get("sid") and pm):
        acc["servers_json"] = ""
        return
    servers = []
    for name, p in pm.items():
        servers.append({
            "name": name.upper(),
            "host": p["host"],
            "port": p["port"],
            "pbk": rk["pub"],
            "sid": rk["sid"],
            "label": LABELS.get(name, name),
        })
    acc["servers_json"] = json.dumps(servers, ensure_ascii=False)


async def run_rotate(update: Update, context: ContextTypes.DEFAULT_TYPE, msg, acc, targets, region, mode, scope):
    """اجرای rotate-proxies.py به صورت async با نمایش زنده.

    - پیام هر ~۴ ثانیه آپدیت می‌شود حتی وقتی اسکریپت خروجی نمی‌دهد
      (حلقه‌های انتظار Railway تا ۲۴۰ ثانیه ساکت‌اند — بدون این، ربات «قفل» به نظر می‌رسد)
    - سقف زمانی کلی (پیش‌فرض ۲۵ دقیقه) — بعدش پروسه kill می‌شود
    - دکمه 🛑 توقف → acc['rotate_cancel']=True → پروسه kill می‌شود
    """
    env = dict(os.environ)
    svc_ids = {k: v for k, v in (acc.get("service_ids") or {}).items()
               if k in (acc.get("proxy_map") or {})}
    if region:
        svc_ids = {region: svc_ids.get(region)} if region in svc_ids else {}
    env.update({
        "RAILWAY_TOKEN": acc["token"],
        "ENV_ID": acc["env_id"],
        "SERVICE_IDS": json.dumps(svc_ids),
        "PORT": "443",
        "MAX_TRIES": os.environ.get("ROTATE_MAX_TRIES", "30"),
        "COOLDOWN": os.environ.get("ROTATE_COOLDOWN", "8"),
    })
    if targets:
        env["TARGET_DOMAINS"] = targets

    script = os.path.join(SCRIPT_DIR, "rotate-proxies.py")
    proc = await asyncio.create_subprocess_exec(
        sys.executable, script,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env,
    )
    acc["rotate_cancel"] = False
    lines = []
    tail = []
    started = time.time()
    deadline = started + float(os.environ.get("ROTATE_TIMEOUT", "1500"))  # ۲۵ دقیقه
    cancel_kbd = InlineKeyboardMarkup([[
        InlineKeyboardButton("🛑 توقف چرخش", callback_data="proxy_cancel"),
    ]])
    last_edit = 0.0
    try:
        while time.time() < deadline:
            try:
                raw = await asyncio.wait_for(proc.stdout.readline(), timeout=4)
            except asyncio.TimeoutError:
                raw = None
            if raw == b"":
                break  # EOF — اسکریپت تمام شد
            if raw:
                line = raw.decode(errors="replace").rstrip()
                if line:
                    lines.append(line)
                    tail.append(line)
                    if len(tail) > 5:
                        tail.pop(0)
            now = time.time()
            if now - last_edit > 4:
                last_edit = now
                body = f"{mode} {scope}\n⏱ {int(now - started)} ثانیه"
                if tail:
                    body += "\n\n" + pre("\n".join(tail))
                try:
                    await msg.edit_text(
                        card("چرخش TCP Proxy", body, emoji="🌐",
                             footer="⏳ در حال اجرا… (🛑 برای توقف)"),
                        parse_mode=HTML,
                        reply_markup=cancel_kbd,
                    )
                except Exception:
                    pass
            if acc.get("rotate_cancel"):
                try:
                    proc.kill()
                except Exception:
                    pass
                try:
                    await proc.wait()
                except Exception:
                    pass
                lines.append("CANCELLED")
                break
        else:
            # سقف زمانی رسید — پروسه را بکش
            try:
                proc.kill()
            except Exception:
                pass
            try:
                await proc.wait()
            except Exception:
                pass
            lines.append("TIMEOUT")
    finally:
        acc["rotate_cancel"] = False
        try:
            if proc.returncode is None:
                proc.kill()
        except Exception:
            pass
    return lines


# ══════════════ Setup ══════════════
async def setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = USERS.get(uid)
    acc = get_acc(user)
    if not acc or "token" not in acc:
        await update.effective_message.reply_text(
            "⚠️ <b>اول توکن Railway را بفرست!</b>\n\n"
            "(<code>Railway → Settings → Tokens → New Token</code> — دسترسی Account)\n"
            "یا از منوی <b>👥 اکانت‌ها</b> اکانت اضافه کن.",
            parse_mode=HTML,
        )
        return

    token = acc["token"]
    msg = await update.effective_message.reply_text(
        card("شروع Setup", f"{bar(0)}\n\n📦 <b>مرحله ۱:</b> ساخت پروژه…", emoji="🚀"),
        parse_mode=HTML,
    )

    try:
        # ۱) پروژه — بازیافت پروژه ناقص قبلی (سقف ۲۵ سرویس/روز اکانت‌های جدید)
        pid = find_or_create_project(token, acc["workspace_id"])
        acc["project_id"] = pid
        env_id = get_env_id(token, pid)
        acc["env_id"] = env_id
        url = get_project_url(token, pid)
        await msg.edit_text(
            card(
                "ساخت پروژه",
                f"✅ پروژه ساخته شد!\n"
                f"🔗 <a href=\"{esc(url)}\">باز کردن داشبورد پروژه</a>\n\n"
                f"{bar(1)}\n\n"
                "📡 <b>مرحله ۲:</b> ساخت ۴ سرویس (بدون ریجن)…\n"
                "⏳ این چند دقیقه طول می‌کشد…",
                emoji="📦",
            ),
            parse_mode=HTML,
        )

        # ۲) ساخت سرویس‌ها
        rc, out, err = run_script("deploy.py", {
            "RAILWAY_TOKEN": token,
            "WORKSPACE_ID": acc["workspace_id"],
            "PROJECT_ID": pid,
            "SKIP_REGION": "1",
        })
        if rc != 0:
            low = ((out or "") + (err or "")).lower()
            if "service creation limit" in low or "25 services per day" in low:
                await msg.edit_text(
                    card(
                        "سقف ساخت سرویس امروز پر شده!",
                        "❌ Railway به اکانت‌های <b>جدید</b> فقط <b>۲۵ ساخت سرویس در روز</b> می‌دهد\n"
                        "و این اکانت امروز به سقف رسیده است.\n\n"
                        "🔧 <b>راه‌حل‌ها:</b>\n"
                        "  • از یک اکانت قدیمی‌تر توکن بده (👥 اکانت‌ها → ➕ افزودن)\n"
                        "  • یا فردا دوباره تلاش کن — شمارنده ریست می‌شود\n"
                        "  • یا از <code>station.railway.com</code> بخواه سقف را بالا ببرند\n\n"
                        "💡 از نسخه جدید، پروژه و سرویس‌های ناقص قبلی <b>بازیافت</b> می‌شوند\n"
                        "و سهمیه روزانه هدر نمی‌رود.",
                        emoji="⛔",
                    ),
                    parse_mode=HTML,
                )
            else:
                await msg.edit_text(
                    card(
                        "خطا در ساخت سرویس‌ها",
                        "❌ خروجی:\n" + pre((out or "")[-800:]) + "\n" + pre((err or "")[-400:]),
                        emoji="❌",
                    ),
                    parse_mode=HTML,
                )
            return

        # استخراج دامنه‌ها — خروجی deploy.py: «✅ دامنه: https://xxx.up.railway.app  (پورت 3000)»
        domains = extract_lines(out, ["دامنه: https://"])
        panel_urls = []
        for d in domains:
            m = re.search(r"https://([^\s\)]+)", d)
            if m:
                panel_urls.append("https://" + m.group(1).rstrip("/") + "/managepanel/")

        await msg.edit_text(
            card(
                "مرحله ۳ — تنظیم ریجن‌ها",
                "✅ سرویس‌ها ساخته شدند!\n\n"
                "📋 <b>دامنه‌های پنل:</b>\n"
                + "\n".join(f"  • <code>{esc(p)}</code>" for p in panel_urls)
                + "\n\n⏭️ حالا ریجن هر سرویس را در داشبورد بگذار:\n"
                "  🇳🇱 <b>xui-nl</b> → هلند (Amsterdam)\n"
                "  🇸🇬 <b>xui-sg</b> → سنگاپور (Singapore)\n"
                "  🇺🇸 <b>xui-us-va</b> → ویرجینیا (Virginia)\n"
                "  🇺🇸 <b>xui-us-ca</b> → کالیفرنیا (San Francisco)\n\n"
                f"🔗 <a href=\"{esc(url)}\">📂 باز کردن پروژه در Railway</a>",
                emoji="⏭️",
                footer="تنظیم کردی؟ دکمه زیر را بزن یا /continue بفرست",
            ),
            parse_mode=HTML,
            reply_markup=CONTINUE_KBD,
        )
        acc["panel_urls"] = panel_urls
    except Exception as e:
        await msg.edit_text(
            f"❌ خطا: <code>{esc(str(e)[:200])}</code>",
            parse_mode=HTML,
        )


async def continue_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = USERS.get(uid)
    acc = get_acc(user)
    if not acc or "project_id" not in acc:
        await update.effective_message.reply_text(
            "⚠️ اول /setup را اجرا کن!",
            parse_mode=HTML,
        )
        return

    token = acc["token"]
    pid = acc["project_id"]
    env_id = acc["env_id"]
    msg = await update.effective_message.reply_text(
        card("ادامه Setup", f"{bar(1)}\n\n🔗 <b>مرحله ۴:</b> اتصال نودها…", emoji="🔄"),
        parse_mode=HTML,
    )

    try:
        # پیدا کردن دامنه‌های پنل‌ها
        d = gql(token, 'query($pid: String!){ project(id: $pid) { services { edges { node { id name } } } } }',
                {"pid": pid})
        services = {e["node"]["name"]: e["node"]["id"] for e in d["data"]["project"]["services"]["edges"]}
        acc["service_ids"] = services

        # دامنه‌ها را از API بگیر — فیلد درست `domains` است (نه `serviceDomains`)
        domains = {}
        for name in ["xui-nl", "xui-sg", "xui-us-va", "xui-us-ca"]:
            sid = services.get(name)
            if not sid:
                continue
            dd = gql(token,
                     'query($pid: String!, $e: String!, $s: String!){ domains(projectId: $pid, environmentId: $e, serviceId: $s) { serviceDomains { domain } customDomains { domain } } }',
                     {"pid": pid, "e": env_id, "s": sid})
            all_doms = ((dd["data"]["domains"].get("serviceDomains") or [])
                        + (dd["data"]["domains"].get("customDomains") or []))
            if all_doms:
                domains[name] = f"https://{all_doms[0]['domain']}"

        if len(domains) < 4:
            await msg.edit_text(
                f"⚠️ فقط {len(domains)} دامنه پیدا شد — صبر کن و دوباره /continue بزن.",
                parse_mode=HTML,
            )
            return

        acc["domains"] = domains
        panels_env = ";".join(f"{k}={v}" for k, v in domains.items())
        service_ids_env = json.dumps(domains and {k: services.get(k) for k in domains})
    except Exception as e:
        await msg.edit_text(
            f"❌ خطا در خواندن دامنه‌ها: <code>{esc(str(e)[:200])}</code>",
            parse_mode=HTML,
        )
        return

    try:
        # ۴) نودها
        await msg.edit_text(
            card("مرحله ۴", f"{bar(2)}\n\n🔗 اتصال نودها به پنل مرکزی…", emoji="🔗"),
            parse_mode=HTML,
        )
        rc, out, err = run_script("xui-node-connector.py", {
            "PANELS": panels_env,
            "MAIN_PANEL": "xui-nl",
            "REMOTE_NODES": "xui-sg,xui-us-va,xui-us-ca",
            "XUI_USERNAME": os.environ.get("XUI_USERNAME", "admin"),
            "XUI_PASSWORD": os.environ.get("XUI_PASSWORD", "admin"),
        })
        nodes_ok = "نود" in out and "اضافه شد" in out
        await msg.edit_text(
            card(
                "مرحله ۵",
                ("✅ نودها وصل شدند!" if nodes_ok else "⚠️ نودها با خطا مواجه شدند (ادامه می‌دهم):\n" + pre((out or "")[-300:]))
                + f"\n\n{bar(3)}\n\n📡 ساخت اینباند VLESS + Reality (کلید مشترک)…",
                emoji="🛡️",
            ),
            parse_mode=HTML,
        )

        # ۵) اینباند
        rc, out, err = run_script("xui-reality-inbound.py", {
            "PANELS": panels_env,
            "MAIN_PANEL": "xui-nl",
            "XUI_USERNAME": os.environ.get("XUI_USERNAME", "admin"),
            "XUI_PASSWORD": os.environ.get("XUI_PASSWORD", "admin"),
        })
        inbound_ok = "ساخته شد" in out
        # کلیدهای Reality را از خروجی بگیر («🔑 PublicKey: ...» و «🏷 ShortId: ...»)
        reality_keys = {}
        for line in (out or "").splitlines():
            if "PublicKey:" in line:
                reality_keys["pub"] = line.split("PublicKey:")[-1].strip()
            elif "ShortId:" in line:
                reality_keys["sid"] = line.split("ShortId:")[-1].strip()
        acc["reality_keys"] = reality_keys
        await msg.edit_text(
            card(
                "مرحله ۶",
                ("✅ اینباند ساخته شد!" if inbound_ok else "⚠️ اینباند با خطا مواجه شد:\n" + pre((out or "")[-300:]))
                + f"\n\n{bar(4)}\n\n🌐 TCP Proxy + روتیت + Host ها (چند دقیقه)…",
                emoji="🌐",
            ),
            parse_mode=HTML,
        )

        # ۶) TCP proxy
        rc, out, err = run_script("xui-tcp-proxy-setup.py", {
            "RAILWAY_TOKEN": token,
            "ENV_ID": env_id,
            "PROJECT_ID": pid,
            "MAIN_PANEL": "xui-nl",
            "REMOTE_NODES": "xui-sg,xui-us-va,xui-us-ca",
            "TARGET_PORT": "443",
            "PANELS": json.dumps(domains),
            "SERVICE_IDS": service_ids_env,
            "XUI_USERNAME": os.environ.get("XUI_USERNAME", "admin"),
            "XUI_PASSWORD": os.environ.get("XUI_PASSWORD", "admin"),
        })
        # دامنه‌ها و پورت‌های TCP proxy را از خروجی بگیر:
        #   «[xui-nl] ساخت TCP proxy ...» و «✅ domain.proxy.rlwy.net:port → app:443»
        proxy_map = {}
        current = None
        for line in (out or "").splitlines():
            m = re.match(r"\[([^\]]+)\]\s+ساخت TCP proxy", line)
            if m:
                current = m.group(1)
                continue
            m2 = re.search(r"✅\s+([\w.-]+\.proxy\.rlwy\.net):(\d+)\s+→", line)
            if m2 and current:
                proxy_map[current] = {"host": m2.group(1), "port": int(m2.group(2))}
        acc["proxy_map"] = proxy_map

        # ساخت SERVERS_JSON برای لینک‌ساز — داینامیک از ستاپ واقعی
        _rebuild_servers_json(acc)

        await msg.edit_text(
            card(
                "TCP Proxy",
                "✅ TCP Proxy ساخته شد!\n" + (pre((out or "")[-500:]) if out else ""),
                emoji="🌐",
            ),
            parse_mode=HTML,
        )

        # ۷) لینک‌ها — ارسال پنل اصلی + راهنمای ساخت کلاینت
        main_panel = domains.get("xui-nl", "")
        xui_user = os.environ.get("XUI_USERNAME", "admin")
        xui_pass = os.environ.get("XUI_PASSWORD", "admin")
        await msg.edit_text(
            card(
                "Setup کامل شد!",
                f"🎉 <b>همه‌چیز آماده است!</b>\n\n"
                f"🔗 <b>پنل اصلی:</b> <code>{esc(main_panel)}/managepanel/</code>\n"
                f"👤 یوزرنیم: <code>{esc(xui_user)}</code>  |  🔑 پسورد: <code>{esc(xui_pass)}</code>\n\n"
                f"{bar(TOTAL_STEPS)}\n\n"
                "👤 برای ساخت کلاینت و گرفتن <b>لینک ساب</b>:\n"
                "   دکمه <b>«👤 ساخت کلاینت»</b> را بزن یا <code>/client اسم</code> بفرست\n"
                "   (مثلاً <code>/client ali</code> — هر اسمی قبول است)\n\n"
                "🌐 برای چرخش TCP Proxy از منوی <b>«🌐 TCP Proxy»</b> استفاده کن.",
                emoji="🎉",
            ),
            parse_mode=HTML,
            reply_markup=CLIENT_KBD,
        )
        acc["domains"] = domains
    except Exception as e:
        await msg.edit_text(
            f"❌ خطا: <code>{esc(str(e)[:200])}</code>",
            parse_mode=HTML,
        )


async def links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    acc = get_acc(USERS.get(uid))
    if not acc or "domains" not in acc:
        await update.effective_message.reply_text(
            "⚠️ اول /setup و /continue را اجرا کن!",
            parse_mode=HTML,
        )
        return
    await update.effective_message.reply_text(
        card(
            "گرفتن لینک‌ها",
            "۱. برو به پنل اصلی (<code>xui-nl</code>) → اینباند → کلاینت\n"
            "۲. UUID کلاینت را کپی کن\n"
            "۳. اینجا بفرست تا ۴ لینک درست (با TCP proxy) بسازم.",
            emoji="🔗",
        ),
        parse_mode=HTML,
    )


async def make_links(update: Update, context: ContextTypes.DEFAULT_TYPE, uuid_val: str):
    """ساخت لینک‌های VLESS با داده‌های واقعی ستاپ (TCP proxy + کلیدهای Reality)."""
    uid = update.effective_user.id
    acc = get_acc(USERS.get(uid))
    if not acc or "domains" not in acc:
        await update.effective_message.reply_text(
            "⚠️ اول /setup را اجرا کن!",
            parse_mode=HTML,
        )
        return

    env_extra = {"XUI_UUID": uuid_val}
    if acc.get("servers_json"):
        env_extra["SERVERS_JSON"] = acc["servers_json"]

    rc, out, err = run_script("xui-link-maker.py", env_extra)
    if rc == 0 and "vless://" in out:
        await update.effective_message.reply_text(
            card("لینک‌های VLESS", "🔗 لینک‌ها (۴ سرور):\n" + pre(out), emoji="🔗"),
            parse_mode=HTML,
        )
    else:
        await update.effective_message.reply_text(
            card(
                "خطا در ساخت لینک",
                "❌ UUID را بررسی کن.\n" + pre((err or out or "")[-300:]),
                emoji="❌",
            ),
            parse_mode=HTML,
        )


async def client_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ساخت کلاینت با اسم دلخواه کاربر — /client <اسم> یا دکمه منو."""
    uid = update.effective_user.id
    user = USERS.get(uid)
    acc = get_acc(user)
    if not acc or "domains" not in acc:
        await update.effective_message.reply_text(
            "⚠️ اول /setup و /continue را اجرا کن!",
            parse_mode=HTML,
        )
        return
    name = " ".join(context.args or []).strip()
    if name:
        await make_client(update, context, name)
    else:
        acc["awaiting_client_name"] = True
        await update.effective_message.reply_text(
            "👤 اسم کلاینت را بفرست — هر اسمی می‌تونه باشه (بدون محدودیت).",
            parse_mode=HTML,
        )


async def make_client(update: Update, context: ContextTypes.DEFAULT_TYPE, name: str):
    """ساخت کلاینت در پنل اصلی و ارسال لینک ساب (فرمت https بدون پورت)."""
    uid = update.effective_user.id
    user = USERS.get(uid)
    acc = get_acc(user)
    if not acc or "domains" not in acc:
        await update.effective_message.reply_text(
            "⚠️ اول /setup و /continue را اجرا کن!",
            parse_mode=HTML,
        )
        return
    name = name.strip()
    if not name:
        await update.effective_message.reply_text(
            "⚠️ اسم کلاینت خالیه — دوباره بفرست.",
            parse_mode=HTML,
        )
        return

    await update.effective_message.reply_text(
        f"👤 در حال ساخت کلاینت «{esc(name)}» روی پنل اصلی…",
        parse_mode=HTML,
    )
    panels_env = ";".join(f"{k}={v}" for k, v in acc["domains"].items())
    rc, out, err = run_script("xui-client-create.py", {
        "PANELS": panels_env,
        "MAIN_PANEL": "xui-nl",
        "CLIENT_NAME": name,
        "XUI_USERNAME": os.environ.get("XUI_USERNAME", "admin"),
        "XUI_PASSWORD": os.environ.get("XUI_PASSWORD", "admin"),
    })
    sub_https = ""
    uuid_val = ""
    for line in (out or "").splitlines():
        if line.startswith("SUB_LINK_HTTPS="):
            sub_https = line.split("=", 1)[1]
        elif line.startswith("UUID="):
            uuid_val = line.split("=", 1)[1]

    if rc == 0 and sub_https:
        await update.effective_message.reply_text(
            card(
                "کلاینت ساخته شد!",
                f"✅ کلاینت «{esc(name)}» ساخته شد!\n\n"
                f"🔗 <b>لینک ساب:</b>\n<code>{esc(sub_https)}</code>\n\n"
                + (f"🆔 UUID: <code>{esc(uuid_val)}</code>\n" if uuid_val else "")
                + "این لینک توی v2rayNG / Hiddify / v2box / Streisand جواب می‌ده.",
                emoji="✅",
            ),
            parse_mode=HTML,
        )
    elif rc == 0 and uuid_val:
        await update.effective_message.reply_text(
            card(
                "کلاینت ساخته شد (بدون ساب)",
                f"⚠️ کلاینت «{esc(name)}» ساخته شد ولی لینک ساب برنگشت.\n"
                f"🆔 UUID: <code>{esc(uuid_val)}</code>",
                emoji="⚠️",
            ),
            parse_mode=HTML,
        )
    else:
        await update.effective_message.reply_text(
            card(
                "خطا در ساخت کلاینت",
                "❌ " + pre((err or out or "")[-300:]),
                emoji="❌",
            ),
            parse_mode=HTML,
        )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = USERS.get(uid, {})
    acc = get_acc(user)
    rows = []
    n_acc = len(user.get("accounts", {}))
    active = user.get("active_account", "")
    rows.append(f"👥 <b>اکانت‌ها:</b> {n_acc} — فعال: <code>{esc(active)}</code>" if active else "👥 <b>اکانت‌ها:</b> هیچ")
    if acc:
        if "token" in acc:
            rows.append("✅ <b>توکن:</b> ثبت شده")
        if "project_id" in acc:
            rows.append(f"📦 <b>پروژه:</b> <code>{esc(acc['project_id'][:8])}…</code>")
            rows.append(f"🔗 <a href=\"{esc(get_project_url(acc['token'], acc['project_id']))}\">داشبورد پروژه</a>")
        if "domains" in acc:
            rows.append(f"🌐 <b>پنل‌ها:</b> {len(acc['domains'])} دامنه")
        if acc.get("proxy_map"):
            rows.append(f"🌐 <b>TCP Proxy:</b> {len(acc['proxy_map'])} سرور")
    if len(rows) <= 1:
        rows.append("⚠️ هنوز چیزی شروع نشده — توکن Railway بفرست!")
    await update.effective_message.reply_text(
        card("وضعیت Setup", "\n".join(rows), emoji="📋"),
        parse_mode=HTML,
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    USERS.pop(uid, None)
    await update.effective_message.reply_text(
        "❌ لغو شد.\nبرای شروع دوباره توکن Railway بفرست.",
        parse_mode=HTML,
    )


def main():
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN تنظیم نشده!")
        sys.exit(1)

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("setup", setup))
    app.add_handler(CommandHandler("continue", continue_setup))
    app.add_handler(CommandHandler("links", links))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CommandHandler("client", client_cmd))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("🤖 ربات شروع شد — polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
