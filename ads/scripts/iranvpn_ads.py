"""IranVPN (ایران‌وی‌پی‌ان — برای ایرانیان خارج از کشور) poster/text ads, posted by the adsaccount2 userbot
(same Owner account, separate session) to @your_second_channel + @your_second_group. Rotating hooks/bodies/CTAs +
a festive animated sticker, like auto_ads.py but with IranVPN-for-Turkey content and لیر pricing.

  iranvpn_ads.py [--campaign iran|stream|price|trial|invite] [--only=your_second_channel]
  (no flag = auto campaign by Tehran time/day)
"""
import glob, os, sys, asyncio, json, random, time, datetime

_HPY = sorted(glob.glob("/root/.hermes/tools/python*/bin/python3"))[-1]
if os.path.realpath(sys.executable) != os.path.realpath(_HPY):
    os.execv(_HPY, [_HPY, os.path.abspath(__file__)] + sys.argv[1:])
BASE = os.path.dirname(_HPY)
sys.path.insert(0, os.path.join(os.path.dirname(BASE), "lib", "python3.14", "site-packages"))
from telethon import TelegramClient
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from send_sticker import send as send_sticker, BIG_PACKS
from public_text_guard import check as guard

ADS_DIR = "/root/.hermes/ads/iranvpn"
POSTERS = os.path.join(ADS_DIR, "posters")
STATE = os.path.join(ADS_DIR, "state.json")
SESSION = "/root/.hermes/profiles/adsaccount2/userbot/adsaccount2"
TARGETS = ["your_second_channel", "iranvpngroup"]
TZ = datetime.timezone(datetime.timedelta(hours=3, minutes=30))
BOT = "@your_second_sales_bot"

PRICES = ["💎 پلن‌های ۳۰ روزه:\n• ۲۰ گیگ — ۱۴۹ لیر\n• ۵۰ گیگ — ۲۴۹ لیر\n• نامحدود — ۵۴۹ لیر",
          "💰 تعرفه (۳۰ روزه): ۲۰ گیگ ۱۴۹ | ۵۰ گیگ ۲۴۹ | نامحدود ۵۴۹ لیر"]

