"""Admin panel + per-user shortcut keyboards for Agent Hermes (owner request 2026-11-11).

- Owner (Owner, 100000001): a reply keyboard «پنل ادمین» (Telegram shows it as the collapsible keyboard
  button on the right of the input field). Buttons run admin scripts DIRECTLY in this plugin, no LLM call:
  users list / detail / connect / disconnect, new user, pairing requests -> activate, system status, channel
  stats, sales report, festival status, ad now, auto-add status.
- Approved users (their own profiles): a small shortcut keyboard with their capabilities; a button press is
  rewritten into a plain request for their own agent.
- Unknown people who DM the bot: the owner gets one notice (max once per 6 h per person).
Rule #1: the panel shows only status, ids, counts and timestamps, never what a user wrote or asked.
"""
import asyncio, html, json, logging, os, re, shutil, subprocess, time

logger = logging.getLogger(__name__)

OWNER = "100000001"
ADMIN_PY = "/root/.hermes/shared-tools/admin/users_admin.py"
SYS_PY = "/usr/bin/python3"
HPY = "/root/.hermes/tools/python-3.14.7+20260901-linux-x64/bin/python3"
ADS = "/root/.hermes/ads/scripts"
STATE = "/root/.hermes/shared-tools/admin/panel_state.json"
ENV = "/root/.hermes/.env"
KB_VERSION = 20
NAME_RE = re.compile(r"^[a-z][a-z0-9]{1,20}$")

B_MENU, B_USERS, B_NEW, B_REQ = "🏠 منوی ادمین", "👥 کاربران", "➕ کاربر جدید", "📥 درخواست‌ها"
B_SYS, B_STATS, B_SALES, B_FEST = "🩺 وضعیت سیستم", "📊 آمار کانال", "💰 گزارش فروش", "🎉 جشنواره"
B_AD, B_ADD, B_CANCEL = "📢 تبلیغ کانال الان", "📈 ادد خودکار", "❌ لغو"
B_AD_OK = "✔️ تأیید ارسال تبلیغ"
B_PAY = "💳 پرداخت‌ها"
B_TOOLS = "🧰 ابزارهای شخصی من"
B_BIZ = "🤝 Hermes Business"
B_DOCS = "📄 بایگانی سند"
DOC_PY = "/root/.hermes/shared-tools/docs/docproc.py"
DOC_VPY = "/root/.hermes/shared-tools/docs/venv/bin/python"
DOC_INBOX = "/root/.hermes/archive-admin/.inbox"
D_NEW, D_SEARCH, D_FOLDERS, D_CHART, D_RECENT = "📄 خواندن سند جدید", "🔎 جستجو در بایگانی", "📂 پوشه‌ها", "📈 سابقه و نمودار", "🕘 آخرین سندها"
D_WORD, D_XLS, D_FIELDS, D_SUM, D_TR, D_PDF, D_DONE, D_MOVE = ("📝 متن کامل ← Word", "📊 جدول‌ها ← Excel", "🧾 فیلدهای فرم/فاکتور", "✂️ خلاصه",
                                                             "🌐 ترجمه", "🔍 اسکن ← PDF قابل جستجو", "🗂 فقط بایگانی (تمام)", "📂 تغییر پوشه")
OWNER_SESS = "/root/.hermes/userbot/owner"
OWNER_SEND = "/root/.hermes/userbot/send_as_user.py"
BZ_CHATS, BZ_UNREAD, BZ_CONTACTS, BZ_SEARCH = "💼 چت‌های من", "📥 نخوانده‌ها", "📇 مخاطب‌های من", "🔎 جستجو در پیام‌ها"
BZ_SUM, BZ_SUGG, BZ_TR, BZ_SEND, BZ_SEND_OK, BZ_DIGEST = ("📝 خلاصه‌ی این چت", "💡 پیشنهاد جواب", "🌐 ترجمه به فارسی",
                                                        "✉️ ارسال پیام در این چت", "✔️ بله، بفرست", "🧾 خلاصه‌ی همه‌ی نخوانده‌ها")
BZ_PFX = "💼 "
BZ_NEWMSG = "👤 ارسال به یک نفر"
BZ_MSGMENU, BZ_BULK, BZ_BULK_OK = "✉️ ارسال پیام", "👥 ارسال جمعی", "✔️ بله، ارسال جمعی"
BULK_PY = "/root/.hermes/shared-tools/userbot/bulk_send.py"
B_DOC = "🛠 عیب‌یابی و رفع مشکل"
D_RESTART, D_RESTART_OK, D_CLEAN, D_NOUS = "🔄 ری‌استارت ایجنت", "✔️ بله، ری‌استارت کن", "🧹 پاک‌سازی فضای دیسک", "🔑 ورود دوباره‌ی Nous"
DOCTOR_PY = "/root/.hermes/shared-tools/admin/doctor.py"
S_FIXUSER = "🛠 رفع مشکل این کاربر"
B_SUPPORT, SUP_OK, SUP_BAD, SUP_CANCEL = "🆘 پشتیبانی و رفع مشکل", "✅ مشکل حل شد", "❌ هنوز مشکل دارم", "❌ لغو پشتیبانی"
B_REQ_SHORT = "📥 درخواست‌ها"
S_INVITE = "🔗 لینک اتصال این پروفایل"
S_PREM, S_BASIC, S_FOREVER, S_OFF, S_ON, S_BACKU = "⭐ پرمیوم ۱ سال", "🔹 معمولی ۱ سال", "♾ پرمیوم دائمی", "⛔ قطع دسترسی", "✅ وصل دسترسی", "🔙 لیست کاربران"
B_TRIAL = "🎁 لینک تست"
B_TRIAL_NEW = {"basic": "🔹 تست معمولی", "premium": "⭐ تست پرمیوم"}
TRIAL_DAYS = "1"            # owner 2026-11-16: test links last 24 hours


def _routed_ids():
    """Telegram ids that have a DM profile route in the config the gateway STARTED with (routes are only
    read at start). Anyone approved after that must not talk until the restart, or he would fall
    through to the owner's default profile."""
    ids = set()
    try:
        for m in re.finditer(r"chat_id:\s*['\"]?(\d+)['\"]?", open("/root/.hermes/config.yaml").read()):
            ids.add(m.group(1))
    except Exception:
        logger.warning("admin-panel: cannot read routes", exc_info=True)
    return ids


ROUTED_AT_START = _routed_ids()
B_SUB, B_CHAN, B_CANCEL_BUY = "⭐ اشتراک من", "📢 کانال من", "❌ لغو خرید"
B_BUYREQ = "📞 درخواست خرید / تماس با پشتیبانی"
KIND_FA = {"buy": "🛒 خرید", "renew": "🔁 تمدید", "upgrade": "⬆️ ارتقا به"}
PERIOD_FA = {"year": "یک‌ساله", "month": "یک‌ماهه"}


def _buy_label(q):
    return f"{KIND_FA[q['kind']]} {q['title']} — میزبانی {PERIOD_FA[q['period']]} — {q['price']:,} تومان"


def _breakdown(q):
    parts = []
    if q.get("purchase"):
        parts.append(f"{'تفاوت قیمت ارتقا' if q['kind'] == 'upgrade' else 'خرید ربات (یک‌بار برای همیشه)'}: {q['purchase']:,}")
    parts.append(f"آبونمان میزبانی {PERIOD_FA.get(q['period'], '')}: {q['hosting']:,}")
    if q.get("credit"):
        parts.append(f"کسر اعتبار روزهای باقی‌مانده: −{q['credit']:,}")
    return "\n".join(parts) + f"\nجمع: {q['price']:,} تومان"
TIERS = "/root/.hermes/shared-tools/admin/tiers.json"
TIERS_CFG = "/root/.hermes/shared-tools/admin/tiers_config.json"
PREMIUM_ONLY = {"✉️ ارسال پیام", "👤 ارسال به یک نفر", "👥 ارسال جمعی", "✉️ ارسال پیام به یک نفر", "📲 پیام از حساب خودم", "📢 کانال من", "📇 حساب تلگرام من", "👥 مخاطب‌ها", "💬 چت‌ها", "📢 کانال‌ها", "👪 گروه‌ها",
                "📥 نخوانده‌ها", "🔎 جستجو در پیام‌ها", "📝 خلاصه‌ی این چت", "💡 پیشنهاد جواب", "🌐 ترجمه به فارسی", "✉️ ارسال پیام در این چت"}

USER_BUTTONS = {
    "⚖️ مشاور حقوقی": "[شروع حالت مشاور حقوقی] می‌خواهم یک سؤال یا پرونده‌ی حقوقی مطرح کنم. اول کوتاه بپرس موضوع چیست.",
    "📁 فایل‌های من": "فهرست فایل‌هایی را که قبلاً برایت فرستاده‌ام (از file-index خودم) دسته‌بندی‌شده نشانم بده.",
    "📲 پیام از حساب خودم": "می‌خواهم قابلیت فرستادن پیام از حساب تلگرام خودم را راه بیندازم یا استفاده کنم؛ قدم‌به‌قدم راهنمایی کن.",
    "🔎 جستجو در اینترنت": "می‌خواهم چیزی را در اینترنت جستجو کنی. بپرس دنبال چه هستم.",
    "📇 حساب تلگرام من": "می‌خواهم به حساب تلگرام خودم دسترسی داشته باشی تا مخاطب‌ها و چت‌هایم را ببینی (فقط خواندن). اول با account_read.py status ببین یوزرباتم وصل است یا نه؛ اگر نیست قدم‌به‌قدم راهش بینداز، اگر هست فقط در یک جمله بگو وصل است و کوتاه بپرس چه چیزی را ببینم (مخاطب‌ها، آخرین چت‌ها، یک چت خاص یا جستجو). مسیر فایل و جزئیات فنی ننویس.",
    "📢 کانال من": "می‌خواهم کانال یا گروه خودم را مدیریت کنم (پست، تبلیغ زمان‌بندی‌شده، آمار). قدم‌به‌قدم راهنمایی کن.",
}
B_HELP, B_NEWCHAT = "❓ راهنما", "🔄 گفتگوی تازه"
B_LEGAL, B_LEGAL_END = "⚖️ مشاور حقوقی", "↩️ پایان مشاوره‌ی حقوقی"
B_ACC = "📇 حساب تلگرام من"
ACC_SUB = {"👥 مخاطب‌ها": "contacts", "💬 چت‌ها": "private", "📢 کانال‌ها": "channel", "👪 گروه‌ها": "group"}
B_ACC_BACK = "🔙 منوی اصلی"
ACC_PY = "/root/.hermes/shared-tools/userbot/account_read.py"
ACC_PFX = {"private": "💬 ", "channel": "📢 ", "group": "👪 ", "contact": "📇 "}
LEGAL_END_TEXT = ("[پایان حالت مشاور حقوقی] مشاوره‌ی حقوقی تمام شد. از همین پیام به بعد از حالت مشاور حقوقی کاملاً خارج شو و "
                  "مثل یک دستیار عمومی، دوستانه و معمولی جواب بده؛ به احوال‌پرسی جواب ساده بده و دنبال پرونده نپرس. "
                  "فقط وقتی دوباره خودم سؤال حقوقی پرسیدم یا دکمه‌ی مشاور حقوقی را زدم، به حالت حقوقی برگرد. "
                  "در جواب همین پیام فقط یک جمله‌ی کوتاه بگو که به حالت عادی برگشتی.")
HELP_TEXT = ("🎛 دکمه‌های میانبر:\n"
             "🆘 پشتیبانی و رفع مشکل — اگر ایجنت درست کار نمی‌کند، مشکلت را بگو تا خودکار بررسی و رفع شود\n"
             "⭐ اشتراک من — نسخه‌ی معمولی یا پرمیوم، تمدید و خرید\n"
             "⚖️ مشاور حقوقی — سؤال، پرونده، قرارداد، لایحه\n"
             "📁 فایل‌های من — فایل‌هایی که قبلاً فرستادی\n"
             "📇 حساب تلگرام من (پرمیوم) — مخاطب‌ها، چت‌ها، نخوانده‌ها، جستجو؛ داخل هر چت: خلاصه، پیشنهاد جواب، ترجمه و ارسال پیام\n"
             "✉️ پیام به دیگران از حساب خودت (پرمیوم) — فقط بنویس، مثلاً «به علی بگو فردا جلسه نیست»\n"
             "📢 کانال من — پست و تبلیغ زمان‌بندی‌شده در کانال خودت (پرمیوم)\n"
             "🔎 جستجو در اینترنت\n"
             "🔄 گفتگوی تازه — شروع یک گفتگوی جدید\n\n"
             "می‌توانی پیام صوتی یا فایل هم بفرستی. دکمه‌ها را با آیکون کنار کادر پیام باز و بسته کن.")


B_MYACC, B_MYHIST, B_MYRCPT = "💳 حساب من", "🧾 سابقه‌ی خریدهایم", "📸 فیش‌ها و اسنادم"


ACC_ALLOWED_F = "/root/.hermes/shared-tools/admin/account_link_allowed.json"


def _acc_allowed(name):
    """Owner decision 2026-11-12: «📇 حساب تلگرام من» (own-account access) only for the profiles listed in this file."""
    try:
        allowed = json.load(open(ACC_ALLOWED_F))
        # "*" = every SEALED user profile (own container, 2026-11-14) + the owner's own profiles
        return name in allowed or ("*" in allowed and (_sealed(name) or name in OWNER_WORK))
    except Exception:
        logger.warning("admin-panel: cannot read %s", ACC_ALLOWED_F, exc_info=True)
        return False


def _user_rows(tier="premium", active=True, name=None):
    if not active:
        return [[B_SUB, B_MYACC], [B_SUPPORT, B_HELP]]
    if tier == "premium" and not _acc_allowed(name):
        return [["⚖️ مشاور حقوقی", "📁 فایل‌های من"], [B_CHAN, "🔎 جستجو در اینترنت"], [B_SUB, B_NEWCHAT], [B_HELP, B_SUPPORT], [B_MYACC]]
    if tier == "premium":
        return [["⚖️ مشاور حقوقی", "📁 فایل‌های من"], ["📇 حساب تلگرام من", B_CHAN],
                ["🔎 جستجو در اینترنت", B_SUB], [B_NEWCHAT, B_HELP], [B_SUPPORT, B_MYACC]]
    return [["⚖️ مشاور حقوقی", "📁 فایل‌های من"], ["🔎 جستجو در اینترنت", B_SUB], [B_NEWCHAT, B_HELP], [B_SUPPORT, B_MYACC]]


B_TOK = "📊 مصرف توکن"
TOK_PERIODS = {"📊 امروز": "today", "📊 ۷ روز": "7d", "📊 این ماه": "month"}


async def _tokens(event, text):
    """Owner: donut chart of AI token usage per model (all profiles + the oracle VPN admin bot)."""
    if text == B_TOK:
        await _send(event, "📊 مصرف توکن مدل‌های هوش مصنوعی — کدام بازه؟", [list(TOK_PERIODS), [B_MENU]])
        return True
    if text not in TOK_PERIODS:
        return None
    await _send(event, "⏳ در حال ساخت نمودار…")
    os.makedirs(DOC_INBOX, exist_ok=True)
    png = f"{DOC_INBOX}/tok-{int(time.time())}.png"
    code, o = await _run([DOC_VPY, "/root/.hermes/shared-tools/docs/token_dashboard.py", TOK_PERIODS[text], png], 180)
    try:
        r = json.loads(o.splitlines()[-1])
    except Exception:
        logger.warning("admin-panel token dashboard failed: %s", o[-300:])
        r = {}
    if not r.get("ok") or not os.path.exists(png):
        await _send(event, "نمودار ساخته نشد؛ کمی بعد دوباره بزن.", [list(TOK_PERIODS), [B_MENU]])
        return True
    cost = r.get("cost_usd") or 0
    total = r.get("total_tokens", 0)
    lines = [f"📊 {text[2:]}: {fa(f'{total:,}')} توکن · {fa(r.get('calls', 0))} درخواست · هزینه ${fa(f'{cost:.3f}')}"]
    if r.get("key_left") is not None:
        lines.append(f"کلید Haiku: ${fa(f'{float(r['key_left']):.2f}')} مانده")
    cap = rtl("\n".join(lines))
    try:
        with open(png, "rb") as fh:
            await event.raw_message.get_bot().send_photo(chat_id=int(event.source.chat_id), photo=fh, caption=cap[:1000])
    finally:
        os.remove(png)
    await _send(event, "📊 بازه‌ی دیگر؟", [list(TOK_PERIODS), [B_MENU]])
    return True


def _admin_rows():
    return [[B_BIZ, B_DOCS], [B_USERS, B_REQ], [B_PAY, B_TRIAL], [B_NEW, B_SYS],
            [B_STATS, B_SALES], [B_FEST, B_ADD], [B_AD, B_TOOLS], [B_DOC, B_TOK]]


def _docs_rows():
    return [[D_NEW, "🎬 مدیا"], [D_SEARCH, D_FOLDERS], [D_CHART, D_RECENT], [B_MENU]]


def _doc_rows():
    return [[D_WORD, D_XLS], [D_FIELDS, D_SUM], [D_TR, D_PDF], [D_MOVE, D_DONE], [D_NEW, B_MENU]]


async def _dash(kind, png):
    """Radial-gauge dashboard image (dashboard.py, headless Chromium)."""
    code, o = await _run([DOC_VPY, "/root/.hermes/shared-tools/docs/dashboard.py", kind, png], 180)
    try:
        return json.loads(o.splitlines()[-1])
    except Exception:
        logger.warning("admin-panel dashboard %s -> %s", kind, o[-300:])
        return None


async def _dp(*args, timeout=300):
    code, o = await _run([DOC_VPY, DOC_PY, *args], timeout)
    try:
        return json.loads(o.splitlines()[-1])
    except Exception:
        logger.warning("admin-panel docproc %s -> %s", args[:2], o[-300:])
        return None


def _doc_list(rows, title):
    L = [f"<b>{title}</b>", LINE]
    for r in rows or []:
        L.append(f"#{fa(r['id'])} · {esc(r['category'])} · {esc(r['title'] or '—')} · <i>{fa(r.get('date') or '')}</i>")
    if not rows:
        L.append("چیزی پیدا نشد.")
    btns = [f"⬇️ #{r['id']} {(r['title'] or '')[:20]}" for r in (rows or [])[:10]]
    return "\n".join(L), [btns[k:k + 2] for k in range(0, len(btns), 2)] + _docs_rows()


def _drive_line():
    """Owner archive mirror on his Google Drive: link + last sync (drive_mirror.py writes the status)."""
    try:
        d = json.load(open("/root/.hermes/archive-admin/.drive_status.json"))
    except Exception:
        return "\n\n☁️ Google Drive: هنوز همگام نشده."
    ago = lambda t: "همین الان" if time.time() - t < 120 else (f"{int((time.time() - t) // 60)} دقیقه پیش" if time.time() - t < 7200 else f"{int((time.time() - t) // 3600)} ساعت پیش")
    if d.get("last_error") and d.get("last_error_at", 0) > d.get("last_ok", 0):
        state = f"⚠️ آخرین ارسال ناموفق ({ago(d['last_error_at'])})؛ خودکار دوباره تلاش می‌شود."
    elif d.get("last_ok"):
        state = f"✅ همگام — {ago(d['last_ok'])}"
    else:
        state = "در انتظار اولین ارسال"
    link = f'\n<a href="{esc(d["link"])}">📂 باز کردن پوشه در Drive</a>' if d.get("link") else ""
    return f"\n\n☁️ <b>Google Drive</b>: {state}{link}"


