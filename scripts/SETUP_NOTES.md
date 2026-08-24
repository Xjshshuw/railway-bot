# 🗒 نکات راه‌اندازی 3x-ui Multi-Region (یادداشت‌های مهم)

> این فایل خلاصه‌ی کامل تجربه‌های واقعی است — هر بار که می‌خواهی این سیستم را از نو
> بسازی یا نگهداری کنی، این نکات را بخوان. همه‌ی این‌ها از خطاهای واقعی به دست آمده‌اند!

---

## ۰) راه‌اندازی یک‌کلیک (مهم!)

همه‌چیز با یک دستور اجرا می‌شود:

```bash
export RAILWAY_TOKEN="توکن_اکانت"
export WORKSPACE_ID="..."
export PROJECT_ID="..."
export ENV_ID="..."
export PANELS='{"xui-nl": "https://...", "xui-sg": "https://...", "xui-us-va": "https://...", "xui-us-ca": "https://..."}'
export SERVICE_IDS='{"xui-nl": "svc-id-1", "xui-sg": "svc-id-2", "xui-us-va": "svc-id-3", "xui-us-ca": "svc-id-4"}'
bash run_all.sh
```

`run_all.sh` این ۴ مرحله را پشت سر هم اجرا می‌کند:

| مرحله | اسکریپت | کار |
|---|---|---|
| 1 | `deploy.py` | ساخت سرویس‌ها (ریجن + دامنه 3000 + ولوم) |
| 2 | `xui-node-connector.py` | لاگین + API Token + اتصال نودها به پنل مرکزی |
| 3 | `xui-reality-inbound.py` | ساخت اینباند VLESS+Reality روی همه پنل‌ها |
| 4 | `xui-tcp-proxy-setup.py` | TCP proxy + روتیت به دامنه خوب + Host ها |

> متغیرهای پیش‌فرض: `XUI_USERNAME=admin`، `XUI_PASSWORD=admin`، `MAIN_PANEL=xui-nl`

---

## ۱) دیپلوی اولیه (ساده)

```bash
# فقط Deploy from GitHub — بدون هیچ متغیری
# ریپو: Djsjsnsjcjx/railway-3xui-service
```

- Railway فقط `Dockerfile` را build می‌کند → 3x-ui روی پورت 2053 + nginx روی پورت **3000**
- دامنه‌ی عمومی باید `targetPort=3000` باشد (همان پورت nginx)

---

## ۲) ساخت سرویس‌ها از طریق API (deploy.py)

```bash
export RAILWAY_TOKEN="توکن_اکانت"
export WORKSPACE_ID="..."
export PROJECT_ID="..."
python3 deploy.py
```

### ⚠️ اشتباهاتی که نباید تکرار کنی:

| باگ | علت | فیکس |
|---|---|---|
| `python3: command not found` | alpine پایتون ندارد | `python3` به Dockerfile اضافه شد |
| `Problem processing request` | `variables` باید **JSON object** باشد نه لیست | `{"KEY": "value"}` |
| `HTTP 400` در set_region | mutation با `{ id }` انتخاب فیلد — ولی Boolean برمی‌گرداند | بدون انتخاب فیلد |
| ریجن ست نمی‌شود | فیلد `region` در ServiceInstanceUpdate کار نمی‌کند | از `multiRegionConfig: {"ams": {"numReplicas": 1}}` استفاده کن |
| `Free plan resource provision limit exceeded` | پلن HOBBY سقف دارد | ارتقا پلن یا حذف سرویس اضافی |

### ریجن‌های معتبر Railway:
```
ams = هلند (Amsterdam)       sin = سنگاپور (Singapore)
iad = آمریکا شرق (Virginia)   sfo = آمریکا غرب (San Francisco)
pdx = پورتلند (در داشبورد نیست!)
```

---

## ۳) bootstrap خودکار (اختیاری)

- اگر `BOOTSTRAP=1` روی سرویس اول ست شود، خودش ۴ سرویس می‌سازد
- سرویس‌های جدید با `BOOTSTRAP=0` ساخته می‌شوند (جلوگیری از حلقه‌ی بی‌نهایت)
- `bootstrap.py` از داخل کانتینر با توکن Railway کار می‌کند — **امنیت کمتر** (توکن روی Railway می‌ماند)
- برای امنیت بیشتر: bootstrap را خاموش کن و از بیرون با `deploy.py` کار کن

---

## ۳.۵) اینباند استاندارد (مشخصات ثابت — مهم!)

هر پنل 3x-ui باید اینباند با این مشخصات ثابت داشته باشد (اسکریپت `xui-reality-inbound.py`):

