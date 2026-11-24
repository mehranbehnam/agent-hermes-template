"""HermesVPN poster ads — one poster + an eye-catching caption + a big festive animated sticker, posted by the
Ads Account userbot to the channel and the group. Captions are built from rotating hooks / bodies / calls to
action so posts never look the same twice; posters and captions avoid recent repeats (state.json).

Campaigns (poster folder → caption pool):
  vpn       posters/            speed, stability, security, devices, support
  trial     posters-trial/      free trial 500 MB / 24 h (+10% first-purchase code after the trial)
  referral  posters-referral/   invite friends: friend +3 GB, you +10 GB, 3 invites = 50 GB account
  app       posters-app/        Android app HermesVPN Connect download
  agent     posters-agent/      Hermes Agent bot-building service
  new5      posters-new5/       5 fixed poster+caption pairs (N-name.jpg + N-name.txt, exact text, stable links),
                                round-robin in order; this is what --auto posts (3x a day since 2026-11-07)

  auto_ads.py                       # --auto: pick the campaign from Tehran time + day (the daily plan below)
  auto_ads.py --campaign trial      # a specific campaign now
  auto_ads.py --app | --agent       # shortcuts (old flags still work)
  auto_ads.py --only=your_channel       # one target only

Daily plan (Tehran): 10:30 vpn / trial (alternating days) · 16:30 app · 21:30 referral / vpn (alternating days).
"""
import glob, os, sys, asyncio, json, random, time, datetime

_HPY = sorted(glob.glob("/root/.hermes/tools/python*/bin/python3"))[-1]
if os.path.realpath(sys.executable) != os.path.realpath(_HPY):  # run with Hermes' own Python (telethon lives there)
    os.execv(_HPY, [_HPY, os.path.abspath(__file__)] + sys.argv[1:])
BASE = os.path.dirname(_HPY)
sys.path.insert(0, os.path.join(os.path.dirname(BASE), "lib", "python3.14", "site-packages"))
from telethon import TelegramClient
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from send_sticker import send as send_sticker
from public_text_guard import check as guard

ADS_DIR = "/root/.hermes/ads"
STATE = os.path.join(ADS_DIR, "state.json")
SESSION = "/root/.hermes/profiles/adsaccount/userbot/adsaccount"
TARGETS = ["your_channel", "your_group"]
TZ = datetime.timezone(datetime.timedelta(hours=3, minutes=30))
BOT = "@your_sales_bot"
# 2026-11-07 owner: every ad carries the stable (always-latest) Windows installer link
WIN_LINK = "https://app.example.com/app/HermesVPN-Connect-Setup.exe"
WIN_LINE = "💻 دانلود نسخه‌ی ویندوز: " + WIN_LINK

PRICES = ["💎 پلن‌های ۳۰ روزه:\n• ۲۰ گیگ — ۶۰ هزار تومان\n• ۵۰ گیگ — ۱۰۰ هزار تومان\n• ۱۰۰ گیگ — ۱۵۰ هزار تومان\n• نامحدود — ۲۵۰ هزار تومان",
          "💰 تعرفه‌ها (۳۰ روزه): ۲۰ گیگ ۶۰ | ۵۰ گیگ ۱۰۰ | ۱۰۰ گیگ ۱۵۰ | نامحدود ۲۵۰ هزار تومان",
          "🔥 از ۶۰ هزار تومان برای ۲۰ گیگ تا نامحدود ۲۵۰ هزار تومان — همه ۳۰ روزه، روی ۲ دستگاه"]

NEW5_DIR = os.path.join(ADS_DIR, "posters-new5")

