# 🤖 Railway 3x-ui Bot

ربات تلگرامی که **کل فرایند راه‌اندازی 3x-ui چند-ریجن روی Railway** را خودکار انجام می‌دهد.

## ✨ امکانات

| مرحله | کار |
|---|---|
| ۱ | دریافت توکن Railway از کاربر |
| ۲ | ساخت پروژه + ۴ سرویس (xui-nl/sg/us-va/us-ca) با دامنه + ولوم |
| ۳ | راهنمای تنظیم ریجن (کاربر در داشبورد تنظیم می‌کند) |
| ۴ | اتصال نودها به پنل مرکزی |
| ۵ | ساخت اینباند VLESS+Reality (کلید مشترک — ۴ در، ۱ قفل) |
| ۶ | TCP proxy + روتیت به دامنه خوب + Host ها |
| ۷ | تحویل لینک‌های اتصال با UUID کاربر |

## 🚀 اجرا روی Railway

1. **ساخت ربات تلگرام:**
   - با [@BotFather](https://t.me/BotFather) یک ربات بساز
   - توکن ربات را کپی کن (مثل `123456:ABC-DEF...`)

2. **دیپلوی روی Railway:**
   - `New Project → Deploy from GitHub repo`
   - ریپو: `Kolkolz/railway-bot`
   - متغیر محیطی:
     ```
     BOT_TOKEN=توکن_ربات_تلگرام
     ```

3. **استفاده:**
   - ربات را `/start` کن
   - توکن Railway خودت را بفرست (Railway → Settings → Tokens)
   - `🚀 شروع Setup` را بزن
   - بعد از ساخت سرویس‌ها، ریجن‌ها را در داشبورد تنظیم کن
   - `/continue` بزن تا بقیه کارها انجام شود

## 🛠 متغیرهای محیطی

| متغیر | پیش‌فرض | توضیح |
|---|---|---|
| `BOT_TOKEN` | — | توکن ربات تلگرام (الزامی) |
| `XUI_USERNAME` | `admin` | یوزرنیم پنل 3x-ui |
| `XUI_PASSWORD` | `admin` | پسورد پنل 3x-ui |
| `REPO` | `Djsjsnsjcjx/railway-3xui-service` | ریپوی سرویس‌ها |

## 📁 ساختار

```
railway-bot/
├── bot.py              # ربات تلگرام (منطق اصلی)
├── Dockerfile          # اجرا روی Railway
├── requirements.txt    # python-telegram-bot, cryptography
├── README.md
└── scripts/            # اسکریپت‌های راه‌انداز (از 3xui-multi-region)
    ├── deploy.py               # ساخت سرویس‌ها
    ├── xui-node-connector.py   # اتصال نودها
    ├── xui-reality-inbound.py  # اینباند استاندارد
    ├── xui-tcp-proxy-setup.py  # TCP proxy + Host ها
    └── xui-link-maker.py       # لینک‌ساز
```

## ⚠️ نکات

- وضعیت کاربران در حافظه نگه داشته می‌شود — بعد از ری‌استارت ربات باید دوباره توکن بدهی
- ریجن‌ها توسط کاربر تنظیم می‌شوند (طبق خواسته) — ربات سرویس‌ها را بدون ریجن می‌سازد
- TCP proxy ها به دامنه‌های لیست خوب (monorail, nozomi, ...) روتیت می‌شوند