```
پورت:       443
پروتکل:     vless
شبکه:       tcp (raw)
امنیت:      reality
Target:     is1-ssl.mzstatic.com:443
serverNames: is1..is5.ssl.mzstatic.com
فینگرپرینت: ios
بقیه:       پیش‌فرض خود پنل (دست نمی‌خورد!)
```

### 🔗 ساخت لینک اتصال — مهم‌ترین نکته!

**لینکی که خود پنل 3x-ui می‌سازد (QR/کپی) کار نمی‌کند!** چرا:
1. دامنه‌های `.up.railway.app` (حتی با targetPort=443) **TLS خود Railway را تحمیل می‌کنند** — گواهی `*.up.railway.app` نه `is1-ssl.mzstatic.com` → کلاینت Reality خطای x509 می‌گیرد
2. پورت اینباند (443) با پورت TCP proxy فرق دارد

**راه درست:** از اسکریپت `xui-link-maker.py` استفاده کن:

```bash
python3 xui-link-maker.py <UUID_کلاینت>
```

لینک‌های درست را با TCP proxy می‌سازد (آدرس + پورت درست + pbk/sid از هر سرور).

> نکته: `shareAddr` روی اینباند را می‌توان به دامنه TCP proxy ست کرد (بدون پورت) ولی باز هم پورت لینک اشتباه می‌شود — همیشه از لینک‌ساز استفاده کن.

### ⚠️ اشتباهات رایج:
- **اینباند تکراری 443 نساز!** در xray فقط یکی می‌تواند روی 443 گوش بدهد — بقیه تداخل می‌کنند و همه قطع می‌شوند. اسکریپت جدید خودش چک می‌کند و رد می‌شود.
- فینگرپرینت سرور باید با `fp` لینک کلاینت هماهنگ باشد (ios/ios یا chrome/chrome) — اگر تغییرش دادی، لینک‌ها را هم آپدیت کن.
- اگر اینباندها از پنل اصلی به پنل‌های ریموت کپی می‌شوند (کلید یکسان)، shortIds چندگانه دارند — همه را در لینک امتحان کن.

### 🌐 Host ها — مهم‌ترین باگ ساب!

**هر Host باید به اینباند خودش وصل شود!** اگر همه Host ها به اینباند اول (مثلاً NL) وصل شوند، ساب برای هر نود یک لینک NL می‌دهد + لینک‌های اینباندهای دیگر = لینک‌های تکراری/اشتباه.

**مثال درست:**
```
tcp-xui-nl    → inboundId=1 (اینباند NL محلی — بدون nodeId)
tcp-xui-sg    → inboundId=4 (اینباند SG — nodeId=1)
tcp-xui-us-va → inboundId=2 (اینباند US-VA — nodeId=2)
tcp-xui-us-ca → inboundId=3 (اینباند US-CA — nodeId=3)
```

**چطور اینباند هر سرویس را پیدا کنیم (روی پنل اصلی):**
- اینباند خود پنل اصلی → `nodeId=None`
- اینباند هر نود → `nodeId=1..N` (به ترتیب نودهای ریموت)

> اسکریپت `xui-tcp-proxy-setup.py` الان این کار را خودکار انجام می‌دهد (نگاشت nodeId → نام سرویس).

## ۴) اتصال نودها (xui-node-connector.py)

```bash
export PANELS="xui-nl=https://...;xui-sg=https://...;xui-us-va=https://...;xui-us-ca=https://..."
export MAIN_PANEL="xui-nl"
export REMOTE_NODES="xui-sg,xui-us-va,xui-us-ca"
export XUI_USERNAME="admin"
export XUI_PASSWORD="admin"
python3 xui-node-connector.py
```

### 🔑 نکات حیاتی API داخلی 3x-ui (v3.6):

1. **مسیر درست همه API ها:** باید با پیشوند `/managepanel/panel/api/...` صدا زده شوند
   - ✅ `/managepanel/panel/api/nodes/list`
   - ❌ `/panel/api/nodes/list` → **502** (nginx به پورت اشتباه می‌فرستد!)

2. **جریان لاگین (CSRF) — حیاتی:**
   ```
   GET  /managepanel/            → کوکی 3x-ui
   GET  /managepanel/csrf-token  → توکن CSRF (فیلد obj)
   POST /managepanel/login       → {username, password} + هدر X-CSRF-Token
   ```
   ⚠️ **بعد از لاگین، دوباره CSRF mint کن!** توکن قبلی با سشن جدید نامعتبر است.
   ⚠️ **کوکی سشن بعد از لاگین عوض می‌شود!** باید `Set-Cookie` پاسخ login را بگیری، نه کوکی اولیه — وگرنه API ها 404 می‌دهند.

3. **همه POST ها به هدر `X-CSRF-Token` نیاز دارند** — بدون آن → 403