CAMPAIGNS = {
    "owner12": {"dir": "posters-divar", "fixed": True, "hooks": [], "bodies": [], "ctas": [], "prices": False},
    "new5": {"dir": "posters-new5", "fixed": True, "hooks": [], "bodies": [], "ctas": [], "prices": False},
    "vpn": {
        "dir": "posters",
        "hooks": ["🚀 سرعت بی‌نظیر، اتصال بی‌وقفه!", "❓ خسته شدی از فیلترشکن‌هایی که هر ساعت قطع می‌شن؟", "⚡️ سرعتی که حسش می‌کنی",
                  "🌍 دنیا رو آزاد ببین", "🎮 گیمر یا اهل استریم؟", "🔐 امنیت و سرعت، با هم", "📱 یک اکانت، دو دستگاه",
                  "😮‍💨 دیگه لازم نیست هر روز دنبال کانفیگ بگردی", "🛰 سرور اختصاصی آلمان، فقط برای مشتری‌های هرمس"],
        "bodies": ["سرور اختصاصی آلمان، پینگ پایین و اتصال پایدار؛ فیلم ببین، بازی کن، کار کن — بدون قطعی.",
                   "HermesVPN با سرور اختصاصی و پشتیبانی واقعی، وصلت نگه می‌داره تا تو فقط از اینترنت لذت ببری.",
                   "یوتیوب بدون بافر، اینستاگرام بدون معطلی، بازی بدون لگ.",
                   "ترافیکت رمزنگاری می‌شه و اتصالت پایدار می‌مونه؛ گوشی و لپ‌تاپ رو هم‌زمان وصل کن.",
                   "زمان اکانت از اولین اتصال شروع می‌شه؛ یک روز هم هدر نمی‌ره.",
                   "اندروید، آیفون و ویندوز — نصب ساده، اتصال با یک لمس."],
        "ctas": [f"🛒 خرید آنی و تحویل خودکار: {BOT}", f"👈 همین الان از ربات {BOT} بخر و وصل شو",
                 f"🧪 اول تست رایگان بگیر، بعد تصمیم بگیر: {BOT}"],
        "prices": True,
    },
    "trial": {
        "dir": "posters-trial",
        "hooks": ["🧪 قبل از خرید امتحان کن — رایگان!", "🤔 مطمئن نیستی؟ ریسک نکن!", "🎯 ۲۴ ساعت مهمون هرمس باش",
                  "🆓 تست رایگان، بدون پرداخت، بدون شرط"],
        "bodies": ["۵۰۰ مگ / ۲۴ ساعت تست رایگان بگیر و سرعت و پایداری رو خودت بسنج.",
                   "با تست رایگان ۵۰۰ مگی فرق یه فیلترشکن حرفه‌ای رو حس کن.",
                   "تستت که تموم شد، اولین خریدت ۱۰٪ تخفیف داره 🎁"],
        "ctas": [f"👈 ربات {BOT} ← دکمه‌ی «🧪 تست»", f"🎁 تست رایگانت منتظرته: {BOT}"],
        "prices": False,
    },
    "referral": {
        "dir": "posters-referral",
        "hooks": ["🎁 دعوت کن، گیگ رایگان بگیر!", "👥 دوستات هم فیلترشکن خوب می‌خوان!", "🏆 چالش ۳ دعوت",
                  "💸 فیلترشکن رایگان می‌خوای؟", "🔗 لینک دعوتت = حجم رایگان", "🤝 هم به دوستت هدیه بده، هم خودت ببر",
                  "📲 یه لینک بفرست، ۱۰ گیگ بگیر"],
        "bodies": ["هر دوستی که با لینک تو بیاد و خرید کنه: اون ۳ گیگ هدیه می‌گیره، تو ۱۰ گیگ رایگان.",
                   "فقط ۳ نفر رو دعوت کن؛ یه اکانت ۵۰ گیگ یک‌ماهه جایزه بگیر.",
                   "با دعوت دوستات حجم رایگان جمع کن — محدودیتی برای تعداد دعوت نیست.",
                   "پوستر دعوتت رو با یک لمس برای دوستات بفرست؛ لینک اختصاصی خودت زیرشه.",
                   "لینک دعوت اختصاصیت رو از ربات بگیر و تو گروه‌ها و چت‌هات بفرست؛ هر خرید دوستت = ۱۰ گیگ برای تو."],
        "ctas": [f"👈 ربات {BOT} ← «🎁 دعوت دوستان (حجم رایگان)»", "👇 لینک دعوت اختصاصیت: t.me/your_sales_bot?start=invite"],
        "prices": False,
    },
    "app": {
        "dir": "posters-app",
        "hooks": ["📲 اپ اندروید HermesVPN اومد!", "⚡️ ساده‌ترین راه اتصال: اپ رسمی HermesVPN",
                  "🔄 همیشه آخرین نسخه، همیشه وصل", "👆 با یک لمس وصل شو", "🧩 دیگه لینک کپی نکن!"],
        "bodies": ["اکانتت خودش داخل اپ ثبت می‌شه؛ فقط دکمه‌ی اتصال رو بزن.",
                   "لینک اشتراک و نسخه‌های جدید رو اپ خودش مدیریت می‌کنه؛ تو فقط وصل شو.",
                   "سبک، سریع و سازگار با بیشتر گوشی‌های اندروید."],
        "ctas": [f"📥 دانلود رایگان: ربات {BOT} ← «📥 دانلود نرم‌افزار»\nیا مستقیم: app.example.com/open",
                 "📥 دانلود مستقیم: app.example.com/open"],
        "prices": False,
    },
    "creative": {
        "dir": "posters-creative",
        "hooks": ["🤔 یه سؤال صادقانه بپرسم؟", "😩 ➡️ 😎 فرقش فقط یه اتصاله", "💬 «کاش زودتر عوضش کرده بودم»",
                  "🆚 فیلترشکن رایگان یا هرمس؟", "🎬 وقت فیلمه، فیلترشکنت جا می‌زنه؟", "🧠 فیلترشکن خوب رو از بد چی جدا می‌کنه؟"],
        "bodies": ["فیلترشکن رایگان هر چند دقیقه قطع می‌شه؛ هرمس با سرور اختصاصی آلمان همون‌جا که لازمش داری وصل می‌مونه.",
                   "فرق یه اتصال پایدار با یه فیلترشکن قطع‌وصلی رو وقتی می‌فهمی که وسط فیلم یا بازی جا نزنه.",
                   "خیلی‌ها بعد از یه ماه استفاده می‌گن کاش زودتر عوضش کرده بودن؛ چون دیگه حتی یه بار قطع نشدن.",
                   "رایگان یعنی سرعت پایین، قطعی و احتمال نشت اطلاعات. هرمس یعنی پایدار، سریع و رمزنگاری‌شده با پشتیبانی واقعی."],
        "ctas": [f"🛒 خودت امتحانش کن: {BOT}", f"🧪 اول تست رایگان بگیر، بعد قضاوت کن: {BOT}",
                 f"👈 همین الان از ربات {BOT} وصل شو"],
        "prices": True,
    },
    "festival": {
        "dir": "posters-festival",
        "hooks": [], "bodies": [], "ctas": [f"🛒 همین الان از ربات {BOT} بخر یا تمدید کن"], "prices": False,
    },
    "agent": {
        "dir": "posters-agent",
        "hooks": ["🤖 ربات تلگرام اختصاصی با هوش مصنوعی", "⚡️ کارهای تکراری رو بسپار به ربات", "🚀 کسب‌وکارت رو رباتی کن"],
        "bodies": ["ربات فروش، پشتیبانی ۲۴ ساعته و مدیریت کانال و گروه — طراحی‌شده برای کسب‌وکار تو.",
                   "پاسخ خودکار به مشتری، ثبت سفارش، پرداخت و گزارش‌گیری.",
                   "Hermes Agent ربات هوشمند تلگرام می‌سازه؛ سریع، حرفه‌ای و اختصاصی."],
        "ctas": ["🤖 مشاوره و سفارش: @your_agent"],
        "prices": False,
    },
}