CAMPAIGNS = {
    "iran": {
        "hooks": ["🇮🇷 ایرانی و خارج از ایران؟ به اینترنت ایران وصل شو!",
                  "🏦 بانک و اپ‌های ایرانی از خارج باز نمی‌شن؟ حلش کردیم!",
                  "📲 اپ‌های ایرانی رو با آی‌پی ایران باز کن", "🌐 انگار توی ایرانی!"],
        "bodies": ["با IranVPN یه آی‌پی ثابت ایران داری؛ بانک، اسنپ، دیجی‌کالا و اپ‌های ایرانی از هر جای دنیا بی‌دردسر باز می‌شن.",
                   "سایت‌ها و سرویس‌های ایرانی که از خارج بسته‌ان، با IranVPN مثل داخل ایران باز می‌شن.",
                   "آی‌پی ثابت ایران + دسترسی به اینترنت آزاد جهانی، هر دو توی یک اپ."],
        "ctas": [f"🛒 خرید و تست: {BOT}", f"👈 همین الان از ربات {BOT} وصل شو"],
        "prices": True,
    },
    "stream": {
        "hooks": ["🎬 فیلم و سریال ایرانی از هر جای دنیا، بدون محدودیت!", "📺 آوامووی و زرفیلم باز نمی‌شه؟",
                  "🍿 دلت برای سریال‌های ایرانی تنگ شده؟"],
        "bodies": ["با IranVPN آوامووی، زرفیلم و پلتفرم‌های ایرانی از هر جای دنیا روان باز می‌شن.",
                   "آی‌پی ایران داری، پس استریم ایرانی بدون «در کشور شما در دسترس نیست»."],
        "ctas": [f"🎬 شروع تماشا: {BOT}", f"👈 ربات {BOT}"],
        "prices": True,
    },
    "price": {
        "hooks": ["🔥 کیفیت بالا، قیمت منصفانه", "⚡️ اتصال پایدار IranVPN برای ایرانیان خارج از کشور"],
        "bodies": ["سرور ایران + رله‌ی اروپا؛ هم به اینترنت ایران وصلی هم به اینترنت آزاد جهان.",
                   "اتصال پایدار و پشتیبانی واقعی، مخصوص ایرانیان خارج از کشور."],
        "ctas": [f"🛒 خرید آنی: {BOT}"],
        "prices": True,
    },
    "trial": {
        "hooks": ["🧪 اول تست کن، بعد بخر — رایگان!", "🆓 بدون پرداخت امتحانش کن"],
        "bodies": ["تست رایگان بگیر و خودت کیفیت اتصال به اینترنت ایران از خارج رو بسنج.",
                   "مطمئن نیستی؟ تست رایگان IranVPN رو امتحان کن."],
        "ctas": [f"👈 ربات {BOT} ← «تست رایگان»"],
        "prices": False,
    },
    "invite": {
        "hooks": ["🎁 دوستاتو دعوت کن، حجم رایگان بگیر!", "👥 دوستای ایرانیت خارج از ایران هم به IranVPN نیاز دارن"],
        "bodies": ["هر دوستی با لینک دعوت تو بیاد و خرید کنه، هر دوتون هدیه می‌گیرید.",
                   "لینک دعوتت رو بفرست و حجم رایگان جمع کن."],
        "ctas": [f"👈 ربات {BOT} ← بخش دعوت دوستان"],
        "prices": False,
    },
    "creative": {
        "hooks": ["🤔 یه سؤال برای ایرانیِ خارج از کشور…", "😩 ➡️ 😎 فرقش یه آی‌پی ایرانه",
                  "💬 «از ترکیه بالاخره بانکم رو باز کردم»", "🆚 فیلترشکن معمولی یا IranVPN؟",
                  "🏦 چرا به بانک ایران وصل نمی‌شی؟"],
        "bodies": ["فیلترشکن معمولی فقط اینترنت آزاد خارج رو می‌ده؛ IranVPN آی‌پی ثابت ایران می‌ده تا بانک و اپ‌های ایرانی هم باز شن.",
                   "از خارج، سایت‌ها و اپ‌های ایرانی بسته‌ان. با آی‌پی ثابت ایرانِ IranVPN انگار توی تهرانی.",
                   "خیلی از ایرانی‌های خارج از کشور می‌گن کاش زودتر عوضش می‌کردن؛ بانک، آوامووی و زرفیلم بی‌دردسر باز می‌شه.",
                   "هم آی‌پی ایران برای سرویس‌های داخلی، هم اینترنت آزاد جهانی — هر دو توی یک اپ."],
        "ctas": [f"🛒 خودت امتحانش کن: {BOT}", f"🧪 اول تست رایگان بگیر، بعد قضاوت کن: {BOT}",
                 f"👈 همین الان از ربات {BOT} وصل شو"],
        "prices": True,
    },
    "app": {
        "hooks": ["📲 اپ اندروید IranVPN اومد!", "👆 با یک لمس به اینترنت ایران وصل شو",
                  "🔄 اپ رسمی: همیشه آخرین نسخه، همیشه وصل"],
        "bodies": ["اکانتت داخل اپ ثبت می‌شه؛ فقط دکمه‌ی اتصال رو بزن و به سرویس‌های ایران و اینترنت آزاد وصل شو.",
                   "دیگه لینک کپی نکن؛ اپ خودش اشتراک و نسخه‌ی جدید رو مدیریت می‌کنه.",
                   "سبک و سازگار با بیشتر گوشی‌های اندروید؛ روی آیفون هم با V2Box وصل شو."],
        "ctas": ["📥 دانلود رایگان: app.example.com/open", f"📥 دانلود از ربات {BOT} ← «دانلود نرم‌افزار»"],
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
    ch = random.choice(pool)
    st[key] = (recent + [ch])[-keep:]
    return ch


def auto_campaign(now):
    order = ["iran", "stream", "app", "price", "trial", "invite", "iran", "app"]
    return order[(now.toordinal() * 3 + now.hour // 8) % len(order)]


def build(camp, st):
    c = CAMPAIGNS[camp]
    hook = pick(st, f"{camp}_h", c["hooks"], max(1, len(c["hooks"]) - 1))
    body = pick(st, f"{camp}_b", c["bodies"], max(1, len(c["bodies"]) - 1))
    cta = pick(st, f"{camp}_c", c["ctas"], max(1, len(c["ctas"]) - 1))
    parts = [hook, body]
    if c["prices"]:
        parts.append(random.choice(PRICES))
    parts.append(cta)
    if camp not in ("trial",) and random.random() < 0.5:
        parts.append("🧪 تست رایگان هم داریم — قبل از خرید امتحان کن.")
    if camp != "app":
        parts.append("📥 اپ اندروید: app.example.com/open")
    return "\n\n".join(parts), hook


async def main():
    args = sys.argv[1:]
    camp = None
    for a in args:
        if a.startswith("--campaign="):
            camp = a.split("=", 1)[1]
    if "--campaign" in args:
        camp = args[args.index("--campaign") + 1]
    if camp is None:
        camp = auto_campaign(datetime.datetime.now(TZ))
    if camp not in CAMPAIGNS:
        sys.exit(f"unknown campaign {camp}; {list(CAMPAIGNS)}")
    targets = [a.split("=", 1)[1] for a in args if a.startswith("--only=")] or TARGETS
    st = load_state()
    caption, hook = build(camp, st)
    if guard(caption):
        print("BLOCKED by guard: " + "; ".join(guard(caption)))
        sys.exit(3)
    POSTER_FOR = {"iran": "iran_access", "stream": "streaming", "trial": "trial", "price": "price", "invite": "iran_access", "app": "app_ir"}
    poster = None
    if camp == "creative":
        cdir = os.path.join(ADS_DIR, "posters-creative")
        cp = sorted(glob.glob(os.path.join(cdir, "*.jpg")) + glob.glob(os.path.join(cdir, "*.png")))
        if cp:
            names = [os.path.basename(p) for p in cp]
            poster = os.path.join(cdir, pick(st, "creative_poster", names, max(1, len(names) - 1)))
    else:
        posters = sorted(glob.glob(os.path.join(POSTERS, "*.jpg")) + glob.glob(os.path.join(POSTERS, "*.png")))
        if posters:
            match = [p for p in posters if POSTER_FOR.get(camp, "") in os.path.basename(p)]
            if match:
                poster = match[0]
            else:
                names = [os.path.basename(p) for p in posters]
                poster = os.path.join(POSTERS, pick(st, f"{camp}_poster", names, max(1, len(names) // 2)))
    cr = json.load(open(SESSION + ".creds.json"))
    c = TelegramClient(SESSION, cr["api_id"], cr["api_hash"])
    await c.connect()
    if not await c.is_user_authorized():
        print("ERROR: adsaccount2 session not authorized")
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
                await send_sticker(c, ent, "random", BIG_PACKS)
            except Exception as e:
                print(f"sticker to {t} failed: {e}")
        except Exception as e:
            print(f"ERROR sending to {t}: {e}")
    await c.disconnect()
    st["last_run"] = int(time.time())
    st["last_campaign"] = camp
    os.makedirs(ADS_DIR, exist_ok=True)
    json.dump(st, open(STATE, "w"), ensure_ascii=False, indent=1)
    print(f"[{camp}] sent to {sent} poster={os.path.basename(poster) if poster else None} hook={hook}")
    if not sent:
        sys.exit(1)


asyncio.run(main())
