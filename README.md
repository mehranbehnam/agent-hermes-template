# Agent Hermes — الگوی ساخت

ایجنت هوش مصنوعی چندکاربره روی تلگرام. روی موتور **[hermes-agent](https://github.com/NousResearch/hermes-agent)** (Nous Research) ساخته شده و این مخزن **فقط بخش‌های خودمان** را دارد: پنل ادمین، ابزارهای کاربر، جداسازی کامل کاربران، تبلیغات، بایگانی اسناد و دسترسی به گوشی.

> هیچ رمز، توکن، اطلاعات کاربر یا مشتری در این مخزن نیست. شناسه‌ها، آی‌پی‌ها و دامنه‌ها نمونه‌اند (`100000001`، `203.0.113.x`، `example.com`) و باید با مقدارهای خودت عوض شوند.

## چه چیزهایی دارد

| پوشه | کار |
|---|---|
| `plugins/admin-panel/` | پنل ادمین داخل تلگرام: کاربران، اشتراک معمولی/پرمیوم، لینک تست ۲۴ ساعته با سهمیه‌ی توکن، دفتر حساب مشتری، بایگانی، گراف‌ها، و نگهبان‌های امنیتی (جلوگیری از دسترسی یک کاربر به داده‌ی دیگری) |
| `plugins/group-self-filter/` | جلوگیری از جواب دادن ربات به پیام‌های خودش در گروه‌ها |
| `shared-tools/admin/` | مدیریت کاربران (`users_admin.py`)، جداسازی هر کاربر در کانتینر Docker خودش (`sandbox_profile.py`)، عیب‌یابی |
| `shared-tools/userbot/` | اتصال امن حساب تلگرام خود کاربر (Telethon)، خواندن چت‌ها، جستجوی تلگرام، مرتب‌سازی پوشه/بایگانی |
| `shared-tools/docs/` | پردازش و بایگانی اسناد روی Google Drive، داشبورد دایره‌ای، دسترسی به حافظه‌ی گوشی (Termux) |
| `ads/scripts/` | تبلیغات زمان‌بندی‌شده، آمار کانال، گزارش فروش |
| `sandbox/Dockerfile` | ایمیج کانتینر کاربران |
| `profile-template/` | الگوی پروفایل کاربر تازه (SOUL، اسکیل‌ها، نمونه‌ی config) |
| `deploy/` | نمونه‌ی cron و تنظیم systemd |
| `locales/` | ترجمه‌ی فارسی پیام‌های سیستم |

## پیش‌نیازها

- سرور لینوکس (Ubuntu 24.04) با دسترسی root، حداقل ۴ گیگ رم
- Docker
- یک ربات تلگرام (از @BotFather) و `api_id`/`api_hash` از my.telegram.org برای اتصال حساب‌ها
- کلید OpenRouter (برای مدل‌ها؛ مدل‌های رایگان هم کار می‌کنند)
- اختیاری: `rclone` با یک Google Drive برای بایگانی

## راه‌اندازی قدم‌به‌قدم

**۱. نصب موتور hermes-agent** — طبق راهنمای رسمی خودش. بعد از نصب پوشه‌ی `~/.hermes` ساخته می‌شود.

**۲. کپی این مخزن روی سرور:**
```bash
git clone https://github.com/<you>/agent-hermes-template.git
cd agent-hermes-template
cp -r plugins/* ~/.hermes/plugins/
mkdir -p ~/.hermes/shared-tools ~/.hermes/ads
cp -r shared-tools/* ~/.hermes/shared-tools/
cp -r ads/scripts ~/.hermes/ads/
mkdir -p ~/.hermes/locales && cp locales/fa-overlay.en.yaml ~/.hermes/locales/en.yaml
```

**۳. تنظیم رمزها:**
```bash
cp .env.example ~/.hermes/.env
nano ~/.hermes/.env          # توکن ربات، کلید OpenRouter و شناسه‌ی خودت را بنویس
chmod 600 ~/.hermes/.env
```
در کد، شناسه‌ی مالک به‌صورت `100000001` نوشته شده؛ همه را با شناسه‌ی عددی تلگرام خودت عوض کن:
```bash
grep -rl 100000001 ~/.hermes/plugins ~/.hermes/shared-tools ~/.hermes/ads | xargs sed -i 's/100000001/<YOUR_ID>/g'
```
آی‌پی‌ها (`203.0.113.x`)، دامنه‌ها (`example.com`) و اسم کانال/گروه‌های نمونه (`your_channel` و…) را هم با مال خودت عوض کن.

**۴. ساخت ایمیج کانتینر کاربران:**
```bash
docker build -t hermes-user-sandbox:1 sandbox/
```

**۵. پروفایل الگو:**
```bash
mkdir -p ~/.hermes/profiles/usertemplate
cp profile-template/SOUL.md ~/.hermes/profiles/usertemplate/
cp profile-template/config.example.yaml ~/.hermes/profiles/usertemplate/config.yaml
cp -r profile-template/skills ~/.hermes/profiles/usertemplate/
```
هر کاربر تازه با `users_admin.py create <name>` از همین الگو ساخته و خودکار در کانتینر جدا قفل می‌شود.

**۶. اجرای سرویس:**
```bash
mkdir -p ~/.config/systemd/user/hermes-gateway.service.d
cp deploy/systemd/*.conf ~/.config/systemd/user/hermes-gateway.service.d/
systemctl --user daemon-reload && systemctl --user restart hermes-gateway
systemctl --user is-active hermes-gateway
```

**۷. کارهای زمان‌بندی‌شده (اختیاری):** فایل‌های `deploy/cron/` را بخوان، مسیرها و اسم‌ها را درست کن و فقط آن‌هایی را که لازم داری در `/etc/cron.d/` بگذار.

**۸. اولین ورود:** به ربات پیام بده؛ از پنل ادمین («📥 درخواست‌ها») خودت را تأیید کن. دکمه‌ی «پنل ادمین» برای مالک ظاهر می‌شود.

## قانون شماره‌ی یک: جداسازی کاربران

- هر کاربر پروفایل و کانتینر Docker جدا دارد؛ فایل‌های دیگران، رمزهای سرور و بایگانی مالک داخل کانتینر او **وجود ندارند**.
- پنل ادمین محتوای گفتگوها را نشان نمی‌دهد؛ فقط وضعیت و شمارش.
- ابزارهای مالک (بایگانی، Drive، گوشی) با نگهبان `pre_tool_call` برای بقیه بسته‌اند.

## نکته‌ی تلگرام

اتصال حساب شخصی (یوزربات) فقط برای کارهای خود کاربر روی حساب خودش است. ارسال انبوه، ادد اجباری یا پیام به غریبه‌ها خلاف قوانین تلگرام است و حساب را مسدود می‌کند — این مخزن عمداً چنین ابزارهایی ندارد.

## مجوز

کد خودمان برای استفاده‌ی آزاد منتشر شده است. موتور hermes-agent مجوز خودش را دارد.