4. **Login Limiter:** بعد از ۵ بار تلاش ناموفق، IP برای **۱۵ دقیقه** بن می‌شود
   - برای تست‌های مکرر، بین تلاش‌ها صبر کن یا از IP دیگر استفاده کن

5. **ساخت API Token:** مقدار توکن فقط در پاسخ `create` برمی‌گردد — اگر گمش کردی، باید حذف و دوباره بسازی:
   ```
   POST /panel/api/setting/apiTokens/create   → {"obj": {"token": "..."}}
   POST /panel/api/setting/apiTokens/delete/{id}
   ```

6. **پورت نود باید 443 باشد** نه 3000! (دامنه‌ی عمومی Railway از بیرون روی HTTPS/443 است)
   - `port: 3000` → timeout در `nodes/add`
   - `port: 443` → ✅

7. **ساختار add نود:**
   ```json
   {
     "name": "xui-sg",
     "scheme": "https",
     "address": "xui-sg-production-xxx.up.railway.app",
     "port": 443,
     "basePath": "/managepanel/",
     "apiToken": "توکن_پنل_مقصد",
     "enable": true
   }
   ```

8. **⚠️ اینباند تکراری نساز! (باگ مهم)**
   - فقط **یک** اینباند می‌تواند روی پورت 443 گوش دهد — بقیه fail می‌شوند و xray خراب می‌شود
   - اجرای مکرر اسکریپت بدون چک، اینباندهای تکراری می‌سازد → همه‌چیز قطع می‌شود
   - `xui-reality-inbound.py` حالا idempotent است (چک می‌کند اینباند 443 از قبل هست یا نه)
   - اگر اینباندهای تکراری ساختی: همه به جز اولی را حذف کن (`/panel/api/inbounds/del/{id}`)

9. **⚠️ اینباندهای نودهای ریموت ممکن است "گم" شوند**
   - بعد از ریاستارت xray، اینباندهای پنل‌های ریموت ممکن است حذف شوند
   - تست سریع: `curl` مستقیم به پنل ریموت → اگر `Connection reset by peer` گرفتی یعنی اینباند نیست
   - فیکس: اینباند را دوباره روی پنل ریموت بساز (`xui_fix_remote_inbounds.py` یا اجرای دوباره‌ی xui-reality-inbound)

10. **ریجن‌ها (مهم):**
    - فیلد `region` در `serviceInstance` ممکن است `null` برگردد ولی ریجن واقعاً ست شده باشد
    - راه درست ست ریجن: `serviceInstanceUpdate` با `region: "ams|sin|iad|sfo"`
    - ⚠️ گاهی بعد از ست ریجن باید سرویس را redeploy کنی تا اعمال شود
    - ریجن‌های معتبر: `ams` (هلند), `sin` (سنگاپور), `iad` (ویرجینیا), `sfo` (کالیفرنیا), `pdx` (پورتلند)

---

## ۵) endpoint های مفید 3x-ui

| مسیر | کار |
|---|---|
| `/managepanel/panel/api/nodes/list` | لیست نودها |
| `/managepanel/panel/api/nodes/add` | افزودن نود |
| `/managepanel/panel/api/nodes/test` | تست اتصال نود |
| `/managepanel/panel/api/inbound/list` | لیست اینباندها |
| `/managepanel/panel/api/setting/apiTokens` | لیست API Token ها |
| `/managepanel/panel/api/server/status` | وضعیت سرور |
| `/managepanel/csrf-token` | توکن CSRF |

---

## ۶) نکات Railway

- **پلن HOBBY (رایگان):** سقف منابع دارد — برای پروژه‌های بزرگ ارتقا بده
- **دو اکانت:**
  - `amirxha2` (اکانت اول) — پروژه‌های worthy-charisma، cycle-test-1
  - `amdux2u` (اکانت دوم) — پروژه‌های 3xui، disciplined-tenderness
- **دامنه‌ها:** هر سرویس دامنه‌ی مستقل `.up.railway.app` می‌گیرد
- **ولوم:** همیشه به مسیر `/etc/x-ui` وصل کن تا تنظیمات پنل ماندگار بماند

---

## ۷) فایل‌های ریپو

| فایل | کار |
|---|---|
| `Dockerfile` | alpine 3.20 + 3x-ui v3.6.0 + nginx + python3 |
| `start.sh` | راه‌اندازی + bootstrap (اختیاری) |
| `bootstrap.py` | خود-راه‌انداز داخل کانتینر (BOOTSTRAP=1) |
| `deploy.py` | ساخت سرویس‌ها از بیرون با API (پیشنهادی) |
| `xui-node-connector.py` | اتصال نودهای چند-ریجن به پنل مرکزی |
| `nginx.conf.template` | ریورس پروکسی (پنل 2053 + ساب 2096 + اینباند 8080) |

---

*ساخته‌شده توسط Hermes — آگوست ۲۰۲۶*