def load_state():
    try:
        return json.load(open(STATE))
    except Exception:
        return {}


def pick(st, key, items, keep):
    recent = st.get(key, [])
    pool = [x for x in items if x not in recent] or items
    choice = random.choice(pool)
    st[key] = (recent + [choice])[-keep:]
    return choice


SLOTS = ["referral", "festival", "vpn", "app", "referral", "festival", "creative", "trial"]


OWNER_DIR = os.path.join(ADS_DIR, "posters-divar")
# 2026-11-08 owner: channel + group use ONLY the owner's 12 posters (same set as @example_ad_group), chosen by situation.
# Slots (Tehran): 10:30 morning, 16:30 afternoon, 21:30 evening. Preferred posters per slot; fall back to any unused one.
SLOT_PREFS = {
    "morning": ["p02-plans", "p04-instant", "p10-trial", "p07-windows", "p11-support", "p09-wheel"],
    "afternoon": ["p01-apps", "p06-routes", "p08-invite", "p07-windows", "p09-wheel", "p12-speed"],
    "evening": ["p03-gaming-trade", "p12-speed", "p08-invite", "p01-apps", "p06-routes", "p04-instant"],
}
FESTIVAL = "p05-festival"


def sale_running():
    fs = sale_state()
    return fs if fs.get("pct", 0) and fs.get("until", 0) / 1000 > time.time() else None