async def _docs(event, text, st):
    """Owner document reader + server archive. Returns True when handled."""
    aw = (st.get("await") or {}).get(OWNER) or {}
    raw = event.raw_message
    bot = raw.get_bot()
    if text == B_DOCS:
        await _send(event, "<b>📄 بایگانی سند</b>\n" + LINE + "\nهمین‌جا روی 📎 بزن ← دوربین ← عکس بگیر و بفرست (یا عکس/PDF/Word از گالری)؛ بدون توضیح بفرستی، خودکار خوانده، دسته‌بندی و بایگانی می‌شود.\n"
                           "اگر با توضیح (کپشن) بفرستی، مثل قبل به ایجنت می‌رود.\n"
                           "هر وقت فایلی خواستی، با ⬇️ همین‌جا برایت می‌آید و در گوشی ذخیره می‌شود." + _drive_line(), _docs_rows(), html_mode=True)
        return True
    if text == D_NEW:
        st.setdefault("await", {})[OWNER] = {"kind": "doc_file"}
        _save(st)
        await _send(event, "📎 حالا عکس سند (با دوربین یا از گالری) یا فایل PDF/Word را بفرست.", [[B_CANCEL]])
        return True
    if aw.get("kind") == "doc_file" and (getattr(raw, "photo", None) or getattr(raw, "document", None)):
        st["await"].pop(OWNER, None)
        _save(st)
        os.makedirs(DOC_INBOX, exist_ok=True)
        if raw.photo:
            fobj, ext, orig = raw.photo[-1], ".jpg", "photo.jpg"
        else:
            fobj, orig = raw.document, raw.document.file_name or "file"
            ext = os.path.splitext(orig)[1].lower() or ".bin"
        path = f"{DOC_INBOX}/{int(time.time())}{ext}"
        tf = await bot.get_file(fobj.file_id)
        await tf.download_to_drive(path)
        await _send(event, "⏳ در حال خواندن و دسته‌بندی سند… (کمتر از یک دقیقه)")
        ex = await _dp("extract", path)
        if not ex or not (ex.get("text") or "").strip():
            await _send(event, "متنی از این سند خوانده نشد. عکس واضح‌تر و صاف‌تر بفرست.", _docs_rows())
            return True
        tpath = path + ".txt"
        open(tpath, "w", encoding="utf-8").write(ex["text"])
        an = await _dp("analyze", tpath) or {}
        meta = {**an, "orig_name": orig, "text": ex["text"]}
        mpath = path + ".meta.json"
        json.dump(meta, open(mpath, "w", encoding="utf-8"), ensure_ascii=False)
        ad = await _dp("archive-add", path, mpath) or {}
        old = st.get("doc_sel") or {}
        for f in (old.get("src"), old.get("txt"), (old.get("src") or "") + ".meta.json"):
            if f and os.path.exists(f):
                os.remove(f)                          # the archive keeps its own copy; inbox files are temporary
        st["doc_sel"] = {"id": ad.get("id"), "src": path, "txt": tpath, "title": an.get("title", ""), "filename": an.get("filename", "")}
        _save(st)
        fields = "\n".join(f"• {esc(k)}: {esc(v)}" for k, v in list((an.get("fields") or {}).items())[:8])
        L = [f"<b>📄 {esc(an.get('title') or 'سند')}</b>", LINE,
             f"📂 پوشه: <b>{esc(an.get('category', 'سایر'))}</b> · 📅 {fa(an.get('date', ''))}",
             f"🏷 {' '.join('#' + esc(t.replace(' ', '_')) for t in (an.get('tags') or [])[:5])}",
             f"📝 اسم فایل: <code>{esc(an.get('filename', ''))}</code>"]
        if fields:
            L += ["", fields]
        lk = f' · <a href="{esc(ad["link"])}">باز کردن در Drive</a>' if ad.get("link") else ""
        L += ["", ("♻️ این سند قبلاً بایگانی شده بود." if ad.get("duplicate") else
                   ("⚠️ Drive الان جواب نداد؛ سند در صف ماند و خودکار فرستاده می‌شود." if ad.get("queued") else "✅ در Google Drive بایگانی شد.")) + lk +
              ("" if ex.get("source") != "gemini" else " (خوانش با کمک هوش مصنوعی)"),
              "خروجی‌ها را با دکمه‌های پایین بگیر؛ برای پوشه‌ی دیگر بنویس «بذارش تو قراردادها» یا «پوشه‌ی جدید: بیمه»."]
        await _send(event, "\n".join(L), _doc_rows(), html_mode=True)
        return True
    sel = st.get("doc_sel") or {}
    if text in (D_WORD, D_XLS, D_PDF, D_FIELDS, D_SUM, D_TR) and sel.get("id"):
        await _send(event, "⏳ چند لحظه…")
        base = os.path.join(DOC_INBOX, (sel.get("filename") or str(sel["id"]))[:80])
        if text == D_WORD:
            r = await _dp("docx", sel["txt"], base + ".docx", sel.get("title", ""))
            outp = base + ".docx" if r and r.get("ok") else None
        elif text == D_XLS:
            r = await _dp("xlsx", sel["txt"], base + ".xlsx")
            outp = base + ".xlsx" if r and r.get("ok") else None
        elif text == D_PDF:
            r = await _dp("pdf", sel["src"], base + ".pdf", timeout=600)
            outp = base + ".pdf" if r and r.get("ok") else None
        else:
            kind = {D_FIELDS: "fields", D_SUM: "summary", D_TR: "translate"}[text]
            r = await _dp("task", kind, sel["txt"])
            if r and r.get("ok"):
                await _send(event, f"<b>{esc(text)}</b>\n{LINE}\n{esc(r['result'])}", _doc_rows(), html_mode=True)
            else:
                await _send(event, "الان انجام نشد؛ کمی بعد دوباره بزن.", _doc_rows())
            return True
        if not outp or not os.path.exists(outp):
            await _send(event, "ساخت فایل انجام نشد؛ دوباره امتحان کن.", _doc_rows())
            return True
        await _dp("archive-attach", str(sel["id"]), outp)
        with open(outp, "rb") as fh:
            await bot.send_document(chat_id=int(event.source.chat_id), document=fh, filename=os.path.basename(outp))
        os.remove(outp)
        await _send(event, "✅ فایل آماده شد و کنار سند در بایگانی هم ذخیره شد.", _doc_rows())
        return True
    if text == D_DONE and sel:
        for f in (sel.get("src"), sel.get("txt"), (sel.get("src") or "") + ".meta.json"):
            if f and os.path.exists(f):
                os.remove(f)                          # nothing of the document stays on the server
        st.pop("doc_sel", None)
        _save(st)
        await _send(event, "🗂 بایگانی شد.", _docs_rows())
        return True
    if text == D_MOVE and sel.get("id"):
        st.setdefault("await", {})[OWNER] = {"kind": "doc_move"}
        _save(st)
        await _send(event, "اسم پوشه را بفرست (مثلاً «قرارداد» یا یک پوشه‌ی جدید مثل «بیمه»):", [[B_CANCEL]])
        return True
    m = re.fullmatch(r"(?:بذارش|بزارش|بگذارش|ببرش|منتقلش کن)\s*(?:تو|توی|در|به)\s*(?:پوشه‌?ی?\s*)?(.+?)\s*(?:بذار|کن)?|پوشه‌?ی? جدید\s*[:：]\s*(.+)", text.strip())
    if (aw.get("kind") == "doc_move" or m) and sel.get("id") and text not in (B_CANCEL, B_MENU):
        st.get("await", {}).pop(OWNER, None)
        _save(st)
        cat = (m.group(1) or m.group(2)) if m else text.strip()
        cat = {"قراردادها": "قرارداد", "فاکتورها": "مالی-فاکتور", "مالی": "مالی-فاکتور", "نامه‌ها": "نامه", "بانک": "بانکی"}.get(cat.strip(), cat.strip())
        r = await _dp("archive-move", str(sel["id"]), cat)
        await _send(event, f"📂 منتقل شد به «{esc(r.get('category', cat))}»." if r and r.get("ok") else "جابه‌جایی انجام نشد.", _doc_rows(), html_mode=True)
        return True
    if text == D_SEARCH:
        st.setdefault("await", {})[OWNER] = {"kind": "doc_search"}
        _save(st)
        await _send(event, "🔎 چه چیزی را در بایگانی پیدا کنم؟ (کلمه، اسم، شماره، تاریخ مثل ۱۴۰۵-۰۸ یا اسم پوشه)", [[B_CANCEL]])
        return True
    if aw.get("kind") == "doc_search" and text not in (B_CANCEL, B_MENU):
        st["await"].pop(OWNER, None)
        _save(st)
        rows = await _dp("archive-search", text.strip().translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")) if re.search(r"[۰-۹]{4}-", text) else text.strip())
        t, kb = _doc_list(rows, f"🔎 نتیجه‌ی «{esc(text.strip())}»")
        await _send(event, t, kb, html_mode=True)
        return True
    if text == D_FOLDERS:
        cats = await _dp("archive-cats") or []
        if not cats:
            await _send(event, "بایگانی هنوز خالی است.", _docs_rows())
            return True
        L = ["<b>📂 پوشه‌ها</b>", LINE] + [f"📁 {esc(c)} — {fa(n)} سند" for c, n in cats]
        btns = [f"📁 {c}" for c, n in cats]
        await _send(event, "\n".join(L), [btns[k:k + 2] for k in range(0, len(btns), 2)] + _docs_rows(), html_mode=True)
        return True
    if text.startswith("📁 "):
        rows = await _dp("archive-list-cat", text[2:].strip())
        t, kb = _doc_list(rows, f"📁 {esc(text[2:].strip())}")
        await _send(event, t, kb, html_mode=True)
        return True
    if text == D_RECENT:
        t, kb = _doc_list(await _dp("archive-recent", "15"), "🕘 آخرین سندها")
        await _send(event, t, kb, html_mode=True)
        return True
    if text == D_CHART:
        png = f"{DOC_INBOX}/chart-{int(time.time())}.png"
        os.makedirs(DOC_INBOX, exist_ok=True)
        r = await _dash("docs", png)
        if not r or not r.get("ok") or not os.path.exists(png):
            await _send(event, "نمودار ساخته نشد.", _docs_rows())
            return True
        cap = rtl(f"📈 بایگانی اسناد: {fa(r['docs'])} سند · دیسک سرور {fa(round(r['disk_pct']))}٪")
        with open(png, "rb") as fh:
            await bot.send_photo(chat_id=int(event.source.chat_id), photo=fh, caption=cap[:1000])
        os.remove(png)
        await _send(event, "📈 سابقه‌ی بایگانی", _docs_rows())
        return True
    m = re.match(r"^⬇️ #(\d+)", text)
    if m:
        os.makedirs(DOC_INBOX, exist_ok=True)
        d = f"{DOC_INBOX}/dl-{int(time.time() * 1000)}"
        r = await _dp("archive-fetch", m.group(1), d, timeout=900) or {}
        try:
            if not r.get("ok"):
                await _send(event, "از Drive دریافت نشد." + (f' <a href="{esc(r["link"])}">باز کردن در Drive</a>' if r.get("link") else ""), _docs_rows(), html_mode=True)
                return True
            for f in r["files"]:
                with open(f, "rb") as fh:
                    await bot.send_document(chat_id=int(event.source.chat_id), document=fh, filename=os.path.basename(f))
        finally:
            shutil.rmtree(d, ignore_errors=True)       # downloaded only to send; nothing stays on the server
        await _send(event, f"⬇️ فایل‌های «{esc(r.get('title') or '')}» آمد؛ با یک لمس در گوشی ذخیره می‌شود.", _docs_rows(), html_mode=True)
        return True
    return None


# ---------------- owner MEDIA archive (Google Drive only; server keeps a metadata row) ----------------
MEDIA_PY = "/root/.hermes/shared-tools/docs/media.py"
M_MENU, M_SEARCH, M_CHART, M_RECENT, M_DONE = "🎬 مدیا", "🔎 جستجوی مدیا", "📈 نمودار مدیا", "🕘 آخرین مدیا", "✅ تمام"
M_FOLDERS = [("🖼", "عکس-تصویر"), ("🎥", "ویدیو"), ("🎙", "صدا-ویس"), ("✍️", "پرامپت"), ("🎨", "طراحی-پوستر"), ("📦", "سایر")]
MEDIA_INBOX = "/tmp/hermes-media-in"           # temp only: media.py deletes each file after upload


def _media_btn(folder):
    return next((f"{i} {f}" for i, f in M_FOLDERS if f == folder), f"🗂 {folder}")


def _media_folder_of(text, st):
    for i, f in M_FOLDERS:
        if text == f"{i} {f}":
            return f
    if text.startswith("🗂 ") and text[2:].strip() in (st.get("media_folders") or []):
        return text[2:].strip()
    return None


def _media_rows(st):
    btns = [_media_btn(f) for _, f in M_FOLDERS] + [f"🗂 {f}" for f in (st.get("media_folders") or [])]
    return [btns[k:k + 2] for k in range(0, len(btns), 2)] + [[M_SEARCH, M_RECENT], [M_CHART, B_DOCS], [B_MENU]]


async def _mp(*args, timeout=900, py=None):
    code, o = await _run([py or DOC_VPY, MEDIA_PY, *args], timeout)
    try:
        return json.loads(o.splitlines()[-1])
    except Exception:
        logger.warning("admin-panel media %s -> %s", args[:1], o[-300:])
        return None


def _media_file(raw):
    """(file object, original name) of any attachment, or (None, None)."""
    if getattr(raw, "photo", None):
        return raw.photo[-1], "photo.jpg"
    for attr, default in (("video", "video.mp4"), ("voice", "voice.ogg"), ("audio", "audio.mp3"),
                          ("video_note", "videonote.mp4"), ("animation", "animation.mp4"), ("document", "file")):
        o = getattr(raw, attr, None)
        if o:
            return o, getattr(o, "file_name", None) or default
    return None, None


def _is_av(raw):
    return any(getattr(raw, a, None) for a in ("video", "voice", "audio", "video_note", "animation")) or \
        str(getattr(getattr(raw, "document", None), "mime_type", "") or "").startswith(("video/", "audio/"))


def _media_list(rows, title):
    L = [f"<b>{title}</b>", LINE]
    icon = {"video": "🎥", "audio": "🎙", "image": "🖼", "text": "✍️"}
    for r in rows or []:
        lk = f' · <a href="{esc(r["link"])}">Drive</a>' if r.get("link") else ""
        L.append(f"{icon.get(r['kind'], '📦')} م{fa(r['id'])} · {esc(r['folder'])} · {esc(r['title'] or '—')} · <i>{fa(r['date'])}</i>{lk}")
    if not rows:
        L.append("چیزی پیدا نشد.")
    btns = [f"⬇️ م{r['id']} {(r['title'] or '')[:18]}" for r in (rows or [])[:10]]
    return "\n".join(L), [btns[k:k + 2] for k in range(0, len(btns), 2)]


async def _media_save(event, st, folder):
    """Download the attachment (Bot API <=20 MB, else through the owner's own session) and send it to Drive."""
    raw = event.raw_message
    bot = raw.get_bot()
    fobj, orig = _media_file(raw)
    if not fobj:
        return False
    os.makedirs(MEDIA_INBOX, mode=0o700, exist_ok=True)
    size = getattr(fobj, "file_size", 0) or 0
    cap = (getattr(raw, "caption", None) or "").strip()
    await _send(event, f"⏳ در حال ارسال به Google Drive{' (فایل بزرگ است، چند دقیقه)' if size > 20 * 1024 * 1024 else ''}…")
    if size > 20 * 1024 * 1024:
        r = await _mp("bigfetch", MEDIA_INBOX, str(size), str(raw.date.timestamp()), timeout=1800, py=HPY)
        if not r or not r.get("ok"):
            await _send(event, "این فایل بزرگ دریافت نشد" + (f" ({esc(r.get('error'))})" if r else "") + ". یک بار دیگر بفرست.", _media_rows(st), html_mode=True)
            return True
        path, orig = r["path"], (orig if orig not in ("file", "video.mp4") else r.get("name") or orig)
    else:
        ext = os.path.splitext(orig)[1] or ".bin"
        path = f"{MEDIA_INBOX}/{int(time.time() * 1000)}{ext}"
        tf = await bot.get_file(fobj.file_id)
        await tf.download_to_drive(path)
    mpath = path + ".meta.json"
    json.dump({"folder": folder or "", "caption": cap, "orig_name": orig}, open(mpath, "w", encoding="utf-8"), ensure_ascii=False)
    r = await _mp("add", path, mpath, timeout=3600) or {}
    for f in (path, mpath):                                # nothing of the media stays on the server
        if os.path.exists(f) and not r.get("queued"):
            os.remove(f)
    if r.get("duplicate"):
        await _send(event, f"این فایل قبلاً ذخیره شده (م{fa(r['id'])}).", None)
    elif r.get("ok"):
        extra = " · ".join(x for x in (f"⏱ {fa(int(r['duration']))} ثانیه" if r.get("duration") and r.get("kind") in ("video", "audio") else "",
                                       f"📐 {r['resolution']}" if r.get("resolution") else "") if x)
        lk = f'\n<a href="{esc(r["link"])}">🔗 باز کردن در Drive</a>' if r.get("link") else ""
        await _send(event, f"✅ م{fa(r['id'])} در پوشه‌ی «{esc(r['folder'])}» ذخیره شد{(' · ' + extra) if extra else ''}{lk}", None, html_mode=True)
    elif r.get("queued"):
        await _send(event, "⚠️ ارسال به Drive الان نشد؛ فایل در صف ماند و خودکار دوباره فرستاده می‌شود.", None)
    else:
        await _send(event, "ذخیره نشد؛ دوباره بفرست.", None)
    return True


async def _media(event, text, st):
    """Owner media section. Returns True when handled, None otherwise."""
    aw = (st.get("await") or {}).get(OWNER) or {}
    raw = event.raw_message
    bot = raw.get_bot()
    fobj, _ = _media_file(raw)
    if text == M_MENU:
        st.setdefault("await", {})[OWNER] = {"kind": "media_menu", "ts": time.time()}
        _save(st)
        try:
            du = shutil.disk_usage("/")
            disk = f"\n💽 دیسک سرور: {fa(int(du.used * 100 / du.total))}٪ پر" + (" ⚠️" if du.used / du.total > 0.8 else "")
        except Exception:
            disk = ""
        await _send(event, "<b>🎬 مدیا</b>\n" + LINE + "\nیک پوشه را بزن، بعد هر چند عکس/ویدیو/ویس/فایل که خواستی بفرست؛ همه مستقیم به Google Drive می‌رود "
                    "(روی سرور نمی‌ماند). توضیح زیر فایل = توضیح/برچسب.\n"
                    "اگر همین‌جا بدون انتخاب پوشه بفرستی، نوعش خودکار تشخیص داده می‌شود.\n"
                    "پوشه‌ی تازه: بنویس «پوشه‌ی جدید: تبلیغات دیوار»" + disk, _media_rows(st), html_mode=True)
        return True
    folder = _media_folder_of(text, st)
    if folder:
        st.setdefault("await", {})[OWNER] = {"kind": "media_in", "folder": folder, "ts": time.time()}
        _save(st)
        hint = ("✍️ متن پرامپت را بفرست (خط اول = عنوان، #برچسب). بعدش عکس/ویدیوی نتیجه را بفرستی، کنار همان پرامپت ذخیره می‌شود."
                if folder == "پرامپت" else "📎 فایل/عکس/ویدیو/ویس بفرست (چندتایی و آلبوم هم می‌شود).")
        await _send(event, f"🗂 پوشه‌ی «{esc(folder)}»\n{hint}\nآخر کار «{M_DONE}» را بزن.", [[M_DONE], [M_MENU, B_MENU]], html_mode=True)
        return True
    m = re.fullmatch(r"پوشه‌?ی? جدید\s*[:：]\s*(.+)", text.strip()) if aw.get("kind") in ("media_menu", "media_in") else None
    if m:
        name = re.sub(r"[\\/:*?\"<>|#\n]+", " ", m.group(1)).strip()[:30]
        if name:
            st.setdefault("media_folders", [])
            if name not in st["media_folders"] and name not in [f for _, f in M_FOLDERS]:
                st["media_folders"].append(name)
            st.setdefault("await", {})[OWNER] = {"kind": "media_in", "folder": name, "ts": time.time()}
            _save(st)
            await _send(event, f"🗂 پوشه‌ی «{esc(name)}» ساخته شد. حالا فایل‌ها را بفرست؛ آخر کار «{M_DONE}».", [[M_DONE], [M_MENU, B_MENU]], html_mode=True)
            return True
    if text == M_DONE:
        st.setdefault("await", {})[OWNER] = {"kind": "media_menu", "ts": time.time()}
        st.pop("media_last_prompt", None)
        _save(st)
        await _send(event, "✅ تمام شد.", _media_rows(st))
        return True
    if aw.get("kind") in ("media_in", "media_menu", "media_auto") and fobj:
        folder = aw.get("folder") if aw.get("kind") == "media_in" else ""
        lp = st.get("media_last_prompt") or {}
        if folder == "پرامپت" and lp.get("id") and time.time() - lp.get("ts", 0) < 3600:
            # result of the prompt just saved: keep prompt + result together
            os.makedirs(MEDIA_INBOX, mode=0o700, exist_ok=True)
            size = getattr(fobj, "file_size", 0) or 0
            if size > 20 * 1024 * 1024:
                r = await _mp("bigfetch", MEDIA_INBOX, str(size), str(raw.date.timestamp()), timeout=1800, py=HPY) or {}
                path = r.get("path")
            else:
                _, orig = _media_file(raw)
                path = f"{MEDIA_INBOX}/{int(time.time() * 1000)}{os.path.splitext(orig)[1] or '.bin'}"
                await (await bot.get_file(fobj.file_id)).download_to_drive(path)
            r = await _mp("attach", str(lp["id"]), path) if path else None
            if path and os.path.exists(path):
                os.remove(path)
            await _send(event, f"✅ نتیجه کنار پرامپت م{fa(lp['id'])} ذخیره شد." if r and r.get("ok") else "ذخیره نشد؛ دوباره بفرست.", None)
            return True
        if aw.get("kind") == "media_auto":
            st["await"].pop(OWNER, None)
            _save(st)
        return await _media_save(event, st, folder)
    if aw.get("kind") == "media_in" and aw.get("folder") == "پرامپت" and text and text not in (B_CANCEL, B_MENU, M_MENU, B_DOCS):
        os.makedirs(MEDIA_INBOX, mode=0o700, exist_ok=True)
        tp = f"{MEDIA_INBOX}/{int(time.time() * 1000)}.txt"
        open(tp, "w", encoding="utf-8").write(text)
        r = await _mp("prompt", tp, "پرامپت") or {}
        if r.get("ok") and not r.get("duplicate"):
            st["media_last_prompt"] = {"id": r["id"], "ts": time.time()}
            _save(st)
            await _send(event, f"✍️ پرامپت م{fa(r['id'])} ذخیره شد. اگر عکس/ویدیوی نتیجه‌اش را داری، همین الان بفرست؛ کنارش می‌رود.", None)
        else:
            await _send(event, "ذخیره نشد؛ دوباره بفرست." if not r.get("duplicate") else "این پرامپت قبلاً ذخیره شده.", None)
        return True
    if text == M_SEARCH:
        st.setdefault("await", {})[OWNER] = {"kind": "media_search"}
        _save(st)
        await _send(event, "🔎 چه چیزی را در مدیا پیدا کنم؟ (کلمه، برچسب، اسم پوشه، تاریخ مثل ۱۴۰۵-۰۸)", [[B_CANCEL]])
        return True
    if aw.get("kind") == "media_search" and text not in (B_CANCEL, B_MENU):
        st["await"].pop(OWNER, None)
        _save(st)
        t, kb = _media_list(await _mp("search", text.strip(), timeout=60), f"🔎 مدیا: «{esc(text.strip())}»")
        await _send(event, t, kb + _media_rows(st), html_mode=True)
        return True
    if text == M_RECENT:
        t, kb = _media_list(await _mp("recent", "15", timeout=60), "🕘 آخرین مدیا")
        await _send(event, t, kb + _media_rows(st), html_mode=True)
        return True
    if text == M_CHART:
        os.makedirs(MEDIA_INBOX, mode=0o700, exist_ok=True)
        png = f"{MEDIA_INBOX}/chart-{int(time.time())}.png"
        r = await _dash("media", png)
        if not r or not r.get("ok") or not os.path.exists(png):
            await _send(event, "نمودار ساخته نشد" + ("؛ Google Drive جواب نداد." if r and r.get("error") == "drive_unreachable" else "."), _media_rows(st))
            return True
        cap = rtl(f"📈 مدیا: {fa(r['media'])} فایل · Google Drive {fa(round(r['drive_pct']))}٪ پر"
                  + ("\n⚠️ فضای Drive رو به پر شدن است." if r["drive_pct"] >= 80 else ""))
        with open(png, "rb") as fh:
            await bot.send_photo(chat_id=int(event.source.chat_id), photo=fh, caption=cap[:1000])
        os.remove(png)
        await _send(event, "📈 سابقه‌ی مدیا", _media_rows(st))
        return True
    m = re.match(r"^⬇️ م(\d+)", text)
    if m:
        os.makedirs(MEDIA_INBOX, mode=0o700, exist_ok=True)
        r = await _mp("fetch", m.group(1), MEDIA_INBOX, timeout=1800) or {}
        if not r.get("ok"):
            await _send(event, "پیدا نشد.", _media_rows(st))
            return True
        if r.get("too_big") or not r.get("path"):
            await _send(event, f'این فایل بزرگ است؛ از Drive بازش کن:\n<a href="{esc(r.get("link") or "")}">🔗 {esc(r.get("name") or "")}</a>', _media_rows(st), html_mode=True)
            return True
        try:
            with open(r["path"], "rb") as fh:
                await bot.send_document(chat_id=int(event.source.chat_id), document=fh, filename=os.path.basename(r["path"]))
        finally:
            os.remove(r["path"])
        return True
    return None


# ---------------- 💳 customer account (owner only): purchases, payments, receipts, purchase documents ----------------
S_ACCOUNT = "💳 حساب مشتری"
A_HIST, A_RCPT, A_DOCS, A_PAY, A_FILE, A_NOTE, A_REFUND = ("🧾 سابقه‌ی خرید", "📸 فیش‌ها", "📂 اسناد خرید", "➕ ثبت پرداخت دستی",
                                                       "📎 افزودن فیش/سند", "📝 یادداشت", "↩️ ثبت برگشت وجه")
LEDGER_TMP = "/tmp/hermes-ledger-in"
LED_ICON = {"order": "🛒", "receipt": "📸", "payment": "✅", "manual_payment": "💵", "reject": "✖️", "refund": "↩️",
            "tier": "⭐", "trial": "🎁", "note": "📝", "doc": "📂"}


def _jdt(ts):
    """Unix time -> Jalali 'YYYY/MM/DD HH:MM' (Tehran time), Persian digits."""
    t = time.gmtime(ts + 12600)
    gy, gm, gd = t.tm_year, t.tm_mon, t.tm_mday
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = 355666 + 365 * gy + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400 + gd + g_d_m[gm - 1]
    jy = -1595 + 33 * (days // 12053); days %= 12053
    jy += 4 * (days // 1461); days %= 1461
    if days > 365:
        jy += (days - 1) // 365; days = (days - 1) % 365
    jm = 1 + days // 31 if days < 186 else 7 + (days - 186) // 30
    jd = 1 + (days % 31 if days < 186 else (days - 186) % 30)
    return fa(f"{jy}/{jm:02d}/{jd:02d} {t.tm_hour:02d}:{t.tm_min:02d}")


def _cacc_rows(sel):
    return [[A_HIST], [A_RCPT, A_DOCS], [A_PAY, A_FILE], [A_NOTE, A_REFUND], [f"👤 {sel}", B_MENU]]


def _money(n):
    return fa(f"{int(n):,}") + " تومان"


async def _account(event, text, st):
    sel = st.get("sel")
    aw = (st.get("await") or {}).get(OWNER) or {}
    if not sel or not (text in (S_ACCOUNT, A_HIST, A_RCPT, A_DOCS, A_PAY, A_FILE, A_NOTE, A_REFUND) or aw.get("kind", "").startswith("acc_")):
        return None
    raw = event.raw_message
    bot = raw.get_bot()
    if aw.get("kind", "").startswith("acc_") and text in (B_CANCEL,):
        return None
    if text == S_ACCOUNT:
        r = await _admin_json("ledger", sel)
        s_ = r.get("summary") or {}
        E = r.get("entries") or []
        ti = r.get("tier") or {}
        L = [f"<b>💳 حساب مشتری — {esc(sel)}</b>", LINE,
             f"💎 {_tier_label(ti.get('tier'), ti.get('until'), ti.get('active'))}" if ti else "",
             f"💰 جمع پرداخت‌ها: <b>{_money(s_.get('paid', 0))}</b>" + (f" · برگشتی: {_money(s_['refund'])}" if s_.get("refund") else ""),
             f"🛒 خریدها: {fa(s_.get('purchases', 0))} · سفارش‌ها: {fa(s_.get('orders', 0))}",
             f"📸 فیش‌ها: {fa(s_.get('receipts', 0))} · 📂 اسناد: {fa(s_.get('docs', 0))}",
             f"📅 اولین ثبت: {_jdt(s_['first']) if s_.get('first') else '—'}",
             f"🕘 آخرین خرید: {_jdt(s_['last_purchase']) if s_.get('last_purchase') else '—'}", LINE]
        if E:
            L.append("<b>آخرین رویدادها</b>")
            for e in E[-5:][::-1]:
                L.append(f"{LED_ICON.get(e['type'], '•')} {_jdt(e['ts'])} — {esc(e['text'])}" + (f" · {_money(e['amount'])}" if e.get("amount") else ""))
        else:
            L.append("هنوز چیزی ثبت نشده.")
        await _send(event, "\n".join(x for x in L if x != ""), _cacc_rows(sel), html_mode=True)
        return True
    if text == A_HIST:
        E = (await _admin_json("ledger", sel)).get("entries") or []
        L = [f"<b>🧾 سابقه‌ی کامل — {esc(sel)}</b>", LINE]
        for e in E[::-1][:60]:
            L.append(f"{LED_ICON.get(e['type'], '•')} <b>{_jdt(e['ts'])}</b>\n     {esc(e['text'])}" + (f"\n     مبلغ: {_money(e['amount'])}" if e.get("amount") else "")
                     + (" · 📎 فایل دارد" if e.get("file") else ""))
        if not E:
            L.append("هنوز چیزی ثبت نشده.")
        await _send(event, "\n".join(L), _cacc_rows(sel), html_mode=True)
        return True
    if text in (A_RCPT, A_DOCS):
        E = (await _admin_json("ledger", sel)).get("entries") or []
        want = [e for e in E if e.get("file") and ((e["type"] == "receipt") == (text == A_RCPT))]
        if not want:
            await _send(event, "فیشی ثبت نشده." if text == A_RCPT else "سندی ثبت نشده.", _cacc_rows(sel))
            return True
        for e in want[-10:]:
            cap = rtl(f"{LED_ICON.get(e['type'], '•')} {_jdt(e['ts'])}\n{e['text']}" + (f"\nمبلغ: {_money(e['amount'])}" if e.get("amount") else ""))[:1000]
            if not os.path.exists(e["file"]):
                continue
            with open(e["file"], "rb") as fh:
                if e["file"].lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                    await bot.send_photo(chat_id=int(event.source.chat_id), photo=fh, caption=cap)
                else:
                    await bot.send_document(chat_id=int(event.source.chat_id), document=fh, filename=os.path.basename(e["file"]), caption=cap)
        await _send(event, f"{text} — {esc(sel)}" + (" (۱۰ مورد آخر)" if len(want) > 10 else ""), _cacc_rows(sel), html_mode=True)
        return True
    prompts = {A_PAY: ("acc_pay", "💵 مبلغ و توضیح را بفرست، مثلاً:\n<code>۹۰۰۰۰۰ خرید پرمیوم سالانه کارت‌به‌کارت</code>"),
               A_REFUND: ("acc_refund", "↩️ مبلغ برگشتی و دلیل را بفرست، مثلاً:\n<code>۲۰۰۰۰۰ برگشت بخشی از وجه</code>"),
               A_NOTE: ("acc_note", "📝 یادداشت را بفرست:"),
               A_FILE: ("acc_file", "📎 عکس فیش یا فایل سند خرید را بفرست (با دوربین یا از گالری).\nاگر فیش است، در توضیح زیرش بنویس «فیش» و مبلغ؛ مثلاً «فیش ۹۰۰۰۰۰».")}
    if text in prompts:
        st.setdefault("await", {})[OWNER] = {"kind": prompts[text][0]}
        _save(st)
        await _send(event, prompts[text][1], [[B_CANCEL]], html_mode=True)
        return True
    kind = aw.get("kind")
    if kind in ("acc_pay", "acc_refund"):
        m = re.match(r"^\s*([\d۰-۹,٬،]+)\s*(.*)$", text or "", re.S)
        if not m:
            await _send(event, "اول مبلغ را با عدد بنویس، بعد توضیح.", [[B_CANCEL]])
            return True
        amount = re.sub(r"[,٬،]", "", m.group(1)).translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
        st["await"].pop(OWNER, None)
        _save(st)
        r = await _admin_json("ledger-add", sel, "payment" if kind == "acc_pay" else "refund", amount,
                              m.group(2).strip() or ("پرداخت دستی" if kind == "acc_pay" else "برگشت وجه"))
        await _send(event, f"✅ ثبت شد: {_money(int(amount))}" if r.get("ok") else "ثبت نشد.", _cacc_rows(sel))
        return True
    if kind == "acc_note" and text:
        st["await"].pop(OWNER, None)
        _save(st)
        r = await _admin_json("ledger-add", sel, "note", "0", text.strip())
        await _send(event, "📝 یادداشت ثبت شد." if r.get("ok") else "ثبت نشد.", _cacc_rows(sel))
        return True
    if kind == "acc_file":
        fobj, orig = _media_file(raw)
        if not fobj:
            await _send(event, "عکس یا فایل بفرست.", [[B_CANCEL]])
            return True
        st["await"].pop(OWNER, None)
        _save(st)
        os.makedirs(LEDGER_TMP, mode=0o700, exist_ok=True)
        path = f"{LEDGER_TMP}/{int(time.time() * 1000)}{os.path.splitext(orig)[1] or '.jpg'}"
        try:
            await (await bot.get_file(fobj.file_id)).download_to_drive(path)
            cap = (getattr(raw, "caption", None) or "").strip()
            is_rcpt = "فیش" in cap or "رسید" in cap
            r = await _admin_json("ledger-file", sel, "receipt" if is_rcpt else "doc", path, cap or ("فیش" if is_rcpt else "سند خرید"))
            if r.get("ok") and is_rcpt:
                m = re.search(r"[\d۰-۹][\d۰-۹,٬،]{3,}", cap)
                if m:                                    # a receipt with an amount counts as a payment, unless that payment is already recorded
                    amt = re.sub(r"[,٬،]", "", m.group(0)).translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
                    E = (await _admin_json("ledger", sel)).get("entries") or []
                    dup = any(e["type"] in ("payment", "manual_payment") and e.get("amount") == int(amt) and time.time() - e["ts"] < 7 * 86400 for e in E)
                    if not dup:
                        await _admin_json("ledger-add", sel, "payment", amt, f"پرداخت با فیش ({cap})")
        finally:
            if os.path.exists(path):
                os.remove(path)
        await _send(event, ("📸 فیش ثبت شد." if is_rcpt else "📂 سند ثبت شد.") if r.get("ok") else "ثبت نشد.", _cacc_rows(sel))
        return True
    return None


# customer's own view of HIS account (only his ledger; the owner's internal notes are never shown)
MY_TYPES = ("order", "payment", "manual_payment", "refund", "tier", "trial")   # no receipts / documents / notes for customers
MY_TEXT = {"tier": "تغییر نسخه", "manual_payment": "پرداخت ثبت شد"}


async def _my_account(event, name, text, rows):
    r = await _admin_json("ledger", name)
    E = [e for e in (r.get("entries") or []) if e.get("type") in MY_TYPES]
    s_ = r.get("summary") or {}
    ti = r.get("tier") or {}
    sub = [[B_MYHIST]] + rows
    # owner-typed descriptions (manual payment / refund) are never shown: a generic label + the amount only
    def _label(e):
        t = e.get("text") or ""
        if e["type"] == "tier":
            plan = "⭐ پرمیوم" if "premium" in t or "پرمیوم" in t else "🔹 معمولی"
            return f"فعال/تمدید پلن {plan}" + (" · دائمی" if "دائمی" in t else "")
        return {"manual_payment": "پرداخت", "refund": "برگشت وجه", "trial": "شروع دوره‌ی آزمایشی"}.get(e["type"], t)
    E = [{**e, "text": _label(e)} for e in E]
    if text == B_MYACC:
        L = ["<b>💳 حساب من</b>", LINE,
             f"💎 {_tier_label(ti.get('tier'), ti.get('until'), ti.get('active'))}" if ti else "",
             f"💰 جمع پرداخت‌ها: <b>{_money(s_.get('paid', 0))}</b>" + (f" · برگشتی: {_money(s_['refund'])}" if s_.get("refund") else ""),
             f"🛒 خریدها: {fa(s_.get('purchases', 0))}",
             f"🕘 آخرین خرید: {_jdt(s_['last_purchase']) if s_.get('last_purchase') else '—'}", LINE]
        if E:
            L.append("<b>آخرین رویدادها</b>")
            for e in E[-5:][::-1]:
                L.append(f"{LED_ICON.get(e['type'], '•')} {_jdt(e['ts'])} — {esc(e['text'])}" + (f" · {_money(e['amount'])}" if e.get("amount") else ""))
        else:
            L.append("هنوز خریدی ثبت نشده.")
        await _send(event, "\n".join(x for x in L if x != ""), sub, html_mode=True)
    elif text == B_MYHIST:
        L = ["<b>🧾 سابقه‌ی خریدهایم</b>", LINE]
        for e in E[::-1][:60]:
            L.append(f"{LED_ICON.get(e['type'], '•')} <b>{_jdt(e['ts'])}</b>\n     {esc(e['text'])}" + (f"\n     مبلغ: {_money(e['amount'])}" if e.get("amount") else ""))
        if not E:
            L.append("هنوز خریدی ثبت نشده.")
        await _send(event, "\n".join(L), sub, html_mode=True)
    else:
        await _send(event, "💳 حساب من", sub)


# ---------------- premium: connect the user's OWN Telegram account inside the bot (no api_id, no LLM) ----------------
B_LINK, B_UNLINK, B_UNLINK_OK, B_LINK_CANCEL, B_SAVED = ("🔗 وصل کردن اکانت تلگرام", "🔌 قطع اتصال اکانت", "✔️ بله، قطع کن",
                                                       "❌ لغو اتصال", "⭐ پیام‌های ذخیره‌شده")
LOGIN_PY = "/root/.hermes/shared-tools/userbot/login.py"


async def _login(args, stdin_text=None, timeout=120):
    p = await asyncio.create_subprocess_exec(HPY, LOGIN_PY, *args, stdin=asyncio.subprocess.PIPE,
                                             stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        o, e = await asyncio.wait_for(p.communicate((stdin_text or "").encode()), timeout)
    except asyncio.TimeoutError:
        p.kill()
        return {"ok": False, "error": "timeout"}
    try:
        return json.loads(o.decode().strip().splitlines()[-1])
    except Exception:
        logger.warning("admin-panel: login.py %s failed: %s", args[0], (e or b"").decode()[-300:])   # never the code/password
        return {"ok": False, "error": "internal"}


async def _delete_msg(event):
    """The login code / password must not stay in the chat (and Telegram voids a code that appears in a chat)."""
    try:
        await event.raw_message.get_bot().delete_message(chat_id=int(event.source.chat_id), message_id=int(event.raw_message.message_id))
    except Exception:
        logger.warning("admin-panel: could not delete a login message", exc_info=True)


LINK_ERR = {"phone_invalid": "این شماره درست نیست. شماره را با کد کشور بفرست، مثل ‎+98912xxxxxxx",
            "code_invalid": "کد اشتباه بود. دوباره بفرست (با خط تیره بین عددها، مثل 1-2-3-4-5).",
            "code_expired": "کد منقضی شد. «🔗 وصل کردن اکانت تلگرام» را دوباره بزن تا کد تازه بیاید.",
            "password_invalid": "رمز دومرحله‌ای اشتباه بود. دوباره بفرست.",
            "no_pending_login": "مهلت ورود تمام شد. «🔗 وصل کردن اکانت تلگرام» را دوباره بزن."}


async def _link(event, uid, name, text, st, rows):
    sess = f"/root/.hermes/profiles/{name}/userbot/{name}"
    aw = (st.get("await") or {}).get(uid) or {}
    kind = aw.get("kind", "")
    connected = os.path.exists(sess + ".session") and os.path.exists(sess + ".creds.json")
    skip = {"action": "skip", "reason": "account link"}
    cancel = [[B_LINK_CANCEL]]

    def set_aw(k):
        if k:
            st.setdefault("await", {})[uid] = {"kind": k, "ts": time.time()}
        else:
            st.get("await", {}).pop(uid, None)
        _save(st)

    if text == B_LINK_CANCEL:
        set_aw(None)
        if not connected:
            for f in (sess + ".pending_login.json", sess + ".session"):
                if os.path.exists(f):
                    os.remove(f)
        await _send(event, "اتصال لغو شد.", rows)
        return skip
    if text == B_LINK:
        if connected:
            await _send(event, "✅ اکانت تلگرامت از قبل وصل است.", _acc_rows())
            return skip
        set_aw("link_phone")
        await _send(event, "<b>🔗 وصل کردن اکانت تلگرام</b>\n" + LINE +
                    "\nبا این کار ایجنت می‌تواند به درخواست خودت پیام‌های ذخیره‌شده، چت‌ها و مخاطب‌هایت را بخواند. "
                    "چیزی از چت‌هایت روی سرور ذخیره نمی‌شود و هر وقت بخواهی با «🔌 قطع اتصال اکانت» قطعش می‌کنی.\n\n"
                    "📱 شماره‌ی تلگرامت را با کد کشور بفرست، مثل:\n<code>+98912xxxxxxx</code>", cancel, html_mode=True)
        return skip
    if kind == "link_phone" and text and len(re.sub(r"\D", "", text.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")))) < 8:
        await _send(event, "این شماره نیست. شماره‌ی تلگرامت را با کد کشور بفرست، یا «❌ لغو اتصال» را بزن.", cancel)
        return skip
    if kind == "link_phone" and text:
        await _send(event, "⏳ در حال گرفتن کد از تلگرام…")
        r = await _login(["send", sess, text])
        if r.get("already"):
            set_aw(None)
            await _send(event, "✅ اکانتت از قبل وصل است.", _acc_rows())
        elif r.get("ok"):
            set_aw("link_code")
            await _send(event, "📩 تلگرام همین الان یک کد ورود در اپ تلگرامت فرستاد (از طرف «Telegram»).\n\n"
                        "⚠️ کد را <b>با خط تیره یا فاصله بین عددها</b> بفرست، مثل <code>1-2-3-4-5</code>؛ "
                        "اگر کد را یک‌تکه در چت بفرستی، تلگرام برای امنیت باطلش می‌کند.\nپیامت بلافاصله پاک می‌شود.", cancel, html_mode=True)
        elif r.get("error") == "flood":
            set_aw(None)
            await _send(event, f"تلگرام گفت کمی صبر کن ({fa(int(r.get('seconds', 60)) // 60 + 1)} دقیقه)، بعد دوباره امتحان کن.", rows)
        else:
            await _send(event, LINK_ERR.get(r.get("error"), "الان نشد؛ چند دقیقه بعد دوباره «🔗 وصل کردن اکانت تلگرام» را بزن."), cancel)
        return skip
    if kind == "link_code" and text and not re.fullmatch(r"[\d۰-۹\s\-_.,/]{5,30}", text.strip()):
        await _send(event, "این کد ورود نیست. کد ۵رقمی را با خط تیره بفرست (مثل 1-2-3-4-5)، یا «❌ لغو اتصال» را بزن.", cancel)
        return skip
    if kind == "link_code" and text:
        await _delete_msg(event)
        r = await _login(["code", sess], stdin_text=text)
        if r.get("needs_password"):
            set_aw("link_pw")
            await _send(event, "🔐 اکانتت رمز دومرحله‌ای دارد. رمز را بفرست (پیامت بلافاصله پاک می‌شود و جایی ذخیره نمی‌شود).", cancel)
        elif r.get("logged_in"):
            set_aw(None)
            await _send(event, f"✅ اکانت تلگرامت وصل شد{(' — ' + esc(r['name'])) if r.get('name') else ''}.\n"
                        "حالا از «📇 حساب تلگرام من» پیام‌های ذخیره‌شده، چت‌ها و مخاطب‌هایت را ببین، یا از خود ایجنت بپرس.", _acc_rows(), html_mode=True)
        else:
            if r.get("error") in ("code_expired", "no_pending_login"):
                set_aw(None)
            await _send(event, LINK_ERR.get(r.get("error"), "الان نشد؛ دوباره «🔗 وصل کردن اکانت تلگرام» را بزن."), cancel if r.get("error") == "code_invalid" else rows)
        return skip
    if kind == "link_pw" and text:
        await _delete_msg(event)
        r = await _login(["password", sess], stdin_text=text)
        if r.get("logged_in"):
            set_aw(None)
            await _send(event, "✅ اکانت تلگرامت وصل شد. حالا از «📇 حساب تلگرام من» استفاده کن.", _acc_rows())
        else:
            await _send(event, LINK_ERR.get(r.get("error"), "الان نشد؛ دوباره رمز را بفرست."), cancel)
        return skip
    if text == B_UNLINK:
        await _send(event, "اتصال اکانت تلگرامت قطع شود؟ ایجنت دیگر به چت‌ها و پیام‌های ذخیره‌شده‌ات دسترسی ندارد.", [[B_UNLINK_OK], [B_ACC_BACK]])
        return skip
    if text == B_UNLINK_OK:
        r = await _login(["logout", sess])
        await _send(event, "🔌 اتصال قطع شد و نشست از روی سرور پاک شد." if r.get("ok") else "قطع اتصال انجام نشد؛ «🆘 پشتیبانی» را بزن.", rows)
        return skip
    if text == B_SAVED or re.match(r"^⭐ #\d+", text or ""):
        if not connected:
            await _send(event, "برای دیدن پیام‌های ذخیره‌شده، اول اکانت تلگرامت را وصل کن.", [[B_LINK], [B_ACC_BACK]])
            return skip
        m = re.match(r"^⭐ #(\d+)", text)
        code, o = await _run([HPY, ACC_PY, sess, "saved-get", m.group(1)] if m else [HPY, ACC_PY, sess, "saved", "20"], 90)
        try:
            items = json.loads(o.splitlines()[-1])
        except Exception:
            logger.warning("admin-panel: saved messages read failed for %s", name)
            await _send(event, "خواندن پیام‌های ذخیره‌شده ممکن نشد. اگر تکرار شد «🆘 پشتیبانی و رفع مشکل» را بزن.", _acc_rows())
            return skip
        icon = {"Photo": "🖼", "Document": "📎", "WebPage": "🔗"}
        if m and items:
            it = items[0]
            L = [f"<b>⭐ پیام #{fa(it['id'])}</b> · <i>{fa(it['date'])}</i>" + (f" · از {esc(it['from'])}" if it.get("from") else ""), LINE,
                 esc(it.get("text") or "") or (f"{icon.get(it.get('media'), '📎')} {esc(it.get('file') or it.get('media') or '')}")]
            await _send(event, "\n".join(L), _acc_rows(), html_mode=True)
            return skip
        L = ["<b>⭐ پیام‌های ذخیره‌شده</b> — ۲۰ تای آخر", "(فقط خودت می‌بینی؛ چیزی ذخیره نمی‌شود)", LINE]
        for it in items:
            body = (it.get("text") or "")[:90] or (it.get("file") or "")
            L.append(f"#{fa(it['id'])} · <i>{fa(it['date'][5:])}</i> {icon.get(it.get('media'), '📎') if it.get('media') else ''} {esc(body)}")
        if not items:
            L.append("پیام ذخیره‌شده‌ای نیست.")
        L += [LINE, "برای جستجو از ایجنت بپرس، مثلاً «در پیام‌های ذخیره‌شده‌ام دنبال آدرس بگرد»."]
        btns = [f"⭐ #{it['id']}" for it in items[:12]]
        await _send(event, "\n".join(L), [btns[k:k + 4] for k in range(0, len(btns), 4)] + _acc_rows(), html_mode=True)
        return skip
    return None


B_TGSEARCH = "🌐 سرچ در تلگرام"


async def _tgsearch(event, key, sess, text, st, rows):
    """Global Telegram search (public channels / groups / bots) through the user's OWN session. key = await-dict key."""
    aw = (st.get("await") or {}).get(key) or {}
    if text == B_TGSEARCH:
        st.setdefault("await", {})[key] = {"kind": "tgsearch", "ts": time.time()}
        _save(st)
        await _send(event, "🌐 چه چیزی را در کل تلگرام بگردم؟ (اسم یا موضوع کانال/گروه/ربات؛ مثل «github» یا «برنامه نویسی پایتون»)", [[B_CANCEL]])
        return True
    if aw.get("kind") != "tgsearch" or not text or text in (B_CANCEL, B_MENU, B_ACC_BACK):
        return None
    st["await"].pop(key, None)
    _save(st)
    await _send(event, "⏳ در حال جستجو در تلگرام…")
    code, o = await _run([HPY, ACC_PY, sess, "tgsearch", text.strip(), "50"], 90)
    try:
        res = json.loads(o.splitlines()[-1])
    except Exception:
        logger.warning("admin-panel: tgsearch failed: %s", o[-200:])
        await _send(event, "جستجو انجام نشد؛ کمی بعد دوباره امتحان کن.", rows)
        return True
    res.sort(key=lambda x: -(x.get("members") or 0))
    icon = {"channel": "📢", "group": "👪", "bot": "🤖"}
    L = [f"<b>🌐 نتیجه‌ی «{esc(text.strip())}» در تلگرام</b> — {fa(len(res))} مورد", "روی هر اسم بزن تا در تلگرام باز شود 👇", LINE]
    for i, x in enumerate(res[:40], 1):
        mem = (" · 👥 " + fa(f"{x['members']:,}")) if x.get("members") else ""
        L.append(f"{fa(i)}. {icon.get(x['type'], '•')} <a href=\"{esc(x['link'])}\">{esc(x['title'] or x['username'])}</a>{mem}")
    if not res:
        L.append("چیزی پیدا نشد. کلمه‌ی دیگری امتحان کن (انگلیسی هم بنویس).")
    L += [LINE, "تلگرام برای هر جستجو حداکثر حدود ۲۰ کانال/گروه عمومی برمی‌گرداند؛ برای نتیجه‌ی بیشتر با کلمه‌های دیگر هم بگرد."]
    await _send(event, "\n".join(L), rows, html_mode=True)
    return True


def _biz_rows():
    return [[BZ_MSGMENU], [BZ_CHATS, BZ_UNREAD], [BZ_CONTACTS, BZ_SEARCH], [B_TGSEARCH], [B_MENU]]


def _biz_chat_rows(owner=True):
    return [[BZ_SUM, BZ_SUGG], [BZ_TR, BZ_SEND]] + ([[BZ_CHATS, B_BIZ], [B_MENU]] if owner else [[B_ACC, B_ACC_BACK]])


def _bz_ctx(uid, name=None):
    """Where Business tools act: the owner's own session, or a premium user's own userbot session."""
    if uid == OWNER:
        return {"owner": True, "sess": OWNER_SESS, "send": [HPY, OWNER_SEND], "home": _biz_rows()}
    sess = f"/root/.hermes/profiles/{name}/userbot/{name}"
    return {"owner": False, "sess": sess, "send": [HPY, "/root/.hermes/shared-tools/userbot/send_as_user.py", sess], "home": _acc_rows()}


async def _biz_read(*args, timeout=90, sess=None):
    code, o = await _run([HPY, ACC_PY, sess or OWNER_SESS, *args], timeout)
    try:
        return json.loads(o.splitlines()[-1])
    except Exception:
        logger.warning("admin-panel biz %s -> %s", args, o[-200:])
        return None


def _transcript(msgs, title, me="من"):
    lines = [f"گفتگو با «{title}» (قدیمی به جدید):"]
    for m in msgs:
        who = me if m.get("from_me") else (title or "طرف مقابل")
        lines.append(f"[{m.get('date','')}] {who}: {m.get('text') or '[' + str(m.get('media') or 'رسانه') + ']'}")
    return "\n".join(lines)


def _bz(st, uid):
    return st.setdefault("bz", {}).setdefault(uid, {})


async def _biz_open_chat(event, st, uid, ctx, cid, link, title):
    await _send(event, "⏳ چند لحظه…")
    msgs = await _biz_read("history", str(cid), "30", sess=ctx["sess"])
    if not isinstance(msgs, list):
        await _send(event, "خواندن این چت ممکن نشد.", ctx["home"])
        return True
    _bz(st, uid)["sel"] = {"id": cid, "link": link, "title": title, "transcript": _transcript(msgs, title)[-6000:]}
    _save(st)
    L = [f"<b>{esc(title or '—')}</b>" + (f" — <a href=\"{esc(link)}\">باز کردن در تلگرام</a>" if link else ""), LINE]
    for m in msgs[-15:]:
        who = "👤 من" if m.get("from_me") else "🗨"
        L.append(f"{who} <i>{fa(m.get('date', '')[5:])}</i>\n{esc(m.get('text') or '') or '[' + esc(m.get('media') or 'رسانه') + ']'}")
    if not msgs:
        L.append("پیامی نیست.")
    await _send(event, "\n".join(L), _biz_chat_rows(ctx["owner"]), html_mode=True)
    return True


async def _biz(event, text, st, uid=OWNER, name=None):
    """Hermes Business (Telepath-like) on the account owner's own Telegram account: the admin's, or a premium
    user's own userbot. Returns True (handled), {"rewrite": ...} (ask own agent), or None."""
    ctx = _bz_ctx(uid, name)
    if not ctx["owner"] and text in (BZ_UNREAD, BZ_SEARCH, BZ_DIGEST) and not os.path.exists(ctx["sess"] + ".session"):
        await _send(event, "📇 هنوز حساب تلگرامت به ایجنت وصل نیست. الان قدم‌به‌قدم وصلش می‌کنیم.")
        return {"rewrite": USER_BUTTONS[B_ACC]}
    b = _bz(st, uid)
    aw = (st.get("await") or {}).get(uid) or {}
    if aw.get("kind") == "biz_search" and text not in (B_CANCEL, B_MENU, B_ACC_BACK):
        st["await"].pop(uid, None)
        _save(st)
        await _send(event, "⏳ جستجو…")
        res = await _biz_read("search", text.strip(), "25", sess=ctx["sess"])
        L = [f"<b>🔎 نتیجه‌ی «{esc(text.strip())}»</b>", LINE] + ([
            f"• <b>{esc(r.get('chat') or '—')}</b> <i>{fa(r.get('date', '')[5:])}</i>{' (من)' if r.get('from_me') else ''}\n{esc(r.get('text') or '')}"
            for r in (res or [])] or ["چیزی پیدا نشد."])
        await _send(event, "\n".join(L), ctx["home"], html_mode=True)
        return True
    if aw.get("kind") == "biz_send" and text not in (B_CANCEL, B_MENU, B_ACC_BACK):
        st["await"].pop(uid, None)
        b["draft"] = text
        _save(st)
        return await _send(event, f"این پیام برای «{esc((b.get('sel') or {}).get('title', ''))}» از حساب خودت فرستاده شود؟\n\n«{esc(text)}»",
                           [[BZ_SEND_OK], [B_CANCEL]], html_mode=True)
    if text == B_CANCEL and aw.get("kind", "").startswith("biz_"):
        st["await"].pop(uid, None)
        b.pop("draft", None)
        _save(st)
        await _send(event, "لغو شد.", ctx["home"])
        return True
    if text == B_BIZ and ctx["owner"]:
        await _send(event, "<b>🤝 Hermes Business</b>\n" + LINE + "\nچت‌های حساب شخصی‌ات را از همین‌جا ببین، خلاصه کن، جواب پیشنهادی بگیر، ترجمه کن و پیام بفرست.\n"
                           "🔒 فقط خودت می‌بینی؛ پیام‌ها فقط با دستور خودت ارسال می‌شوند.", _biz_rows(), html_mode=True)
        return True
    if text in ((BZ_CHATS, BZ_UNREAD) if ctx["owner"] else (BZ_UNREAD,)):
        await _send(event, "⏳ چند لحظه…")
        data = await _biz_read("dialogs", "80", sess=ctx["sess"])
        if not isinstance(data, list):
            await _send(event, "خواندن حساب ممکن نشد.", ctx["home"])
            return True
        items = [d for d in data if d["type"] in ("private", "group")]
        if text == BZ_UNREAD:
            items = [d for d in items if d.get("unread")]
        items = items[:30]
        title = "📥 نخوانده‌ها" if text == BZ_UNREAD else "💼 چت‌های من"
        L = [f"<b>{title}</b>", "روی اسم بزن تا در تلگرام باز شود؛ با دکمه‌ها همین‌جا بازش کن و خلاصه/جواب بگیر 👇", LINE]
        for k, d in enumerate(items, 1):
            unread = f" · 🔴 {fa(d['unread'])}" if d.get("unread") else ""
            L.append(f"{fa(k)}. <a href=\"{esc(d['link'])}\">{esc(d['name'] or '—')}</a>{unread}")
        if not items:
            L.append("موردی نیست. 🎉")
        b["map"] = {BZ_PFX + (d["name"] or "")[:28]: [d["id"], d["link"], d["name"]] for d in items[:14]}
        _save(st)
        btns = list(b["map"])
        rows = ([[BZ_DIGEST]] if text == BZ_UNREAD and items else []) + [btns[k:k + 2] for k in range(0, len(btns), 2)] + ctx["home"]
        await _send(event, "\n".join(L), rows, html_mode=True)
        return True
    if text == BZ_CONTACTS and ctx["owner"]:
        await _send(event, "⏳ چند لحظه…")
        data = await _biz_read("contacts", sess=ctx["sess"])
        cs = (data or {}).get("contacts", [])
        L = [f"<b>📇 مخاطب‌های من</b> — {fa((data or {}).get('count', 0))} نفر", LINE] + \
            [f"{fa(k)}. <a href=\"{esc(c['link'])}\">{esc(c['name'] or '—')}</a>" + (f" (@{esc(c['username'])})" if c.get("username") else "")
             for k, c in enumerate(cs[:60], 1)]
        b["map"] = {BZ_PFX + (c["name"] or "")[:28]: [c["id"], c["link"], c["name"]] for c in cs[:14]}
        _save(st)
        btns = list(b["map"])
        await _send(event, "\n".join(L), [btns[k:k + 2] for k in range(0, len(btns), 2)] + ctx["home"], html_mode=True)
        return True
    if text == BZ_MSGMENU:
        await _send(event, "✉️ ارسال پیام از حساب خودت — به یک نفر یا به چند نفر؟",
                    [[BZ_NEWMSG, BZ_BULK], (ctx["home"][-1] if ctx["owner"] else [B_ACC, B_ACC_BACK])])
        return True
    if text == BZ_BULK:
        if not ctx["owner"] and not os.path.exists(ctx["sess"] + ".session"):
            await _send(event, "📇 هنوز حساب تلگرامت به ایجنت وصل نیست. الان قدم‌به‌قدم وصلش می‌کنیم.")
            return {"rewrite": USER_BUTTONS[B_ACC]}
        st.setdefault("await", {})[uid] = {"kind": "biz_bulk_who"}
        _save(st)
        await _send(event, "<b>👥 ارسال جمعی</b>\n" + LINE + "\nاسم مخاطب‌ها، @آیدی یا شماره‌ها را با «،» جدا بفرست (حداکثر ۱۰ نفر).\n"
                           "⚠️ برای محافظت از شماره‌ات: حداکثر ۲۰ پیام در روز، با فاصله‌ی ۲۰ تا ۴۵ ثانیه، و فقط برای آدم‌هایی که تو را می‌شناسند. "
                           "پیام به غریبه‌ها یا تبلیغ انبوه باعث بسته شدن شماره می‌شود.", [[B_CANCEL]], html_mode=True)
        return True
    if aw.get("kind") == "biz_bulk_who" and text not in (B_CANCEL, B_MENU, B_ACC_BACK):
        st["await"].pop(uid, None)
        names = [x.strip() for x in re.split(r"[،,\n]+", text) if x.strip()][:10]
        found, missing = [], []
        for q in names:
            if q.startswith("@") or re.fullmatch(r"\+?\d{7,15}", q):
                found.append([q, q])
                continue
            data = await _biz_read("contacts", q, sess=ctx["sess"])
            cs = (data or {}).get("contacts", [])
            if cs:
                found.append([cs[0]["id"], cs[0]["name"]])
            else:
                missing.append(q)
        b["bulk"] = {"recipients": found}
        if found:
            st.setdefault("await", {})[uid] = {"kind": "biz_bulk_text"}
        _save(st)
        L = [f"گیرنده‌ها ({fa(len(found))}): " + ("، ".join(esc(n) for _, n in found) or "—")]
        if missing:
            L.append("پیدا نشد: " + "، ".join(esc(m) for m in missing))
        L.append("حالا متن پیام را بفرست. «{نام}» در متن به اسم کوچک هر نفر تبدیل می‌شود (مثلاً: «سلام {نام} جان، …»)." if found else "کسی پیدا نشد.")
        await _send(event, "\n".join(L), [[B_CANCEL]] if found else [[BZ_MSGMENU], [B_CANCEL]], html_mode=True)
        return True
    if aw.get("kind") == "biz_bulk_text" and text not in (B_CANCEL, B_MENU, B_ACC_BACK):
        st["await"].pop(uid, None)
        b.setdefault("bulk", {})["text"] = text
        _save(st)
        rec = b["bulk"].get("recipients", [])
        sample = text.replace("{نام}", (rec[0][1] or "").split()[0] if rec else "").replace("{name}", "")
        await _send(event, f"این پیام برای {fa(len(rec))} نفر از حساب خودت فرستاده شود؟\n\nنمونه برای {esc(rec[0][1] if rec else '')}:\n«{esc(sample)}»\n\n"
                           f"⏱ حدود {fa(max(1, len(rec) * 32 // 60))} دقیقه طول می‌کشد؛ نتیجه را همین‌جا خبر می‌دهم.",
                    [[BZ_BULK_OK], [B_CANCEL]], html_mode=True)
        return True
    if text == BZ_BULK_OK and (b.get("bulk") or {}).get("text"):
        job = {"session": ctx["sess"], "chat_id": str(event.source.chat_id), "text": b["bulk"]["text"],
               "recipients": b["bulk"]["recipients"]}
        b.pop("bulk", None)
        _save(st)
        os.makedirs("/root/.hermes/shared-tools/admin/bulk_jobs", exist_ok=True)
        jp = f"/root/.hermes/shared-tools/admin/bulk_jobs/{int(time.time())}-{uid}.json"
        json.dump(job, open(jp, "w"), ensure_ascii=False)
        subprocess.Popen([HPY, BULK_PY, jp], start_new_session=True, stdout=subprocess.DEVNULL,
                         stderr=open(jp + ".log", "w"))
        await _send(event, "🚀 ارسال شروع شد. با فاصله فرستاده می‌شود و نتیجه را همین‌جا خبر می‌دهم.", ctx["home"])
        return True
    if text == BZ_NEWMSG:
        if not ctx["owner"] and not os.path.exists(ctx["sess"] + ".session"):
            await _send(event, "📇 هنوز حساب تلگرامت به ایجنت وصل نیست. الان قدم‌به‌قدم وصلش می‌کنیم.")
            return {"rewrite": USER_BUTTONS[B_ACC]}
        st.setdefault("await", {})[uid] = {"kind": "biz_who"}
        _save(st)
        await _send(event, "✉️ پیام برای چه کسی؟ اسم مخاطب، @آیدی یا شماره (با کد کشور) را بفرست:", [[B_CANCEL]])
        return True
    if aw.get("kind") == "biz_who" and text not in (B_CANCEL, B_MENU, B_ACC_BACK):
        q = text.strip()
        st["await"].pop(uid, None)
        if q.startswith("@") or re.fullmatch(r"\+?\d{7,15}", q):
            b["map"] = {BZ_PFX + q[:28]: [q, None, q]}
        else:
            data = await _biz_read("contacts", q, sess=ctx["sess"])
            cs = (data or {}).get("contacts", [])[:10]
            if not cs:
                _save(st)
                await _send(event, f"مخاطبی با «{esc(q)}» پیدا نشد. اسم دیگری، @آیدی یا شماره بفرست.", [[BZ_NEWMSG], [B_CANCEL]], html_mode=True)
                return True
            b["map"] = {BZ_PFX + (c["name"] or "")[:28]: [c["id"], c["link"], c["name"]] for c in cs}
        b["pick_send"] = True
        _save(st)
        btns = list(b["map"])
        await _send(event, "کدام؟ 👇", [btns[k:k + 2] for k in range(0, len(btns), 2)] + [[B_CANCEL]])
        return True
    if b.get("pick_send") and text in (b.get("map") or {}):
        cid, link, title = b["map"][text]
        b.pop("pick_send", None)
        b["sel"] = {"id": cid, "link": link, "title": title, "transcript": ""}
        st.setdefault("await", {})[uid] = {"kind": "biz_send"}
        _save(st)
        await _send(event, f"✉️ متن پیام برای «{esc(title)}» را بفرست (از حساب خودت ارسال می‌شود):", [[B_CANCEL]], html_mode=True)
        return True
    if text == BZ_SEARCH:
        st.setdefault("await", {})[uid] = {"kind": "biz_search"}
        _save(st)
        await _send(event, "🔎 چه چیزی را در پیام‌هایت جستجو کنم؟ (یک کلمه یا عبارت بفرست)", [[B_CANCEL]])
        return True
    if text in (b.get("map") or {}):
        return await _biz_open_chat(event, st, uid, ctx, *b["map"][text])
    sel = b.get("sel") or {}
    if text in (BZ_SUM, BZ_SUGG, BZ_TR) and sel:
        task = {BZ_SUM: "این گفتگو را به فارسی در چند خط خلاصه کن: موضوع اصلی، درخواست‌ها/قول‌ها، و کاری که من باید انجام بدهم.",
                BZ_SUGG: "سه پیشنهاد جواب کوتاه و مؤدبانه به آخرین پیام طرف مقابل بنویس، با لحن خود من، هر کدام در یک خط شماره‌دار. چیزی ارسال نکن؛ فقط پیشنهاد بده.",
                BZ_TR: "هر پیامی از این گفتگو را که فارسی نیست به فارسی ترجمه کن و فقط ترجمه‌ها را بده."}[text]
        return {"rewrite": f"[Hermes Business] {task}\nهیچ پیامی برای کسی نفرست و ابزار ارسال را اجرا نکن.\n\n{sel['transcript']}"}
    if text == BZ_SEND and sel:
        st.setdefault("await", {})[uid] = {"kind": "biz_send"}
        _save(st)
        await _send(event, f"✉️ متن پیام برای «{esc(sel['title'])}» را بفرست (از حساب خودت ارسال می‌شود):", [[B_CANCEL]], html_mode=True)
        return True
    if text == BZ_SEND_OK and sel and b.get("draft"):
        draft = b.pop("draft")
        _save(st)
        code, o = await _run(ctx["send"] + [str(sel["id"]), draft], 60)
        await _send(event, "✅ ارسال شد." if "SENT" in o else f"❌ ارسال نشد: {esc(o[-150:])}", _biz_chat_rows(ctx["owner"]), html_mode=True)
        return True
    if text == BZ_DIGEST:
        data = await _biz_read("dialogs", "60", sess=ctx["sess"])
        items = [d for d in (data or []) if d.get("unread") and d["type"] in ("private", "group")][:8]
        parts = []
        for d in items:
            msgs = await _biz_read("history", str(d["id"]), str(min(d["unread"], 10)), sess=ctx["sess"])
            if isinstance(msgs, list):
                parts.append(_transcript(msgs, d["name"])[-1500:])
        if not parts:
            await _send(event, "پیام نخوانده‌ای نیست. 🎉", ctx["home"])
            return True
        return {"rewrite": "[Hermes Business] از این پیام‌های نخوانده یک گزارش کوتاه فارسی بساز: برای هر چت در یک یا دو خط بگو چه خواسته‌اند "
                           "و کدام فوری‌اند. هیچ پیامی برای کسی نفرست.\n\n" + "\n\n".join(parts)}
    return None


def _tools_rows():
    return [["⚖️ مشاور حقوقی", "📁 فایل‌های من"], ["🔎 جستجو در اینترنت", B_NEWCHAT], [B_MENU]]


def _cfg():
    try:
        return json.load(open(TIERS_CFG))
    except Exception:
        logger.warning("admin-panel: no tiers config", exc_info=True)
        return {"tiers": {}, "period_days": 30}


def _roster():
    try:
        return {k: str(v) for k, v in json.load(open("/root/.hermes/shared-tools/admin/roster.json")).items() if v}
    except Exception:
        logger.warning("admin-panel: cannot read roster", exc_info=True)
        return {}


def _tier_of(name):
    try:
        t = json.load(open(TIERS)).get(name) or {}
    except FileNotFoundError:
        t = {}
    except Exception:
        logger.warning("admin-panel: bad tiers file", exc_info=True)
        t = {}
    tier, until = t.get("tier", "basic"), t.get("until")
    return tier, until, (until is None or until > time.time()) and not t.get("paused")


def _tier_label(tier, until, active):
    title = _cfg().get("tiers", {}).get(tier, {}).get("title", tier)
    icon = "⭐" if tier == "premium" else "🔹"
    if not active:
        return f"{icon} {title} · ⛔ منقضی"
    if until is None:
        return f"{icon} {title} · دائمی"
    return f"{icon} {title} · تا {fa(time.strftime('%Y-%m-%d', time.gmtime(until + 12600)))} ({fa(max(0, -int(-(until - time.time()) // 86400)))} روز مانده)"


# ---------------- state ----------------
def _load():
    try:
        with open(STATE) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception:
        logger.warning("admin-panel: bad state file, starting fresh", exc_info=True)
        return {}


def _save(st):
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f, ensure_ascii=False)
    os.replace(tmp, STATE)


_env_cache = {"mtime": 0, "ids": set()}


def _allowed():
    try:
        mt = os.path.getmtime(ENV)
        if mt != _env_cache["mtime"]:
            m = re.search(r"^TELEGRAM_ALLOWED_USERS=(.*)$", open(ENV).read(), re.M)
            _env_cache.update(mtime=mt, ids={i.strip() for i in (m.group(1).split(",") if m else []) if i.strip()})
    except Exception:
        logger.warning("admin-panel: cannot read allowed users", exc_info=True)
    return _env_cache["ids"]


def _roster_ids():
    try:
        return {str(v) for v in json.load(open("/root/.hermes/shared-tools/admin/roster.json")).values() if v}
    except Exception:
        logger.warning("admin-panel: cannot read roster", exc_info=True)
        return set()


# ---------------- telegram helpers ----------------
RLM = "\u200f"
LINE = "━━━━━━━━━━━━━━━"
_FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa(x):
    """Persian digits (and thousands separator) for numbers shown to people."""
    if isinstance(x, int):
        x = f"{x:,}".replace(",", "٬")
    return str(x).translate(_FA)


def esc(x):
    return html.escape(str(x or ""))


def rtl(text):
    """Every line starts with a right-to-left mark so lines that begin with a Latin name don't flip."""
    return "\n".join(RLM + ln if ln and not ln.startswith(RLM) else ln for ln in text.split("\n"))


async def _send(event, text, rows=None, remove=False, html_mode=False):
    from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove
    src = event.source
    kw = {"parse_mode": "HTML"} if html_mode else {}
    text = rtl(text)
    if rows:
        _kbt_set(str(src.chat_id))
        kw["reply_markup"] = ReplyKeyboardMarkup(rows, resize_keyboard=True, is_persistent=False,
                                                 input_field_placeholder="پیام یا یکی از دکمه‌ها")
    elif remove:
        kw["reply_markup"] = ReplyKeyboardRemove()
    tid = getattr(src, "thread_id", None)
    if tid and str(tid).isdigit():
        kw["message_thread_id"] = int(tid)
    bot = event.raw_message.get_bot()
    parts, cur = [], ""
    for line in text.split("\n"):                 # split on line boundaries so no HTML tag is cut in half
        if cur and len(cur) + len(line) + 1 > 3800:
            parts.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    parts.append(cur or " ")
    for n, part in enumerate(parts):
        last = n == len(parts) - 1
        await bot.send_message(chat_id=int(src.chat_id), text=part, disable_web_page_preview=True, **(kw if last else
                               {k: v for k, v in kw.items() if k in ("message_thread_id", "parse_mode")}))
    return True


async def _run(args, timeout=180):
    p = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        outb, _ = await asyncio.wait_for(p.communicate(), timeout)
    except asyncio.TimeoutError:
        p.kill()
        return 124, "⏱ زمان اجرا تمام شد."
    return p.returncode, outb.decode("utf-8", "replace").strip()


async def _admin_json(*args):
    code, out = await _run([SYS_PY, ADMIN_PY, *args], timeout=300)
    try:
        return json.loads(out.splitlines()[-1])
    except Exception:
        logger.warning("admin-panel: users_admin %s -> %s", args, out[-300:])
        return {"ok": False, "error": out[-200:] or f"exit {code}"}


def _ago(ts):
    if not ts:
        return "هرگز"
    sec = int(time.time() - ts)
    if sec < 120:
        return "همین الان"
    if sec < 3600:
        return f"{fa(sec // 60)} دقیقه پیش"
    if sec < 86400:
        return f"{fa(sec // 3600)} ساعت پیش"
    return f"{fa(sec // 86400)} روز پیش"


ONLINE_SEC = 180      # Telegram never tells a bot whether a chat is open: "online" = wrote in the last 3 min or a reply is running


def _busy(profile):
    """True while the agent is still answering this profile (last incoming batch newer than the last finished reply)."""
    try:
        lg = f"/root/.hermes/profiles/{profile}/logs/gateway.log"
        tail = subprocess.run(["tail", "-c", "20000", lg], capture_output=True, text=True, timeout=5).stdout.splitlines()
        last_in = max((l[:19] for l in tail if "Flushing text batch" in l), default="")
        last_out = max((l[:19] for l in tail if "response ready" in l), default="")
        if not last_in or last_in <= last_out:
            return False
        t_in = time.mktime(time.strptime(last_in, "%Y-%m-%d %H:%M:%S")) - time.timezone
        return time.time() - t_in < 1800
    except Exception:
        return False


def _is_online(last_activity, profile=None):
    return bool((last_activity and time.time() - last_activity < ONLINE_SEC) or (profile and _busy(profile)))


def _online_lamp(last_activity, profile=None, long=False):
    """Owner 2026-11-16: blue = online right now, red = offline (with when it last wrote)."""
    if _is_online(last_activity, profile):
        return "🔵 آنلاین — همین الان دارد با ربات کار می‌کند" if long else "🔵 آنلاین"
    return f"🔴 آفلاین · آخرین پیام {_ago(last_activity)}" if long else "🔴 آفلاین"


def _build_lamp(name):
    """Blue = building/coding allowed by the owner, red = not allowed (only for sealed user profiles)."""
    if not name or not _sealed(name):
        return ""
    return "🔵 اجازه‌ی ساخت: روشن" if _build_allowed(name) else "🔴 اجازه‌ی ساخت: خاموش"


def _status_icon(u):
    if u["status"] == "unpaired":
        return "⚪ وصل‌نشده"
    if u["status"] == "off":
        return "⛔ قطع"
    return _online_lamp(u.get("last_activity"), u.get("name"))


# ---------------- admin screens ----------------
async def _users(event):
    users = await _admin_json("list")
    if not isinstance(users, list):
        return await _send(event, f"خطا: {users.get('error')}", _admin_rows())
    paired = [u for u in users if u["status"] != "unpaired"]
    free = [u for u in users if u["status"] == "unpaired"]
    prem = sum(1 for u in paired if _tier_of(u["name"])[0] == "premium")
    online = sum(1 for u in paired if u["status"] == "on" and _is_online(u.get("last_activity"), u["name"]))
    L = [f"<b>👥 کاربران ایجنت هرمس</b>", LINE,
         f"وصل: <b>{fa(len(paired))}</b>  ·  🔵 آنلاین: <b>{fa(online)}</b>  ·  ⭐ پرمیوم: <b>{fa(prem)}</b>  ·  🔹 معمولی: <b>{fa(len(paired) - prem)}</b>",
         f"پروفایل آماده‌ی خالی: <b>{fa(len(free))}</b>", ""]
    paired.sort(key=lambda u: -(u.get("last_activity") or 0))
    for u in paired:
        title = u.get("label") or u.get("tg_name") or u["name"]
        L += [f"{_status_icon(u)}  <b>{esc(title)}</b>",
              f"     🆔 پروفایل: <code>{esc(u['name'])}</code>",
              f"     💎 اشتراک: {_tier_label(*_tier_of(u['name']))}",
              *([] if _is_online(u.get("last_activity"), u["name"]) else [f"     🕐 آخرین پیام: {_ago(u.get('last_activity'))}"]),
              *([f"     🛠 {_build_lamp(u['name'])}"] if _build_lamp(u['name']) else []),
              f"     💬 پیام‌ها: امروز {fa(u['msgs_24h'])} · هفته {fa(u['msgs_7d'])} · کل {fa(u['msgs_total'])}", ""]
    if free:
        L += ["⚪ <b>پروفایل‌های خالی</b> (هنوز کسی وصل نشده):", "     " + "، ".join(f"<code>{esc(u['name'])}</code>" for u in free), ""]
    L += [LINE, "برای جزئیات و کنترل هر کاربر، دکمه‌ی اسمش را بزن.", "🔒 محتوای گفتگوها نمایش داده نمی‌شود."]
    names = [f"{'⛔' if u['status'] == 'off' else '🔵' if _is_online(u.get('last_activity'), u['name']) else '🔴'} 👤 {u['name']}" for u in paired]
    rows = [names[i:i + 2] for i in range(0, len(names), 2)] + [[B_REQ, B_NEW], [B_MENU]]
    await _send(event, "\n".join(L), rows, html_mode=True)
    return True


async def _detail(event, name):
    u = await _admin_json("detail", name)
    if u.get("error"):
        return await _send(event, f"کاربر «{name}» پیدا نشد.", [[B_USERS, B_MENU]])
    st = _load()
    st["sel"] = name
    _save(st)
    fmt = lambda ts: fa(time.strftime("%Y-%m-%d  %H:%M", time.gmtime(ts + 12600))) if ts else "—"
    title = u.get("label") or u.get("tg_name") or name
    L = [f"<b>👤 {esc(title)}</b>", LINE,
         "<b>📇 مشخصات</b>",
         f"     وضعیت: {_status_icon(u)}",
         f"     پروفایل: <code>{esc(name)}</code>",
         f"     اسم تلگرام: {esc(u.get('tg_name') or '—')}",
         f"     شناسه‌ی تلگرام: <code>{esc(u.get('tg_id') or '—')}</code>",
         f"     ساخت پروفایل: {fmt(u.get('created_at'))}",
         f"     تأیید اتصال: {fmt(u.get('approved_at'))}", "",
         "<b>💎 اشتراک</b>",
         f"     {_tier_label(*_tier_of(name))}",
         f"     یوزربات شخصی: {'✅ وصل' if u.get('userbot') else '— ندارد'}", "",
         "<b>📊 فعالیت</b>",
         f"     {_online_lamp(u.get('last_activity'), name, long=True)}",
         f"     پیام‌ها: ۲۴ ساعت {fa(u['msgs_24h'])} · ۷ روز {fa(u['msgs_7d'])} · کل {fa(u['msgs_total'])}",
         f"     گفتگوها: {fa(u['sessions'])} · کارهای ابزاری ۷ روز: {fa(u['tool_calls_7d'])}", LINE]
    rows = []
    if u["status"] != "unpaired":
        L.append("دکمه‌های پایین روی همین کاربر اثر دارند.")
        rows += [[S_ACCOUNT], [S_FIXUSER], [S_PREM, S_BASIC], [S_FOREVER], [_build_btn(name)]]
        if _build_lamp(name):
            L.insert(-1, f"🛠 {_build_lamp(name)}")
        rows.append([S_OFF] if u["status"] == "on" else [S_ON])
    else:
        L.append("هنوز کسی به این پروفایل وصل نشده. «🔗 لینک اتصال این پروفایل» را بزن و لینک را برایش بفرست.")
        # owner 2026-11-18: one tap on this page binds whoever just pressed Start — no second step, no name guessing
        pend = await _admin_json("pending")
        pend = [p for p in pend if str(p.get("user_id")) != str(OWNER)] if isinstance(pend, list) else []
        if pend:
            L += ["", "<b>📥 درخواست‌های تازه — دکمه‌ی همان شخص را بزن تا به همین حساب وصل شود:</b>"]
            for p in pend[:5]:
                L.append(f"     • {esc(p.get('user_name') or 'بی‌نام')} — شناسه <code>{esc(p['user_id'])}</code> — {fa(p['age_min'])} دقیقه پیش")
                rows.append([f"🔗 {p['user_id']} ← {name}"])
        else:
            L += ["", "📥 هنوز درخواستی نیامده. بعد از اینکه طرف استارت زد، «👤 " + esc(name) + "» را دوباره بزن تا دکمه‌ی اتصال بیاید."]
        rows.append([S_INVITE])
    rows += [[S_BACKU, B_MENU]]
    await _send(event, "\n".join(L), rows, html_mode=True)
    return True


async def _set(event, name, action):
    r = await _admin_json("set", name, action)
    if not r.get("ok"):
        return await _send(event, f"انجام نشد: {r.get('error')}", [[B_USERS, B_MENU]])
    await _admin_json("restart")
    await _send(event, (f"⛔ دسترسی {name} قطع شد." if action == "off" else f"✅ دسترسی {name} وصل شد.")
                + "\nایجنت چند ثانیه ری‌استارت می‌شود.", [[f"👤 {name}", B_USERS], [B_MENU]])
    return True


async def _requests(event, st):
    pend = await _admin_json("pending")
    if not isinstance(pend, list) or not pend:
        return await _send(event, "📥 درخواست اتصالی در انتظار نیست.\nکسی که می‌خواهی وصل شود باید اول به ربات پیام بدهد.",
                           _admin_rows())
    lines, rows = ["📥 درخواست‌های اتصال:", ""], []
    for p in pend:
        lines.append(f"• {p['user_name'] or 'بی‌نام'} — شناسه {p['user_id']} — {p['age_min']} دقیقه پیش")
        rows.append([f"✅ تأیید {p['user_id']}"])
    lines.append("\nروی «تأیید» بزن، بعد پروفایلش را انتخاب کن.")
    await _send(event, "\n".join(lines), rows + [[B_MENU]])
    return True


async def _approve_pick(event, uid):
    users = await _admin_json("list")
    free = [u["name"] for u in users if u["status"] == "unpaired"] if isinstance(users, list) else []
    rows = [[f"🔗 {uid} ← {n}"] for n in free] + [[f"➕ پروفایل تازه برای {uid}"], [B_REQ, B_MENU]]
    await _send(event, f"شناسه {uid} به کدام پروفایل وصل شود؟\n(هر پروفایل فقط مال یک نفر است و داده‌اش جداست.)", rows)
    return True


async def _activate(event, uid, name):
    pend = await _admin_json("pending")
    req = next((p for p in pend if p["user_id"] == uid), None) if isinstance(pend, list) else None
    if not req:
        return await _send(event, "این درخواست دیگر در انتظار نیست (شاید منقضی شده). از کاربر بخواه دوباره به ربات پیام بدهد.",
                           [[B_REQ, B_MENU]])
    r = await _admin_json("activate", req["request_id"], name)
    if not r.get("ok"):
        return await _send(event, f"فعال‌سازی انجام نشد: {r.get('error')}", [[B_REQ, B_MENU]])
    st = _load()
    st.setdefault("welcome", {})[uid] = name           # keyboard + welcome sent on the user's next message
    _save(st)
    await _admin_json("restart")
    await _send(event, f"✅ {r.get('user_name') or uid} فعال شد و به پروفایل «{name}» وصل شد.\n"
                       "ایجنت چند ثانیه ری‌استارت می‌شود؛ دکمه‌های میانبر با اولین پیامش برایش فعال می‌شود.",
                [[f"👤 {name}", B_USERS], [B_MENU]])
    return True


async def _set_tier(event, name, tier, days):
    r = await _admin_json("set-tier", name, tier, str(days))
    if not r.get("ok"):
        await _send(event, f"انجام نشد: {r.get('error')}", [[f"👤 {name}", B_MENU]])
        return True
    await _send(event, f"✅ اشتراک {name}: {_tier_label(r['tier'], r['until'], r['active'])}", [[f"👤 {name}", B_USERS], [B_MENU]])
    await _push_user_kb(event, name, f"🎛 اشتراکت به‌روز شد: {_tier_label(r['tier'], r['until'], r['active'])}")
    return True


async def _push_user_kb(event, name, text):
    """Send the user his keyboard for his (new) tier right away."""
    from telegram import ReplyKeyboardMarkup
    uid = _roster().get(name)
    if not uid:
        return
    tier, until, active = _tier_of(name)
    try:
        await event.raw_message.get_bot().send_message(
            chat_id=int(uid), text=text,
            reply_markup=ReplyKeyboardMarkup(_user_rows(tier, active, name), resize_keyboard=True, is_persistent=False))
        st = _load()
        st.setdefault("kb", {})[uid] = f"{KB_VERSION}:{tier}:{active}"
        _save(st)
    except Exception:
        logger.warning("admin-panel: could not push keyboard to %s", name, exc_info=True)


async def _payments(event):
    o = await _admin_json("orders")
    orders = (o or {}).get("orders", {}) if isinstance(o, dict) else {}
    open_ = [(k, v) for k, v in orders.items() if v["status"] in ("awaiting_receipt", "receipt_sent")]
    done = sorted([(k, v) for k, v in orders.items() if v["status"] in ("approved", "rejected")],
                  key=lambda kv: -kv[1].get("decided", 0))[:10]
    cfg = _cfg().get("tiers", {})
    lines, rows = ["💳 پرداخت‌ها", ""], []
    if open_:
        lines.append("در انتظار:")
        for k, v in open_:
            st = "رسید آمده ✅" if v["status"] == "receipt_sent" else "منتظر رسید"
            lines.append(f"#{k} — {v['name']} — {_buy_label(v) if 'kind' in v else v['tier']} — {st}")
            if v["status"] == "receipt_sent":
                rows.append([f"✔️ تأیید پرداخت #{k}", f"✖️ رد پرداخت #{k}"])
    else:
        lines.append("پرداختی در انتظار نیست.")
    if done:
        lines += ["", "آخرین‌ها:"]
        for k, v in done:
            lines.append(f"#{k} — {v['name']} — {cfg.get(v['tier'], {}).get('title', v['tier'])} — {v['price']:,} — "
                         + ("✅ تأیید" if v["status"] == "approved" else "✖️ رد"))
    total = sum(v["price"] for v in orders.values() if v["status"] == "approved")
    lines += ["", f"جمع دریافتی تأییدشده: {total:,} تومان"]
    await _send(event, "\n".join(lines), rows + [[B_MENU]])
    return True


async def _decide(event, oid, approve):
    r = await _admin_json("order-approve" if approve else "order-reject", oid)
    if not r.get("ok"):
        await _send(event, f"انجام نشد: {r.get('error')}", [[B_PAY, B_MENU]])
        return True
    title = _cfg().get("tiers", {}).get(r["tier"], {}).get("title", r["tier"])
    if approve:
        ti = r["tier_info"]
        await _send(event, f"✅ پرداخت #{oid} تأیید شد — {r['name']}: {_tier_label(ti['tier'], ti['until'], ti['active'])}", [[B_PAY, B_MENU]])
        await _push_user_kb(event, r["name"], f"✅ پرداختت تأیید شد و نسخه‌ی {title} فعال شد.\n{_tier_label(ti['tier'], ti['until'], ti['active'])}")
    else:
        await _send(event, f"✖️ پرداخت #{oid} رد شد.", [[B_PAY, B_MENU]])
        if r.get("tg_id"):
            await event.raw_message.get_bot().send_message(
                chat_id=int(r["tg_id"]), text=f"✖️ رسید سفارش #{oid} تأیید نشد. اگر فکر می‌کنی اشتباه شده، دوباره از «⭐ اشتراک من» اقدام کن یا به ادمین پیام بده.")
    return True


T_ICON = {"waiting": "⏳ منتظر ورود", "active": "🟢 فعال", "paused": "⏸ متوقف", "expired": "⌛ تمام شده", "closed": "🔒 بسته"}


def _left(until):
    """Time left until `until`, in Persian (hours + minutes)."""
    sec = int((until or 0) - time.time())
    if sec <= 0:
        return "تمام شده"
    h, m = sec // 3600, (sec % 3600) // 60
    return (f"{fa(h)} ساعت و {fa(m)} دقیقه" if h else f"{fa(m)} دقیقه") + " مانده"


async def _trial_rows():
    r = await _admin_json("trial-accounts")
    return [x for x in (r if isinstance(r, list) else []) if x.get("status") != "deleted"]


TRIAL_TOKENS_DEFAULT = 300_000


def _trial_quota(name):
    """(code, used, quota) for a test profile — same rule as users_admin.trial_usage, read directly (no subprocess)."""
    try:
        t = json.load(open("/root/.hermes/shared-tools/admin/trials.json"))
    except Exception:
        return None
    for code, v in t.items():
        if v.get("used") and v["used"][0].get("name") == name and not v.get("profile"):
            quota = int(v.get("quota") or TRIAL_TOKENS_DEFAULT) + int(v.get("bonus_tokens") or 0)
            try:
                import sqlite3
                c = sqlite3.connect(f"file:/root/.hermes/profiles/{name}/state.db?mode=ro", uri=True)
                used = c.execute("SELECT COALESCE(SUM(input_tokens),0)+COALESCE(SUM(output_tokens),0) FROM session_model_usage WHERE last_seen >= ?",
                                 (v["used"][0].get("at") or 0,)).fetchone()[0] or 0
            except Exception:
                used = 0
            return code, int(used), quota
    return None


def _bar(pct, n=10):
    k = max(0, min(n, round(pct / 100 * n)))
    return "▰" * k + "▱" * (n - k)


def _tok(n):
    return (fa(f"{n / 1e6:.2f}".rstrip("0").rstrip(".")) + " میلیون") if n >= 1e6 else (fa(f"{n / 1e3:.0f}") + " هزار") if n >= 1e3 else fa(n)


T_FILTERS = {"online": "🔵 آنلاین", "active": "🟢 فعال", "paused": "⏸ متوقف", "waiting": "⏳ منتظر", "expired": "⌛ تمام‌شده"}
T_ALL, T_NEXT, T_PREV = "📋 همه", "▶️ بعدی", "◀️ قبلی"
T_PAUSE_ALL, T_PAUSE_ALL_OK = "⏸ توقف همه‌ی تست‌های فعال", "✔️ بله، همه‌ی تست‌های فعال را متوقف کن"
T_PAGE = 10


def _t_online(x):
    return bool(x.get("profile")) and x["status"] in ("active", "paused") and _is_online(x.get("last_activity"), x.get("profile"))


async def _trials(event, flt=None, page=None):
    """Owner: every tester at a glance — counts, filters, pages; tap a name for that tester's page."""
    st = _load()
    view = st.setdefault("tview", {"flt": "all", "page": 0})
    if flt is not None:
        view.update(flt=flt, page=0)
    if page is not None:
        view["page"] = max(0, page)
    _save(st)
    allr = await _trial_rows()
    order = {"active": 1, "paused": 2, "waiting": 3, "expired": 4, "closed": 5}
    allr.sort(key=lambda x: (0 if _t_online(x) else order.get(x["status"], 9), -(x.get("created") or 0)))
    counts = {"online": sum(1 for x in allr if _t_online(x)),
              **{k: sum(1 for x in allr if x["status"] == k) for k in ("active", "paused", "waiting", "expired")}}
    f = view["flt"]
    if f == "online":
        rows_ = [x for x in allr if _t_online(x)]
    elif f in ("active", "paused", "waiting", "expired"):
        rows_ = [x for x in allr if x["status"] == f]
    else:
        rows_ = [x for x in allr if x["status"] in ("active", "paused", "waiting")] + \
                [x for x in allr if x["status"] not in ("active", "paused", "waiting")][:10]
    pages = max(1, -(-len(rows_) // T_PAGE))
    view["page"] = min(view["page"], pages - 1)
    _save(st)
    shown = rows_[view["page"] * T_PAGE:(view["page"] + 1) * T_PAGE]
    title = "همه" if f == "all" else T_FILTERS[f]
    L = ["<b>🎁 لینک‌های تست</b>", LINE,
         "  ·  ".join(f"{T_FILTERS[k]} {fa(counts[k])}" for k in T_FILTERS), "",
         f"<b>{esc(title)}</b>" + (f" — صفحه‌ی {fa(view['page'] + 1)} از {fa(pages)}" if pages > 1 else ""),
         "روی اسم هر نفر بزن تا صفحه‌اش باز شود (وضعیت زنده، پیام، توقف، حذف)."]
    btns = []
    for x in shown:
        who = x.get("label") or "بی‌نام"
        extra = f" · {_left(x['until'])}" if x["status"] in ("active", "paused") and x.get("until") else ""
        if x.get("profile") and x["status"] in ("active", "paused", "expired"):
            extra += f" · {_online_lamp(x.get('last_activity'), x.get('profile'))}"
        L.append(f"{T_ICON.get(x['status'], x['status'])} — <b>{esc(who)}</b>{extra}")
        lamp = ("🔵" if _t_online(x) else "🔴") if x.get("profile") else "⏳" if x["status"] == "waiting" else "⚪"
        tail = (f" · {_left(x['until']).replace(' مانده', '')} مانده" if x["status"] in ("active", "paused") and x.get("until") else
                {"paused": " · متوقف", "waiting": " · منتظر ورود", "expired": " · تمام شده", "closed": " · بسته"}.get(x["status"], ""))
        if x["status"] == "paused":
            tail = " · ⏸ متوقف" + tail.replace(" · متوقف", "")
        if x.get("quota") and x["status"] in ("active", "paused"):
            tail += f" · 🎟 {fa(f'{(x.get('pct') or 0):.0f}')}٪"
        btns.append(f"{lamp} 👤 {who}{tail} #{x['code']}")
    if not shown:
        L.append("\nدر این گروه کسی نیست.")
    # owner 2026-11-16: testers first, ONE per row, in order; every control button below them
    kb = [[b] for b in btns]
    nav = ([T_PREV] if view["page"] > 0 else []) + ([T_NEXT] if view["page"] < pages - 1 else [])
    if nav:
        kb.append(nav)
    fb = [f"{T_FILTERS[k]} {fa(counts[k])}" for k in T_FILTERS] + [T_ALL]
    kb += [fb[0:3], fb[3:6]]
    kb.append([B_TRIAL_NEW["premium"], B_TRIAL_NEW["basic"]])
    if counts["active"]:
        kb.append([T_PAUSE_ALL])
    kb.append([B_MENU])
    await _send(event, "\n".join(L), kb, html_mode=True)
    return True


async def _trials_nav(event, text):
    """Filter / page / pause-all buttons of the tester list."""
    for k, lab in T_FILTERS.items():
        if text and text.startswith(lab + " ") and re.fullmatch(r"[\d۰-۹]+", text[len(lab) + 1:]):
            return await _trials(event, flt=k)
    if text == T_ALL:
        return await _trials(event, flt="all")
    if text in (T_NEXT, T_PREV):
        p = (_load().get("tview") or {}).get("page", 0)
        return await _trials(event, page=p + (1 if text == T_NEXT else -1))
    if text == T_PAUSE_ALL:
        n = sum(1 for x in await _trial_rows() if x["status"] == "active")
        await _send(event, f"⏸ همه‌ی {fa(n)} تست فعال همین الان متوقف شوند؟ (هر کدام را بعداً از صفحه‌اش با «▶️ ادامه» دوباره فعال می‌کنی.)",
                    [[T_PAUSE_ALL_OK], [B_TRIAL, B_MENU]])
        return True
    if text == T_PAUSE_ALL_OK:
        act = [x for x in await _trial_rows() if x["status"] == "active"]
        for x in act:
            await _admin_json("trial-pause", x["code"])
        await _send(event, f"⏸ {fa(len(act))} تست متوقف شد؛ از پیام بعدی‌شان هیچ جوابی از هوش مصنوعی نمی‌گیرند.")
        return await _trials(event, flt="paused")
    return None


async def _trial_page(event, code):
    x = next((r for r in await _trial_rows() if r["code"] == code), None)
    if not x:
        await _send(event, "این تست پیدا نشد (شاید پاک شده).", [[B_TRIAL, B_MENU]])
        return True
    who = x.get("label") or "بی‌نام"
    tt = "⭐ پرمیوم" if x.get("tier", "premium") == "premium" else "🔹 معمولی"
    L = [f"<b>👤 {esc(who)}</b> — تست {tt} ۲۴ ساعته", LINE, f"وضعیت: <b>{T_ICON.get(x['status'], x['status'])}</b>"]
    d = {}
    if x.get("profile"):
        d = await _admin_json("detail", x["profile"])
        d = d if isinstance(d, dict) and not d.get("error") else {}
        tg = x.get("uid") or d.get("tg_id")
        L += [f"ورود: {_jdt(x['at']) if x.get('at') else '—'}",
              f"پایان: {_jdt(x['until']) if x.get('until') else '—'}" + (f" · <b>{_left(x['until'])}</b>" if x["status"] in ("active", "paused") and x.get("until") else ""),
              "", "<b>📇 مشخصات</b>",
              f"     اسم تلگرام: " + (f'<a href="tg://user?id={esc(tg)}">{esc(d.get("tg_name") or x.get("display") or tg)}</a>' if tg else "—"),
              f"     شناسه: <code>{esc(tg or '—')}</code> · حساب: <code>{esc(x['profile'])}</code>",
              f"     حساب تلگرامش وصل است: {'✅ بله' if d.get('userbot') else '— نه'}",
              "", "<b>📊 فعالیت</b>",
              f"     {_online_lamp(d.get('last_activity'), x['profile'], long=True)}",
              f"     پیام‌ها: ۲۴ ساعت {fa(d.get('msgs_24h', 0))} · کل {fa(d.get('msgs_total', 0))} · کارهای ابزاری {fa(d.get('tool_calls_7d', 0))}"]
    elif x["status"] == "waiting":
        L += ["هنوز کسی با این لینک وارد نشده. لینک:", f"<code>{esc(x['link'])}</code>"]
    else:
        L += ["این لینک بسته شده و کسی با آن وارد نشده."]
    tlog = ((_load().get("tchat") or {}).get(x["code"]) or {}).get("log") or []
    if tlog:
        L += ["", "<b>💬 گفتگو با پشتیبانی</b> (آخرین پیام‌ها)"]
        for e in tlog[-6:]:
            L.append(f"     {'🛠 تو' if e['from'] == 'owner' else '👤 ' + esc(who)} · <i>{_jdt(e['ts'])[-5:]}</i>: {esc(e['t'][:140])}")
    if x.get("ext"):
        L += [f"⏱ تمدید شده: <b>{fa(x['ext'])} بار</b>"]
    L += ["", f"ساخته شده: {_jdt(x['created']) if x.get('created') else '—'}", LINE]
    if x.get("profile") and x.get("quota"):
        pct = x.get("pct") or 0
        lamp = "🔴" if pct >= 100 else "🟡" if pct >= 80 else "🔵"
        L.insert(-1, f"🎟 سهمیه‌ی توکن: {lamp} {_bar(pct)} <b>{fa(f'{pct:.0f}')}٪</b> — {_tok(x.get('used', 0))} از {_tok(x['quota'])}"
                     + (" · <b>تمام شده</b>" if pct >= 100 else ""))
    if x.get("profile") and _build_lamp(x["profile"]):
        L.insert(-1, f"🛠 {_build_lamp(x['profile'])}")
    kb_extra = ([[f"📈 گراف مصرف {who} #{x['code']}", f"➕ ۱۰٪ سهمیه‌ی بیشتر {who} #{x['code']}"],
                 [f"⏱ تمدید ۲۴ ساعت {who} #{x['code']}"]] if x.get("profile") else []) + \
               ([[_build_btn(x["profile"])]] if x.get("profile") and x["status"] in ("active", "paused") else [])
    c, kb = x["code"], []
    if x["status"] == "active":
        kb = [[f"⏸ توقف {who} #{c}", f"✉️ پیام به {who} #{c}"], [f"🔄 به‌روزرسانی {who} #{c}", f"🗑 حذف {who} #{c}"]]
    elif x["status"] == "paused":
        kb = [[f"▶️ ادامه {who} #{c}", f"✉️ پیام به {who} #{c}"], [f"🗑 حذف {who} #{c}"]]
    elif x["status"] == "expired":
        kb = [[f"✉️ پیام به {who} #{c}", f"🗑 حذف {who} #{c}"]]
    else:
        kb = [[f"🗑 حذف {who} #{c}"]]
    await _send(event, "\n".join(L), kb + kb_extra + [[B_TRIAL, B_MENU]], html_mode=True)
    return True


def _build_btn(name):
    return (f"🔵 اجازه‌ی ساخت روشن است — خاموش کن · {name}" if _build_allowed(name)
            else f"🔴 اجازه‌ی ساخت خاموش است — روشن کن · {name}")


async def _build_toggle(event, st, text):
    m = re.match(r"^(?:🔵|🔴) اجازه‌ی ساخت (?:روشن|خاموش) است — (روشن|خاموش) کن · ([a-z][a-z0-9]{1,20})$", text or "")
    if not m:
        return None
    on, name = m.group(1) == "روشن", m.group(2)
    try:
        perms = json.load(open(PERMS_F))
    except FileNotFoundError:
        perms = {}
    perms.setdefault(name, {})["build"] = on
    tmp = PERMS_F + ".tmp"
    json.dump(perms, open(tmp, "w"), ensure_ascii=False, indent=1)
    os.chmod(tmp, 0o600)
    os.replace(tmp, PERMS_F)
    await _send(event, f"🛠 اجازه‌ی ساخت و کدنویسی برای <b>{esc(name)}</b>: " +
                ("🔵 روشن شد — ایجنتش حالا می‌تواند برنامه، ربات یا ابزار بسازد." if on else "🔴 خاموش شد — فقط از امکانات آماده استفاده می‌کند.") +
                "\n(از پیام بعدی‌اش اعمال می‌شود.)", None, html_mode=True)
    code = next((r["code"] for r in await _trial_rows() if r.get("profile") == name), None)
    return await (_trial_page(event, code) if code else _detail(event, name))


TC_REPLY = "↩️ جواب به پشتیبانی"


async def _tchat_from_user(event, uid, text, st, rows):
    """A tester answers the owner: tapping «↩️ جواب به پشتیبانی» (next message) or swipe-replying to the owner's message.
    The message goes to the OWNER only (no LLM, no tokens), also when the test is paused or expired."""
    chats = st.get("tchat") or {}
    code = next((c for c, v in chats.items() if v.get("uid") == uid), None)
    if not code:
        return None
    tc = chats[code]
    raw = event.raw_message
    skip = {"action": "skip", "reason": "tester -> owner chat"}
    if text == TC_REPLY:
        tc["await"] = time.time()
        _save(st)
        await _send(event, "✍️ جوابت را بنویس (متن، عکس یا ویس) تا برای پشتیبانی فرستاده شود:", [[B_CANCEL]])
        return skip
    rep = getattr(raw, "reply_to_message", None)
    replying = bool(rep and getattr(rep, "message_id", None) in (tc.get("mids") or []))
    waiting = time.time() - (tc.get("await") or 0) < 1800
    if text == B_CANCEL and waiting:
        tc.pop("await", None)
        _save(st)
        await _send(event, "لغو شد.", rows)
        return skip
    if not (replying or waiting):
        return None
    tc.pop("await", None)
    who = tc.get("who") or "تست‌کننده"
    bot = raw.get_bot()
    from telegram import ReplyKeyboardMarkup
    kb = ReplyKeyboardMarkup([[f"✉️ پیام به {who} #{code}", f"👤 {who} #{code}"], [B_MENU]], resize_keyboard=True, is_persistent=False)
    if text:
        await bot.send_message(chat_id=int(OWNER), text=f"📨 {who} (تست‌کننده) نوشت:\n\n{text}", reply_markup=kb)
    else:                                              # photo / voice / file: forward a copy
        await bot.send_message(chat_id=int(OWNER), text=f"📨 {who} (تست‌کننده) این را فرستاد 👇")
        await bot.copy_message(chat_id=int(OWNER), from_chat_id=int(event.source.chat_id), message_id=int(raw.message_id), reply_markup=kb)
    tc["log"] = (tc.get("log", []) + [{"from": "tester", "t": text or "(عکس/ویس/فایل)", "ts": time.time()}])[-12:]
    _save(st)
    await _send(event, "✅ پیامت به پشتیبانی رسید؛ جواب همین‌جا برایت می‌آید.", rows)
    return skip


async def _trial_action(event, st, text):
    aw = (st.get("await") or {}).get(OWNER) or {}
    if aw.get("kind") == "trial_msg" and text and text not in (B_CANCEL, B_MENU, B_TRIAL):
        st["await"].pop(OWNER, None)
        _save(st)
        try:
            from telegram import ReplyKeyboardMarkup
            m_ = await event.raw_message.get_bot().send_message(
                chat_id=int(aw["uid"]), text="📩 پیام از پشتیبانی ایجنت هرمس:\n\n" + text + "\n\nبرای جواب دادن، «↩️ جواب به پشتیبانی» را بزن.",
                reply_markup=ReplyKeyboardMarkup([[TC_REPLY]], resize_keyboard=True, one_time_keyboard=True))
            tc = st.setdefault("tchat", {}).setdefault(aw["code"], {"uid": aw["uid"], "who": aw.get("who"), "log": [], "mids": []})
            tc["mids"] = (tc.get("mids", []) + [getattr(m_, "message_id", None)])[-20:]
            tc["log"] = (tc["log"] + [{"from": "owner", "t": text[:500], "ts": time.time()}])[-12:]
            _save(st)
            await _send(event, f"✅ پیامت برای {esc(aw.get('who') or '')} فرستاده شد. جوابش همین‌جا برایت می‌آید.", None, html_mode=True)
        except Exception as e:
            logger.warning("admin-panel: message to tester failed", exc_info=True)
            await _send(event, f"فرستاده نشد ({esc(type(e).__name__)}). شاید ربات را بسته باشد.", None, html_mode=True)
        return await _trial_page(event, aw["code"])
    m = re.match(r"^(?:[🔵🔴⏳⚪] )?(👤|🔄 به‌روزرسانی|⏸ توقف|▶️ ادامه|🗑 حذف|✉️ پیام به|✔️ بله، حذف کامل|📈 گراف مصرف|➕ ۱۰٪ سهمیه‌ی بیشتر|⏱ تمدید ۲۴ ساعت)\s.*#([0-9a-f]{8})$", text or "")
    if not m:
        return None
    kind, code = m.group(1), m.group(2)
    if kind == "📈 گراف مصرف":
        os.makedirs(DOC_INBOX, exist_ok=True)
        png = f"{DOC_INBOX}/tq-{int(time.time())}.png"
        c_, o_ = await _run([DOC_VPY, "/root/.hermes/shared-tools/docs/trial_gauge.py", code, png], 120)
        if os.path.exists(png):
            try:
                with open(png, "rb") as fh:
                    await event.raw_message.get_bot().send_photo(chat_id=int(event.source.chat_id), photo=fh)
            finally:
                os.remove(png)
        else:
            logger.warning("admin-panel trial gauge failed: %s", o_[-200:])
            await _send(event, "گراف ساخته نشد؛ دوباره بزن.")
        return await _trial_page(event, code)
    if kind == "⏱ تمدید ۲۴ ساعت":
        r = await _admin_json("trial-extend", code)
        if r.get("ok"):
            st2 = _load()
            if st2.get("quota_off", {}).pop(code, None):
                _save(st2)
            await _send(event, f"⏱ ۲۴ ساعت تمدید شد (بار {fa(r['count'])}) — تا {_jdt(r['until'])}؛ سهمیه حالا {_tok(r['quota'])}. به کاربر هم خبر داده شد.")
            if r.get("restart_needed"):
                await _admin_json("restart")
        else:
            await _send(event, f"انجام نشد: {r.get('error')}")
        return await _trial_page(event, code)
    if kind == "➕ ۱۰٪ سهمیه‌ی بیشتر":
        r = await _admin_json("trial-bonus", code)
        if r.get("ok"):
            await _send(event, f"➕ {_tok(r['added'])} توکن به سهمیه اضافه شد — حالا {_tok(r['used'])} از {_tok(r['quota'])} ({fa(f'{r['pct']:.0f}')}٪).")
            st2 = _load()
            uid_ = next((x.get("uid") for x in await _trial_rows() if x["code"] == code), None)
            if uid_ and st2.get("quota_off", {}).pop(code, None):
                _save(st2)
                try:
                    await event.raw_message.get_bot().send_message(chat_id=int(uid_), text="🎁 سهمیه‌ی تستت بیشتر شد؛ می‌توانی ادامه بدهی.")
                except Exception:
                    logger.warning("admin-panel: bonus notice failed", exc_info=True)
        else:
            await _send(event, f"انجام نشد: {r.get('error')}")
        return await _trial_page(event, code)
    if kind in ("👤", "🔄 به‌روزرسانی"):
        return await _trial_page(event, code)
    if kind == "✉️ پیام به":
        x = next((r for r in await _trial_rows() if r["code"] == code), None)
        if not x or not x.get("uid"):
            await _send(event, "این نفر هنوز وارد نشده؛ پیام فرستادن ممکن نیست.", [[B_TRIAL, B_MENU]])
            return True
        st.setdefault("await", {})[OWNER] = {"kind": "trial_msg", "code": code, "uid": x["uid"], "who": x.get("label") or ""}
        _save(st)
        await _send(event, f"✉️ پیامت به {esc(x.get('label') or '')} را بنویس (همان‌طور که می‌نویسی، از طرف «پشتیبانی ایجنت هرمس» برایش می‌رود):",
                    [[B_CANCEL]], html_mode=True)
        return True
    if kind == "🗑 حذف":
        await _send(event, "🗑 این تست کامل پاک شود؟\nلینک باطل می‌شود و اگر کسی با آن وارد شده، حسابِ تستش و همه‌ی داده‌هایش برای همیشه پاک می‌شود، "
                           "اتصال تلگرامش هم بسته می‌شود و دیگر به ربات دسترسی ندارد.",
                    [[f"✔️ بله، حذف کامل #{code}"], [f"👤 برگشت #{code}"], [B_TRIAL, B_MENU]])
        return True
    action = {"⏸ توقف": "pause", "▶️ ادامه": "resume", "✔️ بله، حذف کامل": "delete"}[kind]
    r = await _admin_json(f"trial-{action}", code)
    if not r.get("ok"):
        await _send(event, f"انجام نشد: {r.get('error')}", [[B_TRIAL, B_MENU]])
        return True
    if r.get("restart_needed"):
        await _admin_json("restart")
    done = {"pause": "⏸ همین الان متوقف شد؛ از پیام بعدی‌اش دیگر هیچ جوابی از هوش مصنوعی نمی‌گیرد (توکنی مصرف نمی‌شود).",
            "resume": "▶️ دوباره فعال شد.", "delete": "🗑 کامل پاک شد."}[action]
    await _send(event, done + (" لینک هنوز استفاده نشده بود و باطل شد." if r.get("closed_link") else ""))
    return await (_trials(event) if action == "delete" else _trial_page(event, code))


NAME_FA = {"کاربر۳": "user3", "کاربر۵": "user5", "کاربر۴": "user4", "کاربر۱": "user1", "کاربر۲": "user2",
           "کاربر۶": "user6", "کاربر۷": "user7",
           # voice-typing variants seen or likely
           "موعد": "user3", "ماحد": "user3", "ماهت": "user3", "ماهِد": "user3", "مائد": "user3",
           "کاربر۵": "user5", "کاربر۶": "user6", "کاربر۶": "user6", "کاربر۱": "user1", "کاربر۲": "user2", "کاربر۷": "user7"}


def _profile_from_name(raw):
    """Persian or Latin person name -> profile id (static map, trial labels, or the profile id itself)."""
    w = (raw or "").strip().strip("«»\"'").replace("ي", "ی").replace("ك", "ک")
    if not w:
        return None
    if re.fullmatch(r"[a-z][a-z0-9]{1,20}", w.lower()) and os.path.isdir(f"/root/.hermes/profiles/{w.lower()}"):
        return w.lower()
    if w in NAME_FA:
        return NAME_FA[w]
    import difflib
    close = difflib.get_close_matches(w, list(NAME_FA), n=1, cutoff=0.6)
    if close:
        return NAME_FA[close[0]]
    try:
        for prof, label in json.load(open("/root/.hermes/shared-tools/admin/labels.json")).items():
            if label.strip() == w:
                return prof
    except FileNotFoundError:
        pass
    except Exception:
        logger.warning("admin-panel: labels unreadable", exc_info=True)
    return None


async def _invite(event, name):
    r = await _admin_json("invite", name)
    if not r.get("ok"):
        msg = {"no_such_profile": f"پروفایلی به اسم «{name}» نیست.",
               "already_bound": f"«{name}» قبلاً وصل شده است (شناسه {r.get('tg_id')})."}.get(r.get("error"), r.get("error"))
        await _send(event, msg, [[S_BACKU, B_MENU]])
        return True
    await _send(event, f"🔗 لینک اتصال اختصاصی <b>{esc(name)}</b>\nفقط یک بار کار می‌کند و هر کس بازش کند به همین پروفایل وصل می‌شود (۳ روز آزمایشی معمولی؛ سطحش را از صفحه‌ی کاربر عوض کن). این لینک را برایش بفرست:",
                [[f"👤 {name}", S_BACKU], [B_MENU]], html_mode=True)
    await _send(event, r["link"])
    return True


async def _trial_claim(event, uid, code):
    src = event.source
    disp = (getattr(src, "user_name", "") or uid).replace(" ", "_")[:40]
    await _send(event, "⏳ در حال ساختن حساب تست تو…")
    r = await _admin_json("trial-claim", code, uid, disp)
    if not r.get("ok"):
        msg = {"closed": "این لینک تست بسته شده یا معتبر نیست.", "full": "ظرفیت این لینک تست پر شده.",
               "already_user": "تو از قبل حساب داری؛ همین‌جا پیام بده."}.get(r.get("error"), "الان ساخت حساب تست ممکن نشد؛ کمی بعد دوباره امتحان کن.")
        await _send(event, msg)
        return
    try:
        from gateway.pairing import PairingStore
        PairingStore()._approve_user("telegram", uid, getattr(src, "user_name", "") or "")
    except Exception:
        logger.warning("admin-panel: trial pairing approve failed for %s", uid, exc_info=True)
    st = _load()
    st.setdefault("welcome", {})[uid] = r["name"]
    _save(st)
    await _admin_json("restart")
    tt = "پرمیوم" if r.get("tier") == "premium" else "معمولی"
    if r.get("invite"):
        await _admin_json("restart")
        await _send(event, "✅ به ایجنت هرمس وصل شدی.\nحدود یک دقیقه دیگر یک «سلام» بفرست تا دکمه‌ها و قابلیت‌ها برایت باز شود.")
        await event.raw_message.get_bot().send_message(
            chat_id=int(OWNER), text=f"🔗 «{r['name']}» با لینک اتصالش وصل شد.\nاسم تلگرامش: {getattr(src, 'user_name', '') or '—'} · شناسه {uid}\nسطح: {tt}")
        return
    hi = f"سلام {r['label']}! " if r.get("label") else ""
    await _send(event, f"✅ {hi}حساب تست ایجنت هرمس برایت ساخته شد: نسخه‌ی {tt}، {fa(int(r['days']) * 24)} ساعت رایگان.\n"
                       "حدود یک دقیقه دیگر یک «سلام» بفرست تا دکمه‌ها و همه‌ی قابلیت‌ها برایت باز شود.")
    await event.raw_message.get_bot().send_message(
        chat_id=int(OWNER), text=f"🎁 «{r.get('label') or 'بی‌نام'}» با لینک تستش وارد شد.\n"
                                 f"اسم تلگرامش: {getattr(src, 'user_name', '') or '—'} · شناسه {uid}\n"
                                 f"پروفایل {r['name']} · تست {tt} {r['days']} روزه")


async def _dashboard(event):
    users = await _admin_json("list")
    users = users if isinstance(users, list) else []
    paired = [u for u in users if u["status"] != "unpaired"]
    online = sum(1 for u in paired if u["status"] == "on" and _is_online(u.get("last_activity"), u["name"]))
    today = sum(u.get("msgs_24h", 0) for u in paired)
    pend = await _admin_json("pending")
    orders = (await _admin_json("orders") or {}).get("orders", {})
    waiting = sum(1 for v in orders.values() if v.get("status") == "receipt_sent")
    income = sum(v.get("price", 0) for v in orders.values() if v.get("status") == "approved")
    c, model = await _run(["/bin/sh", "-c", "grep -m1 -E '^\\s+default:' /root/.hermes/config.yaml"], 10)
    L = ["<b>🎛 پنل ادمین ایجنت هرمس</b>", LINE,
         f"👥 کاربران وصل: <b>{fa(len(paired))}</b>   ·   🔵 آنلاین الان: <b>{fa(online)}</b>",
         f"💬 پیام‌های امروز: <b>{fa(today)}</b>",
         f"📥 درخواست اتصال در انتظار: <b>{fa(len(pend) if isinstance(pend, list) else 0)}</b>",
         f"💳 رسید در انتظار تأیید: <b>{fa(waiting)}</b>   ·   جمع دریافتی: <b>{fa(income)}</b> تومان",
         f"🤖 مدل: <code>{esc(model.split(':', 1)[-1].strip().strip(chr(34)))}</code>", LINE,
         "یکی از دکمه‌ها را انتخاب کن 👇"]
    await _send(event, "\n".join(L), _admin_rows(), html_mode=True)
    return True


async def _doctor_json(*args, timeout=240):
    code, out = await _run([SYS_PY, DOCTOR_PY, *args], timeout)
    try:
        return json.loads(out.splitlines()[-1])
    except Exception:
        logger.warning("admin-panel: doctor %s -> %s", args, out[-300:])
        return None


def _uid_of(name):
    return _roster().get(name)


def _user_reply_rows():
    return [[SUP_OK, SUP_BAD], [B_NEWCHAT, B_HELP]]


async def _fix_user(event, name, by_owner=False, report=""):
    """Check + safe repair of ONE user's account; tells the owner, and the user (politely), with feedback buttons."""
    from telegram import ReplyKeyboardMarkup
    bot = event.raw_message.get_bot()
    if by_owner:
        await _send(event, f"⏳ بررسی و رفع مشکل حساب {name}…")
    checks = await _doctor_json("user", name) or []
    r = await _doctor_json("userfix", name, timeout=330) or {"done": ["رفع خودکار انجام نشد"], "notes": []}
    bad = [c for c in checks if not c.get("ok")]
    icon = {"ok": "✅", "warn": "⚠️", "fail": "❌"}
    owner_txt = ([f"<b>🛠 رفع مشکل حساب {esc(name)}</b>", LINE] +
                 ([f"🆘 گزارش کاربر: «{esc(report[:500])}»", ""] if report else []) +
                 ["<b>بررسی:</b>"] + [f"{icon.get(c['level'], '•')} {esc(c['title'])}: {esc(c['detail'])}" for c in checks] +
                 ["", "<b>انجام شد:</b>"] + [f"• {esc(x)}" for x in r.get("done", [])] +
                 ([""] + [f"ℹ️ {esc(x)}" for x in r.get("notes", [])] if r.get("notes") else []))
    if by_owner:
        await _send(event, "\n".join(owner_txt), [[f"👤 {name}", S_BACKU], [B_MENU]], html_mode=True)
    else:
        await bot.send_message(chat_id=int(OWNER), text=rtl("\n".join(owner_txt)), parse_mode="HTML")
    uid = _uid_of(name)
    if uid:
        clean = all("پیدا نشد" in x for x in r.get("done", []))
        user_txt = (("🛠 حساب شما در ایجنت هرمس کامل بررسی شد و از نظر فنی سالم است.\n\n" if clean else
                     "🛠 حساب شما در ایجنت هرمس بررسی شد و مشکل‌های پیداشده برطرف شد.\n\n") +
                    "\n".join(f"• {x}" for x in r.get("done", [])) +
                    ("\n\nایجنت چند ثانیه ری‌استارت شد؛ یک دقیقه صبر کنید." if r.get("restarted") else "") +
                    "\n\nلطفاً دوباره امتحان کنید و نتیجه را با یکی از دکمه‌های پایین اطلاع دهید. 🙏")
        try:
            await bot.send_message(chat_id=int(uid), text=rtl(user_txt),
                                   reply_markup=ReplyKeyboardMarkup(_user_reply_rows(), resize_keyboard=True, is_persistent=False))
            st = _load()
            sup = st.setdefault("support", {}).setdefault(uid, {})
            sup.update({"stage": "await_feedback", "name": name, "since": time.time(), "round": sup.get("round", 0) + 1})
            _save(st)
        except Exception:
            logger.warning("admin-panel: could not message user %s", name, exc_info=True)
    return True


async def _support(event, uid, name, text, st):
    """User side of the support chat. Returns a dispatch result or None (message goes to the agent)."""
    skip = {"action": "skip", "reason": "support"}
    sup = st.get("support", {}).get(uid) or {}
    tier, until, active = _tier_of(name)
    rows = _user_rows(tier, active, name)
    if text == B_SUPPORT:
        st.setdefault("support", {})[uid] = {"stage": "await_report", "name": name, "since": time.time(), "round": 0}
        _save(st)
        await _send(event, "🆘 پشتیبانی ایجنت هرمس\nمشکلت را در یک پیام کوتاه بنویس (مثلاً «جواب نمی‌ده» یا «فایل رو نمی‌خونه»).\n"
                           "حسابت خودکار بررسی و رفع می‌شود و گزارشش به ادمین هم می‌رسد.", [[SUP_CANCEL]])
        return skip
    if text == SUP_CANCEL:
        st.get("support", {}).pop(uid, None)
        _save(st)
        await _send(event, "پشتیبانی لغو شد.", rows)
        return skip
    stage = sup.get("stage")
    if stage == "await_report" and time.time() - sup.get("since", 0) < 3600:
        report = text or "(پیام غیرمتنی)"
        await _send(event, "⏳ در حال بررسی و رفع مشکل حسابت… (حدود یک دقیقه)")
        if re.search(r"دکمه|منو|کیبورد", report):
            st.setdefault("kb", {}).pop(uid, None)
            _save(st)
        await _fix_user(event, name, report=report)
        return skip
    if stage == "await_feedback" and text in (SUP_OK, SUP_BAD):
        bot = event.raw_message.get_bot()
        if text == SUP_OK:
            st.get("support", {}).pop(uid, None)
            _save(st)
            await _send(event, "🙏 خیلی ممنون که خبر دادی. خوشحالیم که مشکل حل شد.", rows)
            await bot.send_message(chat_id=int(OWNER), text=f"✅ {name}: مشکلش حل شد (تأیید خود کاربر).")
            return skip
        rnd = sup.get("round", 1)
        if rnd < 2:
            await _send(event, "متأسفیم 🙏 یک بار دیگر، کامل‌تر بررسی می‌کنیم. اگر بشود، یک «🔄 گفتگوی تازه» هم شروع کن.")
            await _admin_json("restart")              # debounced: one restart even if the repair also asks for one
            await _fix_user(event, name, report="(کاربر گفت هنوز مشکل دارد — دور دوم)")
            return skip
        st.get("support", {}).pop(uid, None)
        _save(st)
        await _send(event, "🙏 ممنون از صبرت. مشکل برای بررسی دقیق‌تر به ادمین اطلاع داده شد و به‌زودی همین‌جا خبرت می‌کنیم.", rows)
        await bot.send_message(chat_id=int(OWNER), text=f"❗ {name}: بعد از دو بار رفع خودکار هنوز مشکل دارد — بررسی دستی لازم است (🛠 عیب‌یابی یا Claude).")
        return skip
    if stage == "await_feedback":
        st.get("support", {}).pop(uid, None)            # user moved on: normal chat again
        _save(st)
    return None


async def _doctor(event):
    await _send(event, "⏳ در حال بررسی همه‌ی بخش‌ها… (حدود نیم دقیقه)")
    res = await _doctor_json("check")
    if not isinstance(res, list):
        await _send(event, "بررسی انجام نشد. «🔄 ری‌استارت ایجنت» را امتحان کن.", [[D_RESTART], [B_MENU]])
        return True
    icon = {"ok": "✅", "warn": "⚠️", "fail": "❌"}
    bad = [c for c in res if not c["ok"]]
    L = ["<b>🛠 عیب‌یابی ایجنت هرمس</b>", LINE] + [f"{icon.get(c['level'], '•')} <b>{esc(c['title'])}</b>\n     {esc(c['detail'])}" for c in res] + [LINE]
    L.append("✅ همه‌چیز سالم است." if not bad else f"{fa(len(bad))} مورد نیاز به توجه دارد. راه‌حل‌های امن با دکمه‌های پایین:")
    fixes = {c["fix"] for c in bad if c.get("fix")}
    rows = []
    if "nous-login" in fixes:
        rows.append([D_NOUS])
    if "clean" in fixes:
        rows.append([D_CLEAN])
    rows += [[D_RESTART], [B_SYS, B_MENU]]
    if any(c["id"] == "openrouter" and not c["ok"] for c in res):
        L.append("ℹ️ سهمیه‌ی OpenRouter با دکمه درست نمی‌شود: یا تا ۳:۳۰ بامداد صبر کن، یا یک بار ۱۰ دلار شارژ کن (سقف ۱۰۰۰ در روز).")
    await _send(event, "\n".join(L), rows, html_mode=True)
    return True


async def _doctor_fix(event, action):
    r = await _doctor_json("fix", action, timeout=330) or {"ok": False, "msg": "انجام نشد."}
    await _send(event, ("✅ " if r.get("ok") else "❌ ") + esc(r.get("msg", "")), [[B_DOC, B_MENU]], html_mode=True)
    if r.get("link"):
        await _send(event, r["link"])
    return True


async def _sysstatus(event):
    parts = []
    c, o = await _run(["systemctl", "--user", "is-active", "hermes-gateway"], 20)
    parts.append(f"⚙️ ایجنت (گیت‌وی): {'✅ فعال' if o.strip() == 'active' else '❌ ' + esc(o.strip())}")
    c, o = await _run(["/root/.local/bin/hermes", "auth", "list"], 60)
    parts.append("🔑 ورود مدل (Nous): " + ("✅ دارد" if "nous" in o and "credentials" in o and "(0 " not in o else "❌ ندارد — ورود دوباره لازم است"))
    c, o = await _run(["/bin/sh", "-c", "grep -m1 -E '^\\s+default:' /root/.hermes/config.yaml; grep -A2 '^fallback_model:' /root/.hermes/config.yaml | grep '^  model:'"], 10)
    ms = [ln.split(":", 1)[-1].strip().strip('"') for ln in o.splitlines() if ":" in ln]
    parts.append(f"🤖 مدل اصلی: <code>{esc(ms[0] if ms else '?')}</code>")
    if len(ms) > 1:
        parts.append(f"🛟 مدل پشتیبان: <code>{esc(ms[1])}</code>")
    mu = await _admin_json("model-usage") or {}
    orq = mu.get("openrouter") or {}
    if orq:
        parts.append(f"📈 سهمیه‌ی رایگان امروز OpenRouter (ERNIE): <b>{fa(orq.get('used', 0))}</b> از {fa(orq.get('limit', 0))} · باقی‌مانده {fa(orq.get('remaining', 0))}")
        if not orq.get("remaining"):
            parts.append("     ⚠️ سهمیه‌ی امروز تمام شده؛ جواب‌ها با مدل‌های پشتیبان ادامه پیدا می‌کنند (ساعت ۳:۳۰ بامداد تهران دوباره پر می‌شود).")
    parts.append(f"💬 جواب‌های ایجنت امروز (همه‌ی پروفایل‌ها): <b>{fa(mu.get('replies_today', 0))}</b>")
    c, o = await _run(["/root/.local/bin/hermes", "-p", "adsaccount", "cron", "list"], 60)
    parts.append(f"⏰ کرون‌های فعال Owner: {fa(o.count('[active]'))}")
    c, o = await _run(["/bin/sh", "-c", "tail -1 /root/.hermes/ads/stats/divar_ads.log"], 10)
    parts.append(f"📢 آخرین تبلیغ دیوار: <code>{esc(o[-70:] or '—')}</code>")
    c, o = await _run(["/bin/sh", "-c", "df -h / | awk 'NR==2{print $5\" پر — \"$4\" آزاد\"}'"], 10)
    parts.append("💽 دیسک: " + esc(o))
    await _send(event, "<b>🩺 وضعیت سیستم</b>\n" + LINE + "\n" + "\n".join(parts), _admin_rows(), html_mode=True)
    return True


async def _script(event, title, args, timeout=240):
    await _send(event, f"⏳ {title}…")
    code, o = await _run(args, timeout)
    await _send(event, f"<b>{title}</b>\n{LINE}\n{esc(o or '(خروجی خالی)')}", _admin_rows(), html_mode=True)
    return True


# ---------------- dispatch ----------------
async def _admin(event, text, st):
    aw = st.get("await", {}).get(OWNER)
    if text in (B_CANCEL, B_MENU, "🔙 منوی ادمین", "/admin", "پنل ادمین", "منوی ادمین"):
        st.get("await", {}).pop(OWNER, None)
        _save(st)
        return await _dashboard(event)
    if (aw or {}).get("kind") in ("media_in", "media_menu", "media_auto") and (
            _media_file(getattr(event, "raw_message", None))[0] is not None or (aw.get("folder") == "پرامپت" and text not in (M_DONE, M_MENU, B_DOCS))):
        r = await _media(event, text, st)                 # captions / prompt text belong to the media item, not to other commands
        if r is not None:
            return r
    r = await _build_toggle(event, st, text)
    if r is not None:
        return r
    r = await _trials_nav(event, text)
    if r is not None:
        return r
    r = await _trial_action(event, st, text)
    if r is not None:
        return r
    r = await _tokens(event, text)
    if r is not None:
        return r
    if text == B_DOC:
        return await _doctor(event)
    if text == S_FIXUSER and st.get("sel"):
        return await _fix_user(event, st["sel"], by_owner=True)
    if text == D_RESTART:
        return await _send(event, "ایجنت ری‌استارت شود؟ حدود ۲۰ ثانیه هیچ کاربری جواب نمی‌گیرد.", [[D_RESTART_OK], [B_DOC, B_MENU]])
    if text == D_RESTART_OK:
        return await _doctor_fix(event, "restart")
    if text == D_CLEAN:
        return await _doctor_fix(event, "clean")
    if text == D_NOUS:
        return await _doctor_fix(event, "nous-login")
    if text == B_TOOLS:
        return await _send(event, "🧰 ابزارهای شخصی خودت (مثل بقیه‌ی کاربرها). برای برگشت «🏠 منوی ادمین».", _tools_rows())
    sel = st.get("sel")
    r = await _account(event, text, st)
    if r is not None:
        return r
    if sel and text in (S_PREM, S_BASIC, S_FOREVER):
        return await _set_tier(event, sel, "basic" if text == S_BASIC else "premium", 0 if text == S_FOREVER else 365)
    if sel and text == S_OFF:
        return await _send(event, f"دسترسی <b>{esc(sel)}</b> قطع شود؟\nداده‌اش پاک نمی‌شود و هر وقت بخواهی وصلش می‌کنی.",
                           [[f"✔️ تأیید قطع {sel}"], [f"👤 {sel}", B_MENU]], html_mode=True)
    if sel and text == S_ON:
        return await _set(event, sel, "on")
    if text == S_BACKU:
        return await _users(event)
    if text == S_INVITE and sel:
        return await _invite(event, sel)
    if text.count("لینک") > 1:                       # voice typing often repeats the sentence
        text = "لینک" + text.rsplit("لینک", 1)[1]
    m = re.match(r"^(?:🔗\s*)?لینک\s*(?:اتصال|ورود|دعوت)?\s*(?:به\s*|برای\s*)?(.+?)\s*(?:رو|را)?\s*(?:بده|بفرست|می‌خوام|میخوام|بساز)?\s*[.!؟?]*$", text)
    if m:
        who = _profile_from_name(m.group(1))
        if who:
            return await _invite(event, who)
    r = await _media(event, text, st)
    if r is not None:
        return r
    r = await _docs(event, text, st)
    if r is not None:
        return r
    r = await _tgsearch(event, OWNER, OWNER_SESS, text, st, _biz_rows())
    if r is not None:
        return r
    r = await _biz(event, text, st)
    if r is not None:
        return r
    if aw and aw.get("kind") == "trial_name":
        label = text.strip()
        if not label or len(label) > 40 or label.startswith("/"):
            return await _send(event, "یک اسم کوتاه بفرست (حداکثر ۴۰ حرف):", [[B_CANCEL]])
        st["await"].pop(OWNER, None)
        _save(st)
        r = await _admin_json("trial-new", "1", TRIAL_DAYS, aw["tier"], label)
        tt = "پرمیوم" if aw["tier"] == "premium" else "معمولی"
        await _send(event, f"🎁 لینک تست {tt} برای «{label}» (۲۴ ساعت رایگان، فقط برای یک نفر). هر وقت خواستی از «🎁 لینک تست» متوقف یا پاکش کن:", [[B_TRIAL, B_MENU]])
        return await _send(event, r.get("link", "خطا در ساخت لینک"))   # link alone, easy to forward
    if aw and aw.get("kind") == "new_name":
        name = text.strip().lower()
        if not NAME_RE.match(name):
            return await _send(event, "اسم فقط حروف انگلیسی کوچک و عدد، با حرف شروع شود (مثل sara یا ali2). دوباره بفرست:",
                               [[B_CANCEL]])
        st["await"].pop(OWNER, None)
        _save(st)
        await _send(event, f"⏳ ساخت پروفایل «{name}»…")
        r = await _admin_json("create", name)
        if not r.get("ok"):
            msg = {"exists": "این اسم قبلاً هست.", "bad_name": "اسم نامعتبر است."}.get(r.get("error"), r.get("error"))
            return await _send(event, f"ساخته نشد: {msg}", _admin_rows())
        if aw.get("bind_uid"):
            return await _activate(event, aw["bind_uid"], name)
        return await _send(event, f"✅ پروفایل «{name}» ساخته شد با همه‌ی قابلیت‌های عمومی ایجنت (حافظه و داده‌ی خالی، جدا از بقیه).\n"
                                  "لینک ربات را برایش بفرست: https://t.me/your_agent_bot\n"
                                  "وقتی پیام داد، از «📥 درخواست‌های اتصال» فعالش کن.", _admin_rows())
    if text == B_USERS:
        return await _users(event)
    if text == B_PAY:
        return await _payments(event)
    if text == B_TRIAL:
        return await _trials(event)
    tk = next((k for k, v in B_TRIAL_NEW.items() if v == text), None)
    if tk:
        st.setdefault("await", {})[OWNER] = {"kind": "trial_name", "tier": tk}
        _save(st)
        return await _send(event, f"{text}: لینک تست برای چه کسی است؟ اسمش را بفرست (مثلاً سارا).\nایجنتش همین اسم را به خاطر می‌سپارد و با همین اسم صدایش می‌زند.", [[B_CANCEL]])
    r = await _trial_action(event, st, text)
    if r is not None:
        return r
    m = re.match(r"^(✔️ تأیید|✖️ رد) پرداخت #(\d+)$", text)
    if m:
        return await _decide(event, m.group(2), m.group(1).startswith("✔"))
    m = re.match(r"^(⭐ پرمیوم یک سال|🔹 معمولی یک سال|♾ پرمیوم دائمی) ([a-z][a-z0-9]{1,20})$", text)
    if m:
        kind = m.group(1)
        return await _set_tier(event, m.group(2), "basic" if kind.startswith("🔹") else "premium",
                               0 if kind.startswith("♾") else 365)
    m = re.match(r"^(?:[🔵🔴⛔] )?👤 ([a-z][a-z0-9]{1,20})$", text)
    if m:
        return await _detail(event, m.group(1))
    m = re.match(r"^⛔ قطع ([a-z][a-z0-9]{1,20})$", text)
    if m:
        return await _send(event, f"دسترسی {m.group(1)} قطع شود؟ (داده‌اش پاک نمی‌شود؛ هر وقت بخواهی وصلش کن)",
                           [[f"✔️ تأیید قطع {m.group(1)}"], [f"👤 {m.group(1)}", B_MENU]])
    m = re.match(r"^✔️ تأیید قطع ([a-z][a-z0-9]{1,20})$", text)
    if m:
        return await _set(event, m.group(1), "off")
    m = re.match(r"^✅ وصل ([a-z][a-z0-9]{1,20})$", text)
    if m:
        return await _set(event, m.group(1), "on")
    if text == B_NEW:
        st.setdefault("await", {})[OWNER] = {"kind": "new_name"}
        _save(st)
        return await _send(event, "اسم کاربر جدید را بفرست (انگلیسی کوچک، مثل sara):", [[B_CANCEL]])
    if text in (B_REQ, "📥 درخواست‌های اتصال"):
        return await _requests(event, st)
    m = re.match(r"^✅ تأیید (\d{4,15})$", text)
    if m:
        return await _approve_pick(event, m.group(1))
    m = re.match(r"^🔗 (\d{4,15}) ← ([a-z][a-z0-9]{1,20})$", text)
    if m:
        return await _activate(event, m.group(1), m.group(2))
    m = re.match(r"^➕ پروفایل تازه برای (\d{4,15})$", text)
    if m:
        st.setdefault("await", {})[OWNER] = {"kind": "new_name", "bind_uid": m.group(1)}
        _save(st)
        return await _send(event, "اسم پروفایل تازه را بفرست (انگلیسی کوچک):", [[B_CANCEL]])
    if text == B_SYS:
        return await _sysstatus(event)
    if text == B_STATS:
        return await _script(event, "📊 آمار لحظه‌ای کانال و گروه", [SYS_PY, f"{ADS}/chan_stats.py", "report", "--hours", "1", "--live"])
    if text == B_SALES:
        return await _script(event, "💰 گزارش فروش", [SYS_PY, f"{ADS}/sales_report.py"])
    if text == B_FEST:
        return await _script(event, "🎉 وضعیت جشنواره", [SYS_PY, f"{ADS}/flash_sale.py", "status"])
    if text == B_ADD:
        return await _script(event, "📈 وضعیت ادد خودکار", [SYS_PY, f"{ADS}/add_members.py", "--auto", "status"])
    if text == B_AD:
        return await _send(event, "یک تبلیغ (پوستر مناسب همین ساعت از ۱۲ پوستر خودت) الان در کانال و گروه HermesVPN پست شود؟",
                           [[B_AD_OK], [B_MENU]])
    if text == B_AD_OK:
        return await _script(event, "📢 ارسال تبلیغ", [SYS_PY, f"{ADS}/auto_ads.py"], 300)
    if text == B_HELP:
        return await _send(event, HELP_TEXT, _admin_rows())
    if text == B_LEGAL:
        await _send(event, "⚖️ حالت مشاور حقوقی فعال شد. هر وقت تمام شد، «↩️ پایان مشاوره‌ی حقوقی» را بزن.", [[B_LEGAL_END], [B_MENU]])
        return None     # let the rewrite below go to the agent
    if text == B_LEGAL_END:
        await _send(event, "↩️ به حالت عادی برگشتی.", _admin_rows())
        return None
    return await _admin_nlu(event, text, st)


ADMIN_HELP = """<b>🗣 دستورهای متنی ادمین</b> (همین‌ها را بنویس یا بگو؛ دکمه‌ها هم همین کار را می‌کنند)
━━━━━━━━━━━━━━━
👥 «کاربرها» · «لیست کاربران»
👤 «وضعیت کاربر۳» · «اطلاعات کاربر۲»
🔗 «لینک اتصال کاربر۳ رو بده» · «لینک کاربر۵»
🎁 «لینک تست پرمیوم برای محمد» · «لینک تست معمولی برای احمد»
⭐ «کاربر۷ رو پرمیوم کن» (یک سال) · «کاربر۲ رو پرمیوم دائمی کن» · «کاربر۶ رو معمولی کن»
⛔ «کاربر۳ رو قطع کن» · ✅ «کاربر۳ رو وصل کن»
➕ «کاربر جدید بساز به اسم sara» (اسم انگلیسی)
📥 «درخواست‌ها» · 💳 «پرداخت‌ها» · «پرداخت ۵ رو تأیید کن» · «پرداخت ۵ رو رد کن»
🩺 «وضعیت سیستم» · 📊 «آمار کانال» · 💰 «گزارش فروش» · 🎉 «جشنواره»
🛠 «عیب‌یابی» · «مشکل رو بررسی کن» · «ربات رو درست کن» · «چرا جواب نمی‌ده» · «ایجنت رو ری‌استارت کن»
🏠 «پنل ادمین» · ❓ «دستورها»
هر چیز دیگری را خود ایجنت جواب می‌دهد."""

_NUM = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


async def _admin_nlu(event, text, st):
    """Plain Persian admin commands, understood without the LLM. Returns None when it is not an admin command."""
    t = text.strip().replace("ي", "ی").replace("ك", "ک").translate(_NUM)
    t = re.sub(r"[.!؟?]+$", "", t).strip()
    tail = r"\s*(?:رو|را)?\s*"
    if re.fullmatch(r"(?:دستور(?:ها|ات)?|راهنمای ادمین|چه دستوراتی داری|کمک ادمین)", t):
        return await _send(event, ADMIN_HELP, _admin_rows(), html_mode=True)
    if re.search(r"چند(?: ?تا| نفر)?\s*(?:کاربر|یوزر|مشتری)|(?:کاربر|یوزر)(?:ها|ان|ا)?\s*(?:چند|چند ?تا) ?(?:نفر|تا)", t):
        users = await _admin_json("list")
        users = users if isinstance(users, list) else []
        paired = [u for u in users if u["status"] != "unpaired"]
        prem = [u for u in paired if _tier_of(u["name"])[0] == "premium" and _tier_of(u["name"])[2]]
        basic = [u for u in paired if _tier_of(u["name"])[0] == "basic" and _tier_of(u["name"])[2]]
        exp = [u for u in paired if not _tier_of(u["name"])[2]]
        name = lambda u: esc(u.get("label") or u.get("tg_name") or u["name"])
        L = ["<b>👥 شمارش کاربرها</b>", LINE,
             f"⭐ پرمیوم: <b>{fa(len(prem))}</b>" + (" — " + "، ".join(name(u) for u in prem) if prem else ""),
             f"🔹 معمولی: <b>{fa(len(basic))}</b>" + (" — " + "، ".join(name(u) for u in basic) if basic else ""),
             f"⛔ منقضی: <b>{fa(len(exp))}</b>" + (" — " + "، ".join(name(u) for u in exp) if exp else ""),
             f"🔌 کل وصل: <b>{fa(len(paired))}</b> · ⚪ پروفایل خالی: <b>{fa(len(users) - len(paired))}</b>"]
        return await _send(event, "\n".join(L), [[B_USERS], [B_MENU]], html_mode=True)
    if re.fullmatch(r"(?:لیست |فهرست )?(?:کاربر(?:ها|ان|ا)|یوزرها)(?: رو)?(?: نشون بده| بده| را نشان بده)?", t):
        return await _users(event)
    if re.fullmatch(r"(?:درخواست(?:ها|‌ها)?(?: اتصال)?|درخواست‌های اتصال)(?: رو نشون بده)?", t):
        return await _requests(event, st)
    if re.fullmatch(r"(?:پرداخت(?:ها|‌ها)|رسید(?:ها|‌ها))(?: رو نشون بده)?", t):
        return await _payments(event)
    if re.search(r"(?:عیب ?یابی|عیب‌یابی|مشکل(?:ات)?(?: رو| را)? (?:بررسی|پیدا|رفع|حل|درست) کن|(?:ربات|ایجنت|سیستم)(?: رو| را)? (?:درست|چک|بررسی) کن|چرا (?:جواب نمی‌ده|جواب نمیده|کار نمی‌کنه|کار نمیکنه|قطعه))", t):
        return await _doctor(event)
    if re.fullmatch(r"(?:ایجنت|ربات)(?: رو| را)? ری ?استارت کن|ری‌استارت(?: کن)?", t):
        return await _admin(event, D_RESTART, st)
    if re.fullmatch(r"وضعیت (?:سیستم|سرور|ایجنت|ربات)", t):
        return await _sysstatus(event)
    if re.fullmatch(r"آمار (?:کانال|گروه)(?: و گروه)?", t):
        return await _admin(event, B_STATS, st)
    if re.fullmatch(r"(?:گزارش |آمار )?فروش(?: امروز)?", t):
        return await _admin(event, B_SALES, st)
    if re.fullmatch(r"(?:وضعیت )?جشنواره", t):
        return await _admin(event, B_FEST, st)
    m = re.fullmatch(r"(?:پرداخت|سفارش|رسید)\s*#?(\d+)" + tail + r"(تأیید|تایید|قبول|رد)\s*(?:کن|بشه)?", t)
    if m:
        return await _decide(event, m.group(1), m.group(2) != "رد")
    m = re.fullmatch(r"لینک\s*تست\s*(پرمیوم|ویژه|معمولی|عادی)?\s*(?:برای|به اسم)\s*(.+?)\s*(?:رو|را)?\s*(?:بساز|بده|بفرست)?", t)
    if m:
        tier = "basic" if m.group(1) in ("معمولی", "عادی") else "premium"
        label = m.group(2).strip()[:40]
        r = await _admin_json("trial-new", "1", TRIAL_DAYS, tier, label)
        tt = "پرمیوم" if tier == "premium" else "معمولی"
        await _send(event, f"🎁 لینک تست {tt} برای «{esc(label)}» ({fa(int(TRIAL_DAYS))} روز، فقط یک نفر):", [[B_TRIAL, B_MENU]], html_mode=True)
        await _send(event, r.get("link", "خطا در ساخت لینک"))
        return True
    m = re.fullmatch(r"(?:یک |یه )?کاربر (?:جدید|تازه) (?:بساز|درست کن)\s*(?:به اسم|با اسم|اسمش)?\s*([A-Za-z][A-Za-z0-9]{1,20})?", t)
    if m:
        if m.group(1):
            st.setdefault("await", {})[OWNER] = {"kind": "new_name"}
            return await _admin(event, m.group(1).lower(), st)
        return await _admin(event, B_NEW, st)
    m = re.fullmatch(r"(?:وضعیت|اطلاعات|مشخصات|جزئیات|پروفایل)\s+(.+)", t)
    if m and _profile_from_name(m.group(1)):
        return await _detail(event, _profile_from_name(m.group(1)))
    m = re.fullmatch(r"(.+?)" + tail + r"(پرمیوم|ویژه|معمولی|عادی)\s*(دائمی|همیشگی|یک ?ساله|یک سال|ماهانه)?\s*کن", t)
    if m and _profile_from_name(m.group(1)):
        who, kind, dur = _profile_from_name(m.group(1)), m.group(2), m.group(3) or ""
        tier = "basic" if kind in ("معمولی", "عادی") else "premium"
        days = 0 if dur in ("دائمی", "همیشگی") else (30 if dur == "ماهانه" else 365)
        return await _set_tier(event, who, tier, days)
    m = re.fullmatch(r"(?:دسترسی\s+)?(.+?)" + tail + r"(قطع|وصل|فعال|غیرفعال|بلاک|آنبلاک)\s*کن", t)
    if m and _profile_from_name(m.group(1)):
        who, act = _profile_from_name(m.group(1)), m.group(2)
        if act in ("قطع", "غیرفعال", "بلاک"):
            return await _send(event, f"دسترسی <b>{esc(who)}</b> قطع شود؟\nداده‌اش پاک نمی‌شود و هر وقت بخواهی وصلش می‌کنی.",
                               [[f"✔️ تأیید قطع {who}"], [f"👤 {who}", B_MENU]], html_mode=True)
        return await _set(event, who, "on")
    return None   # not an admin command -> normal agent message


def _first_time(event):
    """The plugin is loaded once per profile home; make sure one Telegram message is handled at most once
    process-wide (otherwise a purchase/trial could run twice). Shared registry lives on the sys module."""
    import sys as _sys
    reg = getattr(_sys, "_admin_panel_seen", None)
    if reg is None:
        reg = _sys._admin_panel_seen = {}
    src = getattr(event, "source", None)
    key = (str(getattr(src, "chat_id", "")), str(getattr(event, "message_id", "") or getattr(src, "message_id", "")),
           (getattr(event, "text", "") or "")[:40])
    now = time.time()
    for k in [k for k, v in reg.items() if now - v > 600]:
        reg.pop(k, None)
    if key[1] and key in reg:
        logger.warning("admin-panel: duplicate dispatch ignored (%s) in %s", key[:2], __name__)
        return False
    reg[key] = now
    return True


KB_REFRESH_SEC = 1800
KBTIME = "/root/.hermes/shared-tools/admin/kbtime.json"


def _kbt_get(uid):
    try:
        return json.load(open(KBTIME)).get(uid, 0)
    except FileNotFoundError:
        return 0
    except Exception:
        logger.warning("admin-panel: kbtime unreadable", exc_info=True)
        return 0


def _kbt_set(uid):
    try:
        d = json.load(open(KBTIME))
    except Exception:
        d = {}
    d[uid] = time.time()
    tmp = KBTIME + ".tmp"
    json.dump(d, open(tmp, "w"))
    os.replace(tmp, KBTIME)


async def _kb_refresh(event, uid, rows, st):
    """Telegram clients sometimes drop a non-persistent reply keyboard; quietly re-send it when the last
    one is older than 30 minutes (one short message, no notification)."""
    if time.time() - _kbt_get(uid) < KB_REFRESH_SEC:
        return
    _kbt_set(uid)
    from telegram import ReplyKeyboardMarkup
    try:
        kw = {"message_thread_id": int(event.source.thread_id)} if str(getattr(event.source, "thread_id", "") or "").isdigit() else {}
        await event.raw_message.get_bot().send_message(
            chat_id=int(event.source.chat_id), text="🎛", disable_notification=True,
            reply_markup=ReplyKeyboardMarkup(rows, resize_keyboard=True, is_persistent=False,
                                             input_field_placeholder="پیام یا یکی از دکمه‌ها"), **kw)
    except Exception:
        logger.warning("admin-panel: keyboard refresh failed for %s", uid, exc_info=True)


async def _on_pre_gateway_dispatch(event=None, **_kwargs):
    try:
        if getattr(getattr(event, "source", None), "chat_type", "") == "dm":
            logger.warning("admin-panel hook: %s uid=%s msg=%s", __name__, getattr(event.source, "user_id", "?"), getattr(event, "message_id", "?"))
        if not _first_time(event):
            return None
        src = getattr(event, "source", None)
        if src is None or str(getattr(getattr(src, "platform", None), "value", getattr(src, "platform", ""))) != "telegram":
            return None
        if str(getattr(src, "chat_type", "")) != "dm":
            return None
        uid = str(getattr(src, "user_id", "") or "")
        text = (getattr(event, "text", "") or "").strip()
        st = _load()
        if uid == OWNER:
            if st.get("kb", {}).get(uid) != KB_VERSION and text not in ("/admin", "پنل ادمین"):
                st.setdefault("kb", {})[uid] = KB_VERSION
                _save(st)
                await _send(event, "🎛 پنل ادمین فعال شد — دکمه‌ها را با آیکون کنار کادر پیام باز و بسته کن.", _admin_rows())
            raw = getattr(event, "raw_message", None)
            has_file = _media_file(raw)[0] is not None if raw else False
            _aw = (st.get("await") or {}).get(OWNER) or {}
            if _aw.get("kind") in ("media_menu", "media_in") and time.time() - _aw.get("ts", 0) > 1800:
                st["await"].pop(OWNER, None)          # media mode ends after 30 min idle: later photos go to documents again
                _save(st)
            elif _aw.get("kind") in ("media_menu", "media_in") and has_file:
                _aw["ts"] = time.time()               # keep the mode alive while he is sending
            if has_file and not text and not (st.get("await") or {}).get(OWNER) and not _is_av(raw):
                # owner sent a captionless photo / PDF / Word -> document archive. Voice / video / audio go to his AGENT
                # (a voice note is an instruction, transcribed by the gateway's STT); media goes to Drive ONLY from «🎬 مدیا»
                # (owner 2026-11-13: «نگفتم ارسال کنی به گوگل درایو»).
                st.setdefault("await", {})[OWNER] = {"kind": "doc_file"}
                _save(st)
            waiting_doc = ((st.get("await") or {}).get(OWNER) or {}).get("kind") in ("doc_file", "media_in", "media_menu", "media_auto", "acc_file") and has_file
            handled = await _admin(event, text, st) if (text or waiting_doc) else None
            if not handled:
                await _kb_refresh(event, uid, _admin_rows(), st)
            if isinstance(handled, dict) and handled.get("rewrite"):
                return {"action": "rewrite", "text": handled["rewrite"]}
            if handled:
                return {"action": "skip", "reason": "admin panel button"}
            return _user_button(event, text)
        m = re.match(r"^/start\s+(?:test|join)-([0-9a-f]{8})$", text)
        if m and uid not in _roster_ids():
            await _trial_claim(event, uid, m.group(1))
            return {"action": "skip", "reason": "trial claim"}
        if uid in _roster_ids() and uid not in ROUTED_AT_START:
            await _send(event, "⏳ حسابت در حال آماده شدن است؛ یک دقیقه دیگر دوباره پیام بده.")
            return {"action": "skip", "reason": "profile route not loaded yet"}
        if uid in _allowed() and uid in _roster_ids():
            return await _user(event, uid, text, st)
        if uid and uid not in _allowed():
            last = st.get("notified", {}).get(uid, 0)
            if time.time() - last > 6 * 3600:
                st.setdefault("notified", {})[uid] = time.time()
                _save(st)
                await _notify_owner(event, uid)
    except Exception:
        logger.warning("admin-panel dispatch failed", exc_info=True)
    return None


async def _user(event, uid, text, st):
    name = next((n for n, i in _roster().items() if i == uid), None)
    tier, until, active = _tier_of(name) if name else ("premium", None, True)
    rows = _user_rows(tier, active, name)
    kbkey = f"{KB_VERSION}:{tier}:{active}"
    if st.get("kb", {}).get(uid) != kbkey:
        st.setdefault("kb", {})[uid] = kbkey
        welcome = st.get("welcome", {}).pop(uid, None)
        _save(st)
        await _send(event, ("✅ حسابت در ایجنت هرمس فعال شد.\n" if welcome else "") +
                    f"🎛 دکمه‌های میانبر — {_tier_label(tier, until, active)}\nبا آیکون کنار کادر پیام بازش کن.", rows)
    skip = {"action": "skip", "reason": "subscription/user panel"}
    r = await _tchat_from_user(event, uid, text, st, rows)
    if r is not None:
        return r
    if name and (text in (B_SUPPORT, SUP_CANCEL, SUP_OK, SUP_BAD) or (st.get("support", {}).get(uid) or {}).get("stage")):
        r = await _support(event, uid, name, text, st)
        if r:
            return r
    aw = st.get("await", {}).get(uid)
    raw = getattr(event, "raw_message", None)
    is_img = bool(getattr(raw, "photo", None)) or str(getattr(getattr(event, "message_type", ""), "value", "")) == "photo" or \
        str(getattr(getattr(raw, "document", None), "mime_type", "") or "").startswith("image/")
    if aw and aw.get("kind") == "receipt" and is_img:
        oid = aw["order"]
        st["await"].pop(uid, None)
        _save(st)
        bot = raw.get_bot()
        rpath = None
        try:                                              # keep the receipt in the customer's ledger (owner's business record)
            fobj = raw.photo[-1] if getattr(raw, "photo", None) else raw.document
            os.makedirs(LEDGER_TMP, mode=0o700, exist_ok=True)
            rpath = f"{LEDGER_TMP}/rcpt-{oid}-{int(time.time())}.jpg"
            await (await bot.get_file(fobj.file_id)).download_to_drive(rpath)
        except Exception:
            logger.warning("admin-panel: could not save receipt of order %s", oid, exc_info=True)
            rpath = None
        await _admin_json("order-receipt", oid, *([rpath] if rpath else []))
        if rpath and os.path.exists(rpath):
            os.remove(rpath)
        await bot.copy_message(chat_id=int(OWNER), from_chat_id=int(event.source.chat_id), message_id=int(raw.message_id))
        from telegram import ReplyKeyboardMarkup
        await bot.send_message(chat_id=int(OWNER),
                               text=f"💳 رسید سفارش #{oid}\nکاربر: {name}\n{aw.get('label', '')}\n\n{aw.get('breakdown', '')}",
                               reply_markup=ReplyKeyboardMarkup([[f"✔️ تأیید پرداخت #{oid}", f"✖️ رد پرداخت #{oid}"], [B_PAY, B_MENU]],
                                                                resize_keyboard=True, is_persistent=False))
        await _send(event, "✅ رسیدت رسید. بعد از بررسی ادمین، نسخه‌ات خودکار فعال می‌شود و همین‌جا خبرت می‌کنیم.", rows)
        return skip
    if text == B_CANCEL_BUY:
        st.get("await", {}).pop(uid, None)
        _save(st)
        await _send(event, "خرید لغو شد.", rows)
        return skip
    _law = (st.get("await") or {}).get(uid) or {}
    if _law.get("kind", "").startswith("link_") and time.time() - _law.get("ts", 0) > 600:
        st["await"].pop(uid, None)                    # abandoned login: later messages are normal chat again
        for f in (f"/root/.hermes/profiles/{name}/userbot/{name}.pending_login.json",):
            if os.path.exists(f):
                os.remove(f)
        _save(st)
    if name and not _acc_allowed(name) and (text in (B_LINK, B_SAVED, B_ACC) or text in ACC_SUB or re.match(r"^⭐ #\d+$", text or "")
                                            or ((st.get("await") or {}).get(uid) or {}).get("kind", "").startswith("link_")):
        st.get("await", {}).pop(uid, None)
        _save(st)
        await _send(event, "این قابلیت برای حساب شما فعال نیست.", rows)
        return skip
    if name and (text == B_TGSEARCH or ((st.get("await") or {}).get(uid) or {}).get("kind") == "tgsearch"):
        usess = f"/root/.hermes/profiles/{name}/userbot/{name}"
        if tier != "premium" or not active or not _acc_allowed(name):
            st.get("await", {}).pop(uid, None)
            _save(st)
            await _send(event, "این قابلیت برای حساب شما فعال نیست.", rows)
            return skip
        if not os.path.exists(usess + ".creds.json"):
            await _send(event, "برای سرچ در تلگرام اول اکانت تلگرامت را وصل کن.", [[B_LINK], [B_ACC_BACK]])
            return skip
        r = await _tgsearch(event, uid, usess, text, st, _acc_rows())
        if r is not None:
            return skip
    if name and (text in (B_LINK, B_UNLINK, B_UNLINK_OK, B_LINK_CANCEL, B_SAVED) or re.match(r"^⭐ #\d+$", text or "")
                 or ((st.get("await") or {}).get(uid) or {}).get("kind", "").startswith("link_")):
        if tier != "premium" or not active:
            st.get("await", {}).pop(uid, None)
            _save(st)
            await _send(event, "این قابلیت مخصوص نسخه‌ی پرمیوم است. برای ارتقا «⭐ اشتراک من» را بزن.", rows)
            return skip
        r = await _link(event, uid, name, text, st, rows)
        if r is not None:
            return r
    if name and text in (B_MYACC, B_MYHIST, B_MYRCPT):
        await _my_account(event, name, text, rows)
        return skip
    quotes = None
    if text == B_SUB or text.startswith(tuple(KIND_FA.values())):
        quotes = await _admin_json("quote", name) if name else []
        quotes = quotes if isinstance(quotes, list) else []
    if text == B_SUB:
        L = [f"<b>⭐ اشتراک من</b>: {_tier_label(tier, until, active)}", LINE,
             "<b>ایجنت هرمس چطور فروخته می‌شود؟</b>",
             "🔹 <b>خرید ربات (یک‌بار):</b> نسخه‌ی انتخابی‌ات برای همیشه مال خودت است؛ پروفایل جدا، حافظه‌ی جدا و همه‌ی قابلیت‌های همان نسخه برایت ساخته و تنظیم می‌شود.",
             "🖥 <b>آبونمان میزبانی و نگهداری (سالانه یا ماهانه):</b> ایجنت روی سرور اختصاصی ما شبانه‌روز روشن است. این آبونمان هزینه‌ی سرور، دامنه و اینترنت، "
             "اتصال به مدل‌های هوش مصنوعی، به‌روزرسانی‌ها و قابلیت‌های تازه، پشتیبان‌گیری، امنیت و جداسازی اطلاعاتت از بقیه، و پشتیبانی و رفع مشکل را پوشش می‌دهد. "
             "میزبانی سالانه به‌صرفه‌تر از ماهانه است.",
             "🔁 تمدید فقط آبونمان میزبانی است؛ هزینه‌ی خرید دوباره گرفته نمی‌شود. با ارتقا از معمولی به پرمیوم، فقط تفاوت دو نسخه حساب می‌شود و روزهای باقی‌مانده‌ات هدر نمی‌رود.",
             "", "<b>🔹 نسخه‌ی معمولی</b>",
             "گفتگو با ایجنت هوشمند، ⚖️ مشاور حقوقی حرفه‌ای، 🔎 جستجوی اینترنت، 📁 نگهداری و بازیابی فایل‌ها، 🎙 پیام صوتی.",
             "", "<b>⭐ نسخه‌ی پرمیوم</b>",
             "همه‌ی امکانات معمولی + 📇 دسترسی به حساب تلگرام خودت (مخاطب‌ها، چت‌ها، نخوانده‌ها، جستجو)، 📝 خلاصه و 💡 پیشنهاد جواب و 🌐 ترجمه‌ی چت‌ها، "
             "✉️ ارسال پیام از حساب خودت، 📢 مدیریت کانال و گروه خودت و تبلیغ زمان‌بندی‌شده.",
             LINE, "💬 برای خرید، تمدید، ارتقا یا اطلاع از قیمت، لطفاً با پشتیبانی تماس بگیرید: دکمه‌ی زیر را بزنید تا پشتیبانی خودش با شما تماس بگیرد."]
        await _send(event, "\n".join(L), [[B_BUYREQ], [B_SUPPORT], [B_ACC_BACK]], html_mode=True)
        return skip
    if text == B_BUYREQ:
        bot = event.raw_message.get_bot()
        who = getattr(event.source, "user_name", "") or uid
        await bot.send_message(chat_id=int(OWNER), text=rtl(f"🛒 درخواست خرید/تمدید ایجنت هرمس\nکاربر: {who} (پروفایل {name or '—'}، شناسه {uid})\n"
                                                              f"وضعیت فعلی: {_tier_label(tier, until, active)}\nبرای تنظیم اشتراکش: 👥 کاربران ← {name or ''}"))
        await _send(event, "✅ درخواستت به پشتیبانی رسید. به‌زودی همین‌جا با تو تماس می‌گیریم. 🙏", rows)
        return skip
    q = next((q for q in quotes or [] if _buy_label(q) == text), None)
    if q:
        r = await _admin_json("order-new", name, q["tier"], q["period"])
        if not r.get("ok"):
            await _send(event, "الان امکان خرید نیست؛ کمی بعد دوباره امتحان کن.", rows)
            return skip
        bd = _breakdown(r)
        st.setdefault("await", {})[uid] = {"kind": "receipt", "order": r["id"], "tier": r["tier"], "price": r["price"],
                                           "label": _buy_label(r), "breakdown": bd}
        _save(st)
        await _send(event, f"🧾 سفارش #{r['id']}\n{_buy_label(r)}\n\n{bd}\n\n"
                           f"💳 کارت: {r['card_number']}\n👤 به نام: {r['card_holder']}\n\n"
                           "بعد از واریز، عکس رسید را همین‌جا بفرست. بعد از تأیید ادمین، نسخه‌ات خودکار فعال می‌شود.",
                    [[B_CANCEL_BUY]])
        return skip
    if text.startswith(tuple(KIND_FA.values())):
        await _send(event, "قیمت‌ها به‌روز شده؛ دوباره «⭐ اشتراک من» را بزن.", rows)
        return skip
    if text == B_HELP:
        await _send(event, HELP_TEXT, rows)
        return skip
    if active and name and re.fullmatch(r"test\d{2,3}", name):
        q = _trial_quota(name)
        if q and q[1] >= q[2]:
            code_, used_, quota_ = q
            await _send(event, "⌛ سهمیه‌ی تست ایجنت هرمس تمام شد. ممنون که امتحانش کردی 🌹\nبرای ادامه یا خرید، «⭐ اشتراک من» را بزن یا با پشتیبانی تماس بگیر.", rows)
            off = st.setdefault("quota_off", {})
            if off.get(code_) != quota_:                 # tell the owner once per quota level
                off[code_] = quota_
                _save(st)
                who_ = next((v.get("label") for c_, v in json.load(open("/root/.hermes/shared-tools/admin/trials.json")).items() if c_ == code_), "") or name
                from telegram import ReplyKeyboardMarkup
                await event.raw_message.get_bot().send_message(
                    chat_id=int(OWNER), text=f"🎟 سهمیه‌ی توکن {who_} تمام شد ({_tok(used_)} از {_tok(quota_)}). دیگر از هوش مصنوعی جواب نمی‌گیرد.",
                    reply_markup=ReplyKeyboardMarkup([[f"➕ ۱۰٪ سهمیه‌ی بیشتر {who_} #{code_}"], [f"👤 {who_} #{code_}", B_MENU]],
                                                     resize_keyboard=True, is_persistent=False))
            return skip
    if not active:
        try:
            _paused = (json.load(open(TIERS)).get(name) or {}).get("paused")
        except Exception:
            _paused = False
        _trial = bool(name and re.fullmatch(r"test\d{2,3}", name))
        if _paused:
            await _send(event, "⏸ حساب تو فعلاً متوقف است. برای ادامه با پشتیبانی تماس بگیر.", [[B_SUPPORT]])
        elif _trial:
            await _send(event, "⌛ زمان تست ۲۴ ساعته‌ی ایجنت هرمس تمام شد. ممنون که امتحانش کردی 🌹\nبرای خرید «⭐ اشتراک من» را بزن یا با پشتیبانی تماس بگیر.", rows)
        else:
            await _send(event, f"⛔ اشتراکت تمام شده ({_tier_label(tier, until, active)}).\nبرای تمدید «⭐ اشتراک من» را بزن.", rows)
        return skip
    if text == B_LEGAL:
        st.setdefault("legal", {})[uid] = time.time()
        _save(st)
        await _send(event, "⚖️ حالت مشاور حقوقی فعال شد. هر وقت تمام شد، «↩️ پایان مشاوره‌ی حقوقی» را بزن.", _legal_rows(rows))
        return _user_button(event, text)
    if text == B_LEGAL_END:
        st.get("legal", {}).pop(uid, None)
        _save(st)
        await _send(event, "↩️ به حالت عادی برگشتی.", rows)
        return {"action": "rewrite", "text": LEGAL_END_TEXT}
    if text in PREMIUM_ONLY and tier != "premium":
        await _send(event, "این قابلیت مخصوص نسخه‌ی پرمیوم است. برای ارتقا «⭐ اشتراک من» را بزن.", rows)
        return skip
    if text not in USER_BUTTONS and text not in ACC_SUB and text != B_ACC:
        await _kb_refresh(event, uid, rows, st)
    if (text == B_ACC or text in ACC_SUB) and name:
        return await _acc(event, name, text, rows)
    amap = (st.get("accmap") or {}).get(uid) or {}
    if text in amap and name and tier == "premium" and active:
        e = amap[text]
        return await _biz_open_chat(event, st, uid, _bz_ctx(uid, name), e[0], e[1], e[2]) and {"action": "skip", "reason": "account chat"}
    if name and tier == "premium" and active:
        rb = await _biz(event, text, st, uid, name)
        if isinstance(rb, dict) and rb.get("rewrite"):
            return {"action": "rewrite", "text": rb["rewrite"]}
        if rb:
            return {"action": "skip", "reason": "business"}
    if text == B_ACC_BACK:
        await _send(event, "🏠 منوی اصلی", rows)
        return skip
    if text in PREMIUM_ONLY and tier != "premium":
        await _send(event, "این قابلیت مخصوص نسخه‌ی پرمیوم است. برای ارتقا «⭐ اشتراک من» را بزن.", rows)
        return skip
    return _user_button(event, text)


_ADMIN_TEXTS_BIZ = {B_BIZ}
_ADMIN_TEXTS = {B_TRIAL, *B_TRIAL_NEW.values(), B_PAY, B_USERS, B_NEW, B_REQ, B_SYS, B_STATS, B_SALES, B_FEST, B_AD, B_ADD, B_AD_OK}
_ADMIN_PATTERN = re.compile(r"^((?:[🔵🔴⛔⏳⚪] )?👤 |⛔ قطع |✔️ تأیید قطع |✅ وصل |✅ تأیید |🔗 |➕ پروفایل تازه برای )")


def _acc_rows():
    k = list(ACC_SUB)
    return [[B_SAVED, BZ_MSGMENU], [k[0], k[1]], [k[2], k[3]], [BZ_UNREAD, BZ_SEARCH], [B_TGSEARCH], [B_UNLINK, B_ACC_BACK]]


async def _acc(event, name, text, rows):
    """Own-account views for premium users, run directly (no LLM). Shown only to the account owner."""
    sess = f"/root/.hermes/profiles/{name}/userbot/{name}"
    if not (os.path.exists(sess + ".session") and os.path.exists(sess + ".creds.json")):
        await _send(event, "📇 هنوز اکانت تلگرامت به ایجنت وصل نیست.\nبا دکمه‌ی پایین در یک دقیقه وصلش کن (فقط شماره و کد ورود لازم است).",
                    [[B_LINK], [B_ACC_BACK]])
        return {"action": "skip", "reason": "account not linked"}
    if text == B_ACC:
        await _send(event, "📇 حساب تلگرام تو — کدام را ببینم؟\n(فقط خودت می‌بینی؛ چیزی ذخیره نمی‌شود)", _acc_rows())
        return {"action": "skip", "reason": "account menu"}
    kind = ACC_SUB[text]
    await _send(event, "⏳ چند لحظه…")
    if kind == "contacts":
        code, o = await _run([HPY, ACC_PY, sess, "contacts"], 90)
    else:
        code, o = await _run([HPY, ACC_PY, sess, "dialogs", "100"], 90)
    try:
        data = json.loads(o.splitlines()[-1])
    except Exception:
        logger.warning("admin-panel: account_read %s -> %s", kind, o[-200:])
        await _send(event, "خواندن حساب ممکن نشد. اگر تکرار شد «🆘 پشتیبانی و رفع مشکل» را بزن.", _acc_rows())
        return {"action": "skip", "reason": "account view"}
    if kind == "contacts":
        cs = data.get("contacts", [])
        L = [f"<b>👥 مخاطب‌ها</b> — {fa(data.get('count', 0))} نفر", "روی هر اسم بزن تا چتش در تلگرام باز شود؛ با دکمه‌های پایین مشخصات و آخرین پیام‌ها را همین‌جا ببین 👇", LINE]
        for i, c in enumerate(cs[:60], 1):
            nm = esc(c.get("name") or "—")
            L.append(f"{fa(i)}. <a href=\"{esc(c['link'])}\">{nm}</a>" + (f" (@{esc(c['username'])})" if c.get("username") else ""))
        if data.get("count", 0) > 60:
            L += [LINE, f"… و {fa(data['count'] - 60)} نفر دیگر. برای پیدا کردن کسی بنویس: «شماره‌ی علی رو پیدا کن»."]
        st = _load()
        st.setdefault("accmap", {})[str(event.source.user_id)] = {
            ACC_PFX["contact"] + (c.get("name") or "")[:28]: [c["id"], c["link"], c.get("name"), c.get("username"), c.get("phone")] for c in cs[:12]}
        _save(st)
        btns = [ACC_PFX["contact"] + (c.get("name") or "")[:28] for c in cs[:12]]
        await _send(event, "\n".join(L), [btns[i:i + 2] for i in range(0, len(btns), 2)] + _acc_rows(), html_mode=True)
        return {"action": "skip", "reason": "account view"}
    else:
        title = {"private": "💬 چت‌ها", "channel": "📢 کانال‌ها", "group": "👪 گروه‌ها"}[kind]
        items = [d for d in data if d.get("type") == kind][:40]
        L = [f"<b>{title}</b> (آخرین فعالیت اول)", "روی هر اسم بزن تا همان چت در تلگرام باز شود 👇", LINE]
        for i, d in enumerate(items, 1):
            unread = f" · 🔴 {fa(d['unread'])} نخوانده" if d.get("unread") else ""
            nm = esc(d.get("name") or "—")
            L.append(f"{fa(i)}. <a href=\"{esc(d['link'])}\">{nm}</a>{unread}" if d.get("link") else f"{fa(i)}. {nm}{unread}")
        if not items:
            L.append("موردی پیدا نشد.")
        L += [LINE, "برای دیدن آخرین پیام‌های یکی همین‌جا، دکمه‌اش را پایین بزن."]
        st = _load()
        st.setdefault("accmap", {})[str(event.source.user_id)] = {ACC_PFX[kind] + (d.get("name") or "")[:28]: [d["id"], d.get("link"), d.get("name")] for d in items[:12]}
        _save(st)
        btns = [ACC_PFX[kind] + (d.get("name") or "")[:28] for d in items[:12]]
        rows = [btns[i:i + 2] for i in range(0, len(btns), 2)] + _acc_rows()
        await _send(event, "\n".join(L), rows, html_mode=True)
        return {"action": "skip", "reason": "account view"}
    await _send(event, "\n".join(L), _acc_rows(), html_mode=True)
    return {"action": "skip", "reason": "account view"}


async def _acc_chat(event, name, entry):
    """Last messages of one of the user's own chats, with a link to open it in Telegram."""
    cid, link, title = entry[:3]
    extra = entry[3:] if len(entry) > 3 else []
    sess = f"/root/.hermes/profiles/{name}/userbot/{name}"
    await _send(event, "⏳ چند لحظه…")
    code, o = await _run([HPY, ACC_PY, sess, "history", str(cid), "15"], 90)
    try:
        msgs = json.loads(o.splitlines()[-1])
    except Exception:
        logger.warning("admin-panel: history -> %s", o[-200:])
        await _send(event, "خواندن این چت ممکن نشد.", _acc_rows())
        return {"action": "skip", "reason": "account chat"}
    L = [f"<b>{esc(title or '—')}</b>" + (f" — <a href=\"{esc(link)}\">باز کردن در تلگرام</a>" if link else "")]
    if extra:
        uname, phone = (extra + [None, None])[:2]
        L += [f"🆔 آیدی: {('@' + esc(uname)) if uname else '—'}", f"📞 شماره: {('+' + esc(phone)) if phone else '— (پنهان)'}"]
    L.append(LINE)
    for m in msgs:
        who = "👤 من" if m.get("from_me") else "🗨"
        body = esc(m.get("text") or "") or (f"[{esc(m.get('media') or 'پیام')}]")
        L.append(f"{who} <i>{fa(m.get('date', '')[5:])}</i>\n{body}")
    if not msgs:
        L.append("پیامی نیست.")
    L += [LINE, "برای جواب دادن، روی «باز کردن در تلگرام» بزن؛ یا همین‌جا بنویس: «به " + esc((title or "او").split()[0]) + " بگو …» تا از حساب خودت بفرستم."]
    await _send(event, "\n".join(L), _acc_rows(), html_mode=True)
    return {"action": "skip", "reason": "account chat"}


def _legal_rows(rows):
    return [[B_LEGAL_END]] + [r for r in rows if B_LEGAL not in r]


def _user_button(event, text):
    if text == B_LEGAL_END:
        return {"action": "rewrite", "text": LEGAL_END_TEXT}
    if text in USER_BUTTONS:
        return {"action": "rewrite", "text": USER_BUTTONS[text]}
    if text == B_NEWCHAT:
        return {"action": "rewrite", "text": "/new"}
    return None


async def _notify_owner(event, uid):
    from telegram import ReplyKeyboardMarkup
    src = event.source
    name = getattr(src, "user_name", "") or ""
    bot = event.raw_message.get_bot()
    await bot.send_message(chat_id=int(OWNER),
                           text=f"📥 درخواست اتصال تازه به ایجنت هرمس:\n{name or 'بی‌نام'} — شناسه {uid}\n"
                                "برای فعال‌سازی «📥 درخواست‌های اتصال» را بزن.",
                           reply_markup=ReplyKeyboardMarkup(_admin_rows(), resize_keyboard=True, is_persistent=False))


_UB_RE = re.compile(r"shared-tools/userbot/[a-z_0-9]+\.py.*?/profiles/([a-z][a-z0-9]{1,20})/userbot", re.S)


_PROF_RE = re.compile(r"/root/\.hermes/profiles/([A-Za-z0-9_.*?\[\]-]*)")
OWNER_WORK = {"adsaccount", "adsaccount2", "hermesgroup", "iranvpngroup", "usertemplate"}
ARCHIVE_PROFILES = {"owner2"}          # owner's second account: may use the owner's Drive archive tools


def _caller_profile():
    """Profile whose agent is running this tool call (the gateway carries it in a context-local HERMES_HOME)."""
    try:
        from hermes_constants import get_hermes_home
        h = str(get_hermes_home()).rstrip("/")
    except Exception:
        return None, "?"
    m = re.fullmatch(r"/root/\.hermes/profiles/([a-z][a-z0-9]{1,20})", h)
    return (m.group(1) if m else ("__owner__" if h == "/root/.hermes" else None)), h


CONTAINER_TOOLS = {"terminal", "process", "read_file", "write_file", "patch", "search_files", "execute_code"}
_ABS_RE = re.compile(r"(?:file://)?(?<![\w.-])(/(?:root|etc|home|var|opt|srv|proc|sys|tmp|usr|run|mnt|dev|boot|lib)\b[^\s\"'`<>|;]*|~/[^\s\"'`<>|;]*)")


def _sealed(profile):
    try:
        return "# >>> sandbox (sandbox_profile.py) >>>" in open(f"/root/.hermes/profiles/{profile}/config.yaml").read()
    except OSError:
        return False


def _host_path_block(tool_name, blob, caller):
    """Sealed users: terminal/file/code tools run INSIDE their container (paths there are harmless). Every other tool
    runs on the host, so its path arguments may only point into that user's own profile folder."""
    if tool_name in CONTAINER_TOOLS or not caller or caller == "__owner__" or caller in OWNER_WORK or not _sealed(caller):
        return None
    own = f"/root/.hermes/profiles/{caller}/"
    bad = [m for m in _ABS_RE.findall(blob.replace("\\/", "/")) if not m.replace("file://", "").startswith(own)]
    if bad:
        logger.warning("admin-panel host-path guard: BLOCK caller=%s tool=%s paths=%s", caller, tool_name, bad[:3])
        return ("دسترسی رد شد: این ابزار فقط به فایل‌های خود همین کاربر دسترسی دارد. فایل را در پوشه‌ی خانه‌ی خودت "
                f"({own}home) بساز یا از همان‌جا استفاده کن.")
    return None


PERMS_F = "/root/.hermes/shared-tools/admin/perms.json"
CODE_EXT = r"py|pyw|js|mjs|cjs|ts|tsx|jsx|sh|bash|zsh|ps1|bat|cmd|php|rb|pl|go|rs|java|kt|c|cc|cpp|h|hpp|cs|swift|lua|r|html?|css|scss|vue|svelte|sql|dockerfile|apk|exe"
_CODE_FILE_RE = re.compile(rf"\.(?:{CODE_EXT})(?:[\s\"'`;|&)]|$)|Dockerfile|requirements\.txt|package\.json", re.I)
_BUILD_CMD_RE = re.compile(
    r"(?:^|[\s;&|(`])(?:python3?|pip3?|node|npm|npx|yarn|pnpm|bun|deno|php|ruby|perl|go|gcc|g\+\+|clang|javac|java|cargo|rustc|"
    r"dotnet|docker|git\s+clone|chmod\s+\+x|crontab|nohup|systemctl|bash\s+\S+\.sh|sh\s+\S+\.sh|\./[\w.-]+)(?=[\s;&|)`]|$)", re.I)
_OWN_TOOLS_RE = re.compile(r"/root/\.hermes/shared-tools/userbot/[a-z_]+\.py")


def _build_allowed(name):
    """Owner decides per user (admin panel «🛠 اجازه‌ی ساخت و کدنویسی»); default: NOT allowed for sealed users."""
    try:
        return bool((json.load(open(PERMS_F)).get(name) or {}).get("build"))
    except FileNotFoundError:
        return False
    except Exception:
        logger.warning("admin-panel: perms unreadable", exc_info=True)
        return False


def _nobuild_block(tool_name, args, blob, caller):
    """Owner 2026-11-16: user agents may only use the features prepared for them — no coding, no building bots/apps/UIs,
    no new tools/scripts — unless the owner allowed that user. Data files (notes, .json/.md/.txt …) stay allowed."""
    if not caller or caller == "__owner__" or caller in OWNER_WORK or not _sealed(caller) or _build_allowed(caller):
        return None
    why = None
    a = args if isinstance(args, dict) else {}
    if tool_name == "execute_code":
        why = "اجرای کد"
    elif tool_name in ("write_file", "patch"):
        path = str(a.get("path") or a.get("file_path") or a.get("target") or blob)
        if _CODE_FILE_RE.search(path):
            why = "ساختن فایل برنامه"
    elif tool_name in ("terminal", "process"):
        cmd = str(a.get("command") or a.get("cmd") or blob)
        rest = _OWN_TOOLS_RE.sub(" ", cmd.replace("/root/.hermes/tools/python-3.14.7+20260901-linux-x64/bin/python3", " "))
        if _BUILD_CMD_RE.search(rest) or re.search(rf"(?:>|tee\s+)\s*\S+\.(?:{CODE_EXT})\b", rest, re.I):
            why = "برنامه‌نویسی یا نصب و اجرای برنامه"
    elif tool_name in ("cronjob", "cron") and (a.get("script") or a.get("monitor", "").startswith("/")):
        why = "اسکریپت زمان‌بندی‌شده"
    if not why:
        return None
    logger.warning("admin-panel no-build guard: BLOCK caller=%s tool=%s (%s)", caller, tool_name, why)
    return (f"این کار ({why}) در سرویس این کاربر فعال نیست: ایجنت فقط از امکانات آماده‌ی ایجنت هرمس استفاده می‌کند و برنامه، ربات، سایت یا ابزار تازه نمی‌سازد. "
            "دوباره تلاش نکن و راه دیگری برای ساختنش امتحان نکن. کوتاه و مؤدبانه به کاربر بگو این امکان جزو سرویسش نیست "
            "و اگر چنین کاری لازم دارد با «🆘 پشتیبانی» تماس بگیرد؛ بعد پیشنهاد کن با امکانات موجود چه کمکی می‌توانی بکنی.")


def _xprofile_block(blob):
    """Rule #1: an agent may touch only its OWN profile. Returns a block message or None."""
    caller, home = _caller_profile()
    targets = set(_PROF_RE.findall(blob))
    owner_sess = "/root/.hermes/userbot" in blob
    if not targets and not owner_sess and "/root/.hermes/profiles" not in blob:
        return None
    if caller is None:
        logger.warning("admin-panel xprofile guard: unknown caller home=%s targets=%s", home, sorted(targets))
        return None
    if caller == "__owner__":
        bad = {t for t in targets if t not in OWNER_WORK}
    else:
        bad = {t for t in targets if t != caller}
        if owner_sess:
            bad.add("owner")
    if "/root/.hermes/profiles" in blob and not targets:
        bad.add("*")                                   # listing all profiles
    if bad:
        logger.warning("admin-panel xprofile guard: BLOCK caller=%s targets=%s", caller, sorted(bad))
        return ("دسترسی رد شد: هر ایجنت فقط به اطلاعات خود کاربرش دسترسی دارد و به حساب، پیام‌ها و فایل‌های "
                "کاربران دیگر دسترسی ندارد. همین را کوتاه به کاربر بگو.")
    return None


def _on_pre_tool_call(tool_name=None, args=None, **_kwargs):
    """Rule #1 cross-profile guard + basic-tier or expired users may not run the userbot / channel tools."""
    try:
        blob = json.dumps(args or {}, ensure_ascii=False)
        msg = _xprofile_block(blob)
        if msg:
            return {"action": "block", "message": msg}
        caller0, _h0 = _caller_profile()
        msg = _host_path_block(tool_name, blob, caller0)
        if msg:
            return {"action": "block", "message": msg}
        msg = _nobuild_block(tool_name, args, blob, caller0)
        if msg:
            return {"action": "block", "message": msg}
        caller, _h = _caller_profile()
        if caller not in ("__owner__", None) and caller not in ARCHIVE_PROFILES and re.search(
                r"\brclone\b|\.config/rclone|archive-admin|shared-tools/docs/(media|dashboard|drive_mirror|cartoon_prep)\.py|docproc\.py\W+archive-"
                r"|reply_watch\.py|name_map\.json", blob):
            logger.warning("admin-panel archive guard: BLOCK caller=%s tool=%s", caller, tool_name)
            return {"action": "block", "message": "این ابزار (بایگانی/Google Drive مالک) برای این حساب در دسترس نیست. کوتاه همین را به کاربر بگو."}
        if caller not in ("__owner__", None) and re.search(r"phone_index\.py|phone-index|/home/owner-phone", blob):
            logger.warning("admin-panel phone guard: BLOCK caller=%s tool=%s", caller, tool_name)
            return {"action": "block", "message": "این ابزار فقط برای مالک است. کوتاه همین را به کاربر بگو."}
        m2 = re.search(r"shared-tools/userbot/(account_read|login|send_as_user|bulk_send|request_code|finish_login|finish_2fa)\.py.*?/profiles/([a-z][a-z0-9]{1,20})/userbot", blob, re.S)
        if m2 and m2.group(2) not in OWNER_WORK and not _acc_allowed(m2.group(2)):
            return {"action": "block", "message": "دسترسی به حساب تلگرام شخصی برای این کاربر فعال نیست. کوتاه همین را به کاربر بگو و ادامه نده."}
        m = _UB_RE.search(blob)
        if not m:
            return None
        name = m.group(1)
        if name not in _roster():
            return None
        tier, until, active = _tier_of(name)
        if tier != "premium" or not active:
            return {"action": "block", "message": "این قابلیت (یوزربات و مدیریت کانال) فقط در نسخه‌ی پرمیوم فعال است. "
                                                  "به کاربر بگو با دکمه‌ی «⭐ اشتراک من» ارتقا بدهد."}
    except Exception:
        logger.warning("admin-panel tier guard failed", exc_info=True)
    return None


_CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uf900-\ufaff\uff00-\uffef]+")
_FA_RE = re.compile(r"[\u0600-\u06ff]")


def _on_pre_llm_call(**_kw):
    """Today's date (Tehran) in every turn: the model must never convert dates itself (it wrote 1404 for 1405)."""
    try:
        now = time.time()
        g = time.strftime("%Y-%m-%d %H:%M", time.gmtime(now + 12600))
        wd = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه"][time.gmtime(now + 12600).tm_wday]
        lines = [f"[امروز: {wd} {_jdt(now)} شمسی · {g} میلادی (وقت تهران). تاریخ‌ها را از همین بگیر و خودت تبدیل نکن."]
        lines += _turn_facts()
        lines.append("واژه‌های ویس: ناطیف/ناتیف/نوتیف = نوتیفیکیشن (خبر دادن)؛ اکانت، کانفیگ، لینک، اسکرین، فوروارد = همان کلمه‌ی انگلیسی. "
                     "اسم آدم‌ها در ویس ممکن است غلط شنیده شود: از روی مخاطب‌ها و گفتگوی قبلی درستش کن، نپرس؛ و اسم را دقیقاً همان‌طور بنویس "
                     "که در تلگرام ثبت شده (اسم لاتین را حدسی فارسی نکن)."
                     " اول عمل کن؛ فقط اگر واقعاً مبهم بود یک سؤال کوتاه (نه چند سؤال و فهرست گزینه). فقط چیزی را بگو که ابزار برگرداند؛ وگرنه «مطمئن نیستم»."
                     " همیشه و فقط فارسی جواب بده — حتی اگر ابزاری لغو شد یا خطا داد (یک خط فارسی بگو و یک بار دوباره امتحان کن)."
                     " عدد، مبلغ، تاریخ و وضعیت سفارش را فقط از خروجی همان ابزار/دیتابیس بنویس، از حافظه یا حدس تکرار نکن؛ اگر دو عدد با هم نخواند، بگو و دوباره از ابزار بخوان.]")
        return {"context": "\n".join(lines)}
    except Exception:
        logger.warning("admin-panel date context failed", exc_info=True)
        return None


def _turn_facts():
    """Per-turn facts for the profile that is answering (works even in an old conversation whose prompt is frozen)."""
    caller, _home = _caller_profile()
    H3 = "/root/.hermes/tools/python-3.14.7+20260901-linux-x64/bin/python3"
    if caller == "__owner__":
        out = [f"حساب تلگرام شخصی Owner به تو وصل است — هرگز نگو دسترسی نداری؛ اگر قبلاً در همین گفتگو گفته‌ای «به حساب تلگرام شما دسترسی ندارم» یا اسم را ««اسم نمونه»» نوشته‌ای، اشتباه بود: خودت با ابزار چک کن و درستش را بگو. خواندن: `{H3} /root/.hermes/shared-tools/userbot/account_read.py "
               "/root/.hermes/userbot/owner history \"<اسم یا @آیدی>\" 20` (همچنین dialogs / search / saved / contacts). "
               "«تو تلگرام سرچ کن / کانال‌های فلان رو پیدا کن» = همان ابزار با `tgsearch \"<کلمه>\" 50` (جستجوی کل تلگرام: کانال/گروه/ربات عمومی)؛ "
               "۳ تا ۵ کلمه‌ی مختلف فارسی و انگلیسی را جدا بگرد و با لینک و تعداد عضو جواب بده؛ نگو ممکن نیست. "
               f"پیدا کردن اسم درست یک مخاطب: `{H3} /root/.hermes/shared-tools/userbot/reply_watch.py find \"<اسم>\"`. "
               "«هر وقت فلانی جواب داد خبرم کن» = با ابزار cron خودت یک کار زمان‌بندی‌شده بساز که history همان چت را بخواند (مثل کار قبلی Neda)، "
               "و دقیقاً بگو هر چند وقت یک بار چک می‌شود؛ پایشگر ۵دقیقه‌ای سیستمی وجود ندارد (Owner نخواسته). Google Drive هم وصل است. واتساپ و اینستاگرام واقعاً وصل نیستند.",
               "گوشی Owner (همه‌ی حافظه: عکس، اسکرین‌شات، PDF، دانلود، اسناد): خودِ گوشی متن داخل عکس‌ها و فایل‌ها را می‌خواند و فهرستش را به سرور می‌فرستد. "
               "«تو گوشیم/گالریم بگرد، عکسی که روش فلان نوشته، فایل فلان رو پیدا کن» = `/usr/bin/python3 /root/.hermes/shared-tools/docs/phone_index.py search \"<کلمه‌ها>\" 10` "
               "(اسم فایل هم جستجو می‌شود؛ چند شکل فارسی/انگلیسی را جدا امتحان کن). مسیری که با phone: شروع شود روی گوشی است: "
               "`/usr/bin/python3 /root/.hermes/shared-tools/docs/phone_index.py fetch \"<همان مسیر>\"` آن را از گوشی می‌آورد (تا ۷ دقیقه) و مسیر file را می‌دهد؛ "
               "همان را با MEDIA:<file> بفرست. "
               "«عکس‌هایی که فلان وقت گرفتم / هر عکسی از کاغذ حتی ناخوانا» (متن کمکی نمی‌کند) = `... phone_index.py sheet DCIM <YYYY-MM-DD> <YYYY-MM-DD>` "
               "(تاریخ میلادی؛ شمسی را خودت درست تبدیل کن): گوشی برگه‌های عکس کوچک شماره‌دار (۴۰ تایی) می‌سازد (تا ۱۵ دقیقه)؛ همه‌ی sheets را با MEDIA بفرست "
               "و بگو «شماره‌ی عکس را بگو تا اصلش را بیاورم»، بعد با fetch همان path را از items بیاور. `list <پوشه> <از> <تا>` فهرست فایل‌های یک بازه را می‌دهد. "
               "`status`: اگر text_still_to_read_on_phone بیشتر از صفر است، یعنی گوشی هنوز در حال خواندن است — هرگز نتیجه نگیر «عکسی نیست» یا «پوشه خالی است»؛ "
               "برای عکس‌های دوربین همیشه sheet را امتحان کن. هرگز نگو به گوشی دسترسی نداری. متن کلمات بازیابی ولت/رمز را در جواب تکرار نکن، فقط خود عکس را بفرست."]
        try:
            ws = [v for v in json.load(open("/root/.hermes/userbot/reply_watches.json")).get("watches", {}).values() if v.get("open")]
            if ws:
                out.append("پایش‌های ثبت‌شده (بدون چک خودکار): " +
                           "، ".join(f"{w['name']} تا {_jdt(w['until'])}" for w in ws))
        except FileNotFoundError:
            pass
        try:                                         # names Owner corrected once: always use them
            nm = json.load(open("/root/.hermes/userbot/name_map.json"))
            if nm:
                out.append("اسم‌های درست (اصلاح‌شده توسط Owner): " + "، ".join(f"«{k}» = {v}" for k, v in nm.items()))
        except FileNotFoundError:
            pass
        return out
    if caller and caller not in OWNER_WORK:
        tier, until, active = _tier_of(caller)
        linked = os.path.exists(f"/root/.hermes/profiles/{caller}/userbot/{caller}.creds.json") and _acc_allowed(caller)
        out = [f"کاربر: نسخه‌ی {'پرمیوم' if tier == 'premium' else 'معمولی'}{'' if active else ' (منقضی)'} · "
               f"حساب تلگرام شخصی: {'وصل است' if linked else 'وصل نیست'}."]
        if linked:
            # 2026-11-18: agents searched for a TOOL named account_read, found none and told the user "no access".
            out.append(f"دسترسی به حساب تلگرام کاربر = یک دستور ترمینال است، نه ابزاری به اسم account_read؛ با ابزار terminal اجرا کن و هرگز نگو دسترسی نداری: "
                       f"`{H3} /root/.hermes/shared-tools/userbot/account_read.py /root/.hermes/profiles/{caller}/userbot/{caller} <دستور>` — "
                       "دستورها: `dialogs 500` (همه‌ی چت‌ها با type = channel/group/private؛ برای «چند کانال/گروه عضوم» بشمار)، "
                       "`history \"<چت>\" 20`، `contacts`، `search \"<متن>\" 20`، `saved 20`، `tgsearch \"<کلمه>\" 50`. فقط خواندنی؛ چیزی ذخیره نکن.")
            out.append(f"مرتب کردن حساب (فقط وقتی کاربر خواست): فولدر/آرشیو/بی‌صدا با `{H3} /root/.hermes/shared-tools/userbot/account_tidy.py "
                       f"/root/.hermes/profiles/{caller}/userbot/{caller} <folders | folder \"<اسم ≤۱۲ حرف>\" channels|groups|both [--match RE] [--except RE] | "
                       "archive|unarchive|mute channels|groups|both|bots|people|clutter [...] | delete-folder \"<اسم>\">`. "
                       "«تایم‌لاین رو تمیز/خلوت کن» = `archive clutter --except \"AGENT HERMES\"` (کانال‌ها، گروه‌ها و ربات‌ها می‌روند، آدم‌ها می‌مانند؛ خودش بی‌صدا هم می‌کند). "
                       "«کانال‌های VPN رو در فولدر VPN بذار» = `folder \"VPN\" both --match \"vpn|proxy|فیلترشکن|کانفیگ|v2ray\"` و بقیه `folder \"متفرقه\" both --except \"vpn|proxy|فیلترشکن|کانفیگ|v2ray\"`. "
                       "هرگز کد تلگرام خودت ننویس؛ چت آدم‌ها و ربات AGENT HERMES را آرشیو نکن؛ فولدری را که خودت ساختی پاک نکن مگر کاربر بگوید؛ "
                       "و نتیجه را فقط از خروجی همین دستور بگو (now_archived)، نه از حدس.")
            out.append("«کانال/گروه/ربات فلان رو پیدا کن و عضو شو و بذار تو یه پوشه» = این مراحل را خودت تا آخر انجام بده، بدون سؤال: "
                       "۱) با account_read `tgsearch \"<کلمه>\" 50` با ۳ تا ۵ کلمه‌ی فارسی و انگلیسی جدا بگرد؛ "
                       "۲) ۸ تا ۱۵ مورد بهتر را انتخاب کن (عضو بیشتر، مرتبط با خواسته؛ هر چیزی با نشانه‌ی کودک/نوجوان، اجبار، محارم، دیپ‌فیک یا لخت کردن عکس آدم واقعی را هرگز اضافه نکن)؛ "
                       "۳) `account_tidy.py ... join \"<اسم پوشه ≤۱۲ حرف>\" @a @b @c` — عضو می‌شود/ربات را استارت می‌کند، بی‌صدا و آرشیو می‌کند و در پوشه می‌گذارد "
                       "(هر بار حداکثر ۸ تا؛ اگر بیشتر بود چند دستور پشت سر هم بده؛ هر دستور حدود ۲ دقیقه طول می‌کشد)؛ "
                       "۴) در آخر همیشه تایم‌لاین را هم تمیز کن: `account_tidy.py ... archive clutter --except \"AGENT HERMES\"` (کانال/گروه/ربات‌ها از صفحه‌ی اصلی می‌روند، آدم‌ها می‌مانند)؛ "
                       "۵) فقط از خروجی بگو کدام‌ها اضافه شد (اسم + @آیدی) و اینکه تایم‌لاین تمیز شد. «اینو از پوشه/تلگرام بردار» = `leave @a`. "
                       "اگر خروجی گفت Telegram limit، همان را کوتاه بگو و ادامه نده.")
        if _sealed(caller):
            out.append(f"فایل‌های کاربر در ~ (یعنی /home/user) است؛ برای فرستادن فایلی که ساختی به کاربر، در جوابت بنویس "
                       f"MEDIA:/root/.hermes/profiles/{caller}/home/<مسیر بعد از ~>. برای خواندن/نوشتن فایل همیشه مسیر کامل /home/user/... بده، نه ~.")
            if not _build_allowed(caller):
                out.append("⛔ تو برنامه‌نویس نیستی: هیچ کد، ربات، سایت، اپ، رابط کاربری یا ابزار تازه‌ای نساز و برای ساختنش تلاش نکن؛ "
                           "فقط با امکانات آماده‌ی ایجنت هرمس کمک کن. اگر کاربر ساخت برنامه/ربات/اپ/سایت خواست، بگو «بله، به‌صورت سفارشی ساخته می‌شه؛ "
                           "برای قیمت و جزئیات به @your_support_account پیام بده» (این از خدمات ماست، نگو ممکن نیست و به پشتیبانی عمومی نفرست). "
                           "کانفیگ یا محتوای کانال‌های دیگران را برای کپی یا فروش پیشنهاد نکن.")
        return out
    return []


def _foreign(ch):
    """A LETTER that is neither Persian/Arabic nor Latin (Thai, CJK, Cyrillic, Devanagari, Hangul, Hebrew, …)."""
    import unicodedata
    if not unicodedata.category(ch).startswith("L"):
        return False
    o = ord(ch)
    return not (o < 0x250 or 0x600 <= o <= 0x6FF or 0x750 <= o <= 0x77F or 0x8A0 <= o <= 0x8FF or 0xFB50 <= o <= 0xFDFF
                or 0xFE70 <= o <= 0xFEFF or 0x1E00 <= o <= 0x1EFF)


_TRANSLATE_RE = re.compile(r"ترجمه|translate|چینی|ژاپنی|کره‌?ای|تایلندی|روسی|هندی|عبری|Chinese|Japanese|Korean|Thai|Russian|Hindi")


def _media_guard(t):
    """The gateway uploads host files named in MEDIA: tags. A sealed user's reply may only attach files from its OWN folder."""
    caller, _h = _caller_profile()
    if not caller or caller == "__owner__" or caller in OWNER_WORK:
        return None
    own = f"/root/.hermes/profiles/{caller}/"
    hits = re.findall(r"MEDIA:\s*(\S+)", t)
    bad = [m for m in hits if not os.path.realpath(m.strip("`'\"")).startswith(own)]
    if not bad:
        return None
    logger.warning("admin-panel MEDIA guard: removed %s from %s's reply", bad[:3], caller)
    for m in bad:
        t = re.sub(r"MEDIA:\s*" + re.escape(m), "(فایل خارج از پوشه‌ی کاربر — ارسال نشد)", t)
    return t


def _on_transform_llm_output(response_text=None, **_kw):
    t0 = response_text or ""
    g = _media_guard(t0) if "MEDIA:" in t0 else None
    r = _script_filter(g if g is not None else t0)
    return r if r is not None else g


def _script_filter(response_text=None):
    """Free fallback models sometimes switch language mid-reply (Chinese tokens, whole Thai lines «ถูกยกเลิก…»).
    Persian replies keep only Persian + Latin: foreign-script runs are removed, lines that were mostly foreign are dropped,
    and half-words glued to a removed run are cleaned up. Deliberate translations are left alone."""
    try:
        t = response_text or ""
        if not any(_foreign(ch) for ch in t):
            return None
        fa_letters = len(_FA_RE.findall(t))
        if fa_letters < 20 or _TRANSLATE_RE.search(t):
            return None                                   # not a Persian reply, or a requested translation
        out_lines, removed = [], 0
        for line in t.split("\n"):
            letters = [ch for ch in line if ch.isalpha()]
            bad = [ch for ch in letters if _foreign(ch)]
            if not bad:
                out_lines.append(line)
                continue
            removed += len(bad)
            if len(bad) > 0.3 * len(letters):             # a mostly-foreign line: drop it entirely
                continue
            cleaned = re.sub(r"\S*(" + "|".join(re.escape(ch) for ch in set(bad)) + r")\S*", "", line)   # word incl. glued half-word
            cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()
            if sum(1 for ch in cleaned if ch.isalpha()) >= 3:
                out_lines.append(cleaned)
        out = re.sub(r"\n{3,}", "\n\n", "\n".join(out_lines)).strip()
        logger.warning("admin-panel: removed %d foreign-script letters from a Persian reply", removed)
        return out or None
    except Exception:
        logger.warning("admin-panel script filter failed", exc_info=True)
        return None


_FA_NOTICES = {
    "Your request was not processed. Send it again if you still want me to carry it out.":
        "درخواستت انجام نشد. اگر هنوز لازم است، دوباره بفرست.",
    "This turn did not complete. Some actions may already have run; verify their effects before resending.":
        "این کار نیمه‌کاره ماند؛ ممکن است بخشی از آن انجام شده باشد. «ادامه بده» را بفرست تا نتیجه را بگویم.",
}


def _persian_failed_turn_notices():
    """Owner 2026-11-19: users saw English 'This turn did not complete…'. The notice is hard-coded upstream (no i18n key),
    so translate it at delivery only (the stored transcript row keeps the English text the core recognises)."""
    try:
        import gateway.run_turn as rt
        cls = rt.GatewayTurnMixin
        if getattr(cls, "_fa_notice_patched", False):
            return
        orig = cls._hmwa_add_failed_turn_notice

        def _add(self, response, notice):
            return orig(self, response, _FA_NOTICES.get(str(notice), notice))
        cls._hmwa_add_failed_turn_notice = _add
        cls._fa_notice_patched = True
    except Exception:
        logger.warning("admin-panel: could not localise failed-turn notice", exc_info=True)


def register(ctx) -> None:
    logger.warning("admin-panel registered (HERMES_HOME=%s)", os.environ.get("HERMES_HOME", "?"))
    _persian_failed_turn_notices()
    ctx.register_hook("pre_gateway_dispatch", _on_pre_gateway_dispatch)
    ctx.register_hook("pre_tool_call", _on_pre_tool_call)
    ctx.register_hook("pre_llm_call", _on_pre_llm_call)
    ctx.register_hook("transform_llm_output", _on_transform_llm_output)
