import glob, os, sys, asyncio, json, random
BASE = os.path.dirname(sorted(glob.glob("/root/.hermes/tools/python*/bin/python3"))[-1])
sys.path.insert(0, os.path.join(os.path.dirname(BASE), "lib", "python3.14", "site-packages"))
from telethon import TelegramClient

SESSION = "/root/.hermes/profiles/adsaccount/userbot/adsaccount"
STATE = "/root/.hermes/ads/state.json"

HEADLINES = [
    "🌐 اینترنت بدون مرز، بدون نگرانی\nHERMES VPN اتصال پایدار برای کار، درس، استریم و مرور روزانه.",
    "🔌 اتصال امن و پایدار، هر ساعت از روز\nسرورهای اروپا، بدون قطعی‌های آزاردهنده.",
    "🔒 داده‌های شما برای خودتان می‌ماند\nترافیک رمزنگاری‌شده و حریم خصوصی کامل.",
    "🚀 سرعتی که احساس می‌کنید\nتماشای روان، دانلود سریع، پینگ پایین.",
    "📱 یک اشتراک روی ۲ دستگاه\nنصب ساده روی اندروید، آیفون و ویندوز.",
    "⏳ زمان اکانت از اولین اتصال شروع می‌شه\nهر وقت آماده بودی وصل شو، یک روز هم هدر نمی‌ره.",
]

PRICES = ("پلن‌های ۳۰ روزه:\n• ۲۰ گیگ — ۶۰ هزار تومان\n• ۵۰ گیگ — ۱۰۰ هزار تومان\n"
          "• ۱۰۰ گیگ — ۱۵۰ هزار تومان\n• نامحدود — ۲۵۰ هزار تومان")
FOOTER = ("🧪 تست رایگان ۵۰۰ مگ / ۲۴ ساعت\n🎁 دوستت رو دعوت کن، ۱۰ گیگ رایگان بگیر\n\n"
          "خرید و پشتیبانی: @your_sales_bot")


async def main():
    try:
        state = json.load(open(STATE))
    except Exception:
        state = {"recent_headlines": [], "recent_posters": []}
    recent = state.get("recent_headlines", [])
    pool = [h for h in HEADLINES if h not in recent] or HEADLINES
    headline = random.choice(pool)
    state["recent_headlines"] = (recent + [headline])[-3:]
    caption = f"{headline}\n\n{PRICES}\n\n{FOOTER}"

    sys.path.insert(0, "/root/.hermes/ads/scripts")
    from public_text_guard import check as guard
    problems = guard(caption)
    if problems:
        print("BLOCKED by guard: " + "; ".join(problems))
        sys.exit(3)
    print("guard OK")

    with open(SESSION + ".creds.json") as f:
        creds = json.load(f)
    c = TelegramClient(SESSION, creds["api_id"], creds["api_hash"])
    await c.connect()
    me = await c.get_me()
    if not await c.is_user_authorized():
        print("ERROR: session not authorized")
        sys.exit(2)

    gr = await c.get_entity("your_group")
    before = [m.id async for m in c.iter_messages(gr, limit=1)][0]

    poster = "/root/.hermes/ads/posters/poster_referral_neon_v1.jpg"
    if os.path.exists(poster):
        m = await c.send_file(gr, poster, caption=caption)
        print(f"POSTER id={m.id} out={m.out} sender={m.sender_id} media={bool(m.media)}")
    else:
        m = await c.send_message(gr, caption)
        print(f"TEXT id={m.id} out={m.out} sender={m.sender_id} media={bool(m.media)}")

    try:
        sys.path.insert(0, "/root/.hermes/ads/scripts")
        from send_sticker import send as send_sticker
        await send_sticker(c, gr, "random")
        print("sticker sent")
    except Exception as e:
        print("sticker failed: " + str(e))

    after = [m.id async for m in c.iter_messages(gr, limit=1)][0]
    print(f"GROUP before={before} after={after} ok={after > before}")

    msgs = [m async for m in c.iter_messages(gr, limit=12)]
    msgs.reverse()
    for x in msgs:
        txt = (x.text or "").replace("\n", " ")[:60]
        print(f"  id={x.id} out={x.out} sender={x.sender_id} bot={getattr(x.sender,'bot',None)} media={bool(x.media)} | {txt}")

    await c.disconnect()
    json.dump(state, open(STATE, "w"), ensure_ascii=False, indent=1)

asyncio.run(main())