def owner_pick(st, now):
    """(caption, poster) from the owner's 12. Festival poster only while the sale runs (2 of 3 slots, with the time
    left on top) or on Wednesday evening as the 'starts tonight' teaser; the other 11 rotate (each once per cycle,
    never twice in a row), preferring the ones that fit the time of day."""
    pool = {os.path.basename(p)[:-4]: p for p in glob.glob(os.path.join(OWNER_DIR, "p*.jpg")) if os.path.exists(p[:-4] + ".txt")}
    if not pool:
        sys.exit("no owner posters in " + OWNER_DIR)
    h = now.hour
    slot = "morning" if h < 13 else ("afternoon" if h < 19 else "evening")
    sale = sale_running()
    name = None
    if FESTIVAL in pool and ((sale and slot != "afternoon") or (not sale and now.weekday() == 2 and slot == "evening")):
        name = FESTIVAL
    if not name:
        rest = [n for n in sorted(pool) if n != FESTIVAL]
        left = [n for n in st.get("owner12_queue", []) if n in rest]
        if not left:
            left = rest[:]
        cand = [n for n in left if n != st.get("owner12_last")] or left
        pref = [n for n in SLOT_PREFS[slot] if n in cand]
        name = random.choice(pref or cand)
        st["owner12_queue"] = [n for n in left if n != name]
    st["owner12_last"] = name
    caption = open(pool[name][:-4] + ".txt", encoding="utf-8").read().strip()
    if name == FESTIVAL and sale:
        left_h = max(1, int((sale["until"] / 1000 - time.time()) // 3600))
        left_txt = (f"{left_h // 24} روز و {left_h % 24} ساعت" if left_h % 24 else f"{left_h // 24} روز") if left_h >= 24 else f"{left_h} ساعت"
        caption = f"⏰ جشنواره همین الان فعاله — فقط {left_txt} دیگه مونده!\n\n" + caption
    elif name == FESTIVAL:
        caption = "⏰ جشنواره از ساعت ۱ بامداد امشب شروع می‌شه!\n\n" + caption
    return caption, pool[name]


def auto_campaign(now):
    """2026-11-08 owner: only the owner's 12 posters, by situation (see owner_pick)."""
    return "owner12"


def auto_campaign_new5(now):
    """(old, unused since 2026-11-08) 2026-11-07 owner: 3 posts a day (cron 0 7,13,18 UTC = Tehran 10:30, 16:30, 21:30), the 5 new fixed ads in turn.
    While a festival sale runs (flash_sale_state.json until > now) every slot is a festival reminder with the time left."""
    fs = sale_state()
    if fs.get("pct", 0) and fs.get("until", 0) / 1000 > time.time():
        return "festival"
    return "new5"


def next_fixed(st):
    """Next poster+caption pair of posters-new5, in order, wrapping around."""
    pairs = sorted(p for p in glob.glob(os.path.join(NEW5_DIR, "*.jpg")) if os.path.exists(p[:-4] + ".txt"))
    if not pairs:
        sys.exit("no poster+caption pairs in " + NEW5_DIR)
    i = st.get("new5_next", 0) % len(pairs)
    st["new5_next"] = i + 1
    poster = pairs[i]
    return open(poster[:-4] + ".txt", encoding="utf-8").read().strip(), poster


def auto_campaign_8x(now):
    """(old, unused since 2026-11-07) 8 posts a day (Tehran 09:30, 11:30 … 23:30): 2× invite link, 2× weekend festival, then vpn/app/creative/trial."""
    slot = max(0, min(7, (now.astimezone(datetime.timezone.utc).hour - 6) // 2))
    camp = SLOTS[slot]
    if camp == "vpn" and now.toordinal() % 2:
        camp = "agent" if now.toordinal() % 4 == 1 else "vpn"
    return camp


def sale_state():
    """The festival as the sales bot sees it (source of truth: oracle settings key flash_sale, the same value
    that prices the invoices); falls back to the local flash_sale_state.json if oracle can't be reached."""
    try:
        from flash_sale import remote_setting
        v = json.loads(remote_setting(None) or "{}")
        if isinstance(v, dict):
            return v
    except BaseException as e:                       # remote_setting sys.exit()s on ssh failure
        print(f"sales bot flash_sale unreadable, using local state: {e}")
    try:
        return json.load(open(os.path.join(ADS_DIR, "flash_sale_state.json")))
    except Exception as e:
        print(f"flash_sale_state unreadable: {e}")
        return {}


def festival_caption():
    """Truthful festival copy: live discount while the weekend sale runs, otherwise the weekly schedule."""
    st = sale_state()
    until = st.get("until", 0) / 1000
    if until > time.time():
        end = datetime.datetime.fromtimestamp(until, TZ)
        left_h = max(1, int((until - time.time()) // 3600))
        left_txt = (f"{left_h // 24} روز و {left_h % 24} ساعت" if left_h % 24 else f"{left_h // 24} روز") if left_h >= 24 else f"{left_h} ساعت"
        hook = random.choice([f"🔥 جشنواره فعاله! {st.get('pct', 20)}٪ تخفیف", f"⏰ فقط {left_txt} دیگه از جشنواره مونده",
                              f"🎉 {st.get('pct', 20)}٪ تخفیف روی همه‌ی پلن‌ها و تمدیدها — همین حالا"])
        if end.hour == 0 and end.minute <= 5:                 # weekend sale ends 00:00 -> "تا آخر جمعه"
            end -= datetime.timedelta(minutes=end.minute + 1)
            when = "آخر "
        else:
            when = ""
        today = datetime.datetime.now(TZ).date()
        day = "امروز" if end.date() == today else ("فردا" if end.date() == today + datetime.timedelta(days=1)
                                                   else ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه"][end.weekday()])
        when = f"آخر {day}" if when else f"{day} ساعت {end.strftime('%H:%M')}"
        body = (f"💥 {st.get('pct', 20)}٪ تخفیف روی همه‌ی پلن‌ها و تمدیدها، فقط تا {when} ({left_txt} مونده).\n"
                "تخفیف خودکار روی فاکتورت در ربات اعمال می‌شه؛ فقط پلنت رو انتخاب کن.")
    else:
        hook = random.choice(["🎉 جشنواره‌ی آخر هفته‌ی HermesVPN", "📅 پنجشنبه و جمعه یادت نره!", "💥 هر آخر هفته ۲۰٪ تخفیف"])
        body = ("هر هفته از ساعت ۱ بامداد پنجشنبه تا ساعت ۱ بامداد شنبه (۴۸ ساعت)، ۲۰٪ تخفیف خودکار روی همه‌ی پلن‌ها و تمدیدها.\n"
                "تمدیدت رو بذار برای آخر هفته و ارزون‌تر بخر 😉")
    return hook, body


def auto_campaign_unused(now):
    day_even = now.toordinal() % 2 == 0
    if now.hour < 13:
        return "vpn" if day_even else "trial"
    if now.hour < 19:
        return "app"
    return "referral" if day_even else "vpn"


def build_caption(camp, st):
    c = CAMPAIGNS[camp]
    if camp == "festival":
        hook, body = festival_caption()
    else:
        hook = pick(st, f"{camp}_hooks", c["hooks"], max(1, len(c["hooks"]) - 2))
        body = pick(st, f"{camp}_bodies", c["bodies"], max(1, len(c["bodies"]) - 1))
    cta = pick(st, f"{camp}_ctas", c["ctas"], max(1, len(c["ctas"]) - 1))
    parts = [hook, body]
    if c["prices"]:
        parts.append(random.choice(PRICES))
    parts.append(cta)
    if camp not in ("trial", "agent") and random.random() < 0.5:
        parts.append("🧪 تست رایگان ۵۰۰ مگ / ۲۴ ساعت" if camp != "referral" else "🧪 هنوز امتحان نکردی؟ تست رایگان داریم")
    if camp not in ("app", "agent"):
        parts.append("📥 اپ اندروید HermesVPN: app.example.com/open")
    if camp != "agent":
        parts.append(WIN_LINE)
    return "\n\n".join(parts), hook


async def main():
    args = sys.argv[1:]
    camp = None
    for a in args:
        if a.startswith("--campaign="):
            camp = a.split("=", 1)[1]
    if "--campaign" in args:
        camp = args[args.index("--campaign") + 1]
    if "--app" in args:
        camp = "app"
    if "--agent" in args:
        camp = "agent"
    if camp is None:
        camp = auto_campaign(datetime.datetime.now(TZ))
    if camp not in CAMPAIGNS:
        sys.exit(f"unknown campaign {camp}; use one of {list(CAMPAIGNS)}")
    targets = [a.split("=", 1)[1] for a in args if a.startswith("--only=")] or TARGETS

    st = load_state()
    fixed_poster = None
    if camp == "owner12":
        caption, fixed_poster = owner_pick(st, datetime.datetime.now(TZ))
        hook = os.path.basename(fixed_poster)
    elif CAMPAIGNS[camp].get("fixed"):
        caption, fixed_poster = next_fixed(st)
        if WIN_LINK not in caption:
            caption = caption.replace("\n📢 @your_channel", "\n" + WIN_LINE + "\n📢 @your_channel") if "\n📢 @your_channel" in caption else caption + "\n\n" + WIN_LINE
        hook = os.path.basename(fixed_poster)
    else:
        caption, hook = build_caption(camp, st)
    problems = guard(caption)
    if problems:
        print("BLOCKED by public text guard (nothing sent): " + "; ".join(problems))
        sys.exit(3)
    pdir = os.path.join(ADS_DIR, CAMPAIGNS[camp]["dir"])
    posters = sorted(glob.glob(os.path.join(pdir, "*.jpg")) + glob.glob(os.path.join(pdir, "*.png")))
    poster = fixed_poster
    if posters and not poster:
        names = [os.path.basename(p) for p in posters]
        poster = os.path.join(pdir, pick(st, f"{camp}_posters", names, max(1, len(names) // 2)))

    with open(SESSION + ".creds.json") as f:
        creds = json.load(f)
    c = TelegramClient(SESSION, creds["api_id"], creds["api_hash"])
    await c.connect()
    if not await c.is_user_authorized():
        print("ERROR: userbot session not authorized")
        sys.exit(2)
    sent = []
    for t in targets:
        try:
            ent = await c.get_entity(t)
            if poster:
                await c.send_file(ent, poster, caption=caption)
            else:
                await c.send_message(ent, caption)
            sent.append(t)
            try:
                await send_sticker(c, ent, "random")
            except Exception as e:
                print(f"sticker to {t} failed: {e}")
        except Exception as e:
            print(f"ERROR sending to {t}: {e}")
    await c.disconnect()
    st["last_run"] = int(time.time())
    st["last_campaign"] = camp
    json.dump(st, open(STATE, "w"), ensure_ascii=False, indent=1)
    print(f"[{camp}] sent to {sent} poster={os.path.basename(poster) if poster else None} hook={hook}")
    if not sent:
        sys.exit(1)


asyncio.run(main())
