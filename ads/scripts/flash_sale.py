#!/usr/bin/python3
"""Festival / flash sale + «❤️ heart challenge» (owner items 2 and 4).

  flash_sale.py start [--pct 20] [--hours 36] [--reason weekend|hearts|manual]   # turn the sale on + announce
  flash_sale.py stop | status
  flash_sale.py challenge [--goal 10]        # post «❤️ N hearts → 24 h festival» in the channel (Monday job)
  flash_sale.py check-challenge              # called by the live monitor: goal reached -> start a 24 h sale

The discount lives in the sales bot (settings key flash_sale) and is applied automatically to every single
purchase and renewal until it expires. Announcements go to the channel + group (userbot), poster + big sticker.
"""
import glob, os, sys, json, time, argparse, asyncio, subprocess, datetime

_HPY = sorted(glob.glob("/root/.hermes/tools/python*/bin/python3"))[-1]
if os.path.realpath(sys.executable) != os.path.realpath(_HPY):
    os.execv(_HPY, [_HPY, os.path.abspath(__file__)] + sys.argv[1:])
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from public_text_guard import check as guard

STATE = "/root/.hermes/ads/flash_sale_state.json"
POSTER = "/root/.hermes/ads/posters-divar/p05-festival.jpg"   # 2026-11-08 owner: only his own posters
TZ = datetime.timezone(datetime.timedelta(hours=3, minutes=30))


def remote_setting(value):
    """write/read the sales bot setting over ssh (value None = read)"""
    code = ("import sqlite3,sys,json;c=sqlite3.connect('/root/.hermes-orders.db');"
            "c.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)');"
            + ("c.execute(\"INSERT INTO settings VALUES ('flash_sale',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value\",(sys.argv[1],));c.commit();print('ok')"
               if value is not None else
               "r=c.execute(\"SELECT value FROM settings WHERE key='flash_sale'\").fetchone();print(r[0] if r else '{}')"))
    args = ["ssh", "-o", "BatchMode=yes", "oracle-vpn", "sudo", "python3", "-c", json.dumps(code)]
    if value is not None:
        args.append(json.dumps(json.dumps(value)))
    r = subprocess.run(args, capture_output=True, text=True, timeout=60)
    if r.returncode:
        sys.exit("sales bot update failed: " + r.stderr[-200:])
    return r.stdout.strip()


async def post(text, poster=POSTER, targets=("your_channel", "your_group"), sticker="🎉"):
    import send_sticker as ss
    from telethon import TelegramClient
    if guard(text):
        sys.exit("blocked by guard: " + "; ".join(guard(text)))
    cr = json.load(open(ss.SESSION + ".creds.json"))
    c = TelegramClient(ss.SESSION, cr["api_id"], cr["api_hash"])
    await c.connect()
    ids = {}
    try:
        for t in targets:
            m = await c.send_file(t, poster, caption=text) if poster and os.path.exists(poster) else await c.send_message(t, text)
            ids[t] = m.id
            await ss.send(c, t, sticker, ss.BIG_PACKS)
    finally:
        await c.disconnect()
    return ids


def fmt_until(ms):
    d = datetime.datetime.fromtimestamp(ms / 1000, TZ)
    from jalali import fmt
    return fmt(d)


def next_sat_0100_ms():
    """Weekend festival end (owner 2026-11-08): Saturday 01:00 Tehran = Friday 21:30 UTC."""
    now = datetime.datetime.now(TZ)
    d = now + datetime.timedelta(days=(5 - now.weekday()) % 7)
    end = d.replace(hour=1, minute=0, second=0, microsecond=0)
    if end <= now:
        end += datetime.timedelta(days=7)
    return int(end.timestamp() * 1000)


def start(pct, hours, reason):
    until = int((time.time() + hours * 3600) * 1000)
    if reason == "weekend":                      # fixed window Thu 01:00 -> Sat 01:00 Tehran, same value oracle's timer sets
        until = next_sat_0100_ms()
    try:                                         # never shorten/lower a sale that is already running (oracle timer may be first)
        cur = json.loads(remote_setting(None) or "{}")
        if cur.get("until", 0) > time.time() * 1000 and int(cur.get("pct", 0)) >= pct and cur["until"] >= until:
            pct, until = int(cur["pct"]), int(cur["until"])
    except Exception as e:
        print(f"could not read the running sale, setting ours: {e}")
    remote_setting({"pct": pct, "until": until, "reason": reason})
    headline = {"weekend": "🎉 جشنواره‌ی آخر هفته‌ی HermesVPN شروع شد!",
                "hearts": "❤️ به هدف قلب‌ها رسیدیم — جشنواره فعال شد!",
                "manual": "🔥 جشنواره‌ی ویژه‌ی HermesVPN!"}.get(reason, "🔥 جشنواره‌ی ویژه‌ی HermesVPN!")
    text = (f"{headline}\n\n"
            f"💥 {pct}٪ تخفیف روی همه‌ی پلن‌ها و تمدیدها\n"
            f"⏰ فقط تا {fmt_until(until)} (به وقت تهران)\n\n"
            f"• ۲۰ گیگ ← {int(60000 * (100 - pct) / 100):,} تومان\n"
            f"• ۵۰ گیگ ← {int(100000 * (100 - pct) / 100):,} تومان\n"
            f"• ۱۰۰ گیگ ← {int(150000 * (100 - pct) / 100):,} تومان\n"
            f"• نامحدود ← {int(250000 * (100 - pct) / 100):,} تومان\n\n"
            "تخفیف خودکار اعمال می‌شه، فقط پلنت رو انتخاب کن 👇\n🛒 @your_sales_bot"
            "\n\n💻 دانلود نسخه‌ی ویندوز: https://app.example.com/app/HermesVPN-Connect-Setup.exe")
    ids = asyncio.run(post(text))
    json.dump({"pct": pct, "until": until, "reason": reason, "posts": ids}, open(STATE, "w"))
    print(f"✅ جشنواره {pct}٪ تا {fmt_until(until)} فعال شد و اعلام شد")


def challenge(goal):
    text = (f"❤️ چالش قلب‌ها!\n\nاگه این پست به {goal} تا ❤️ برسه، ۲۴ ساعت جشنواره‌ی ۲۰٪ تخفیف "
            "روی همه‌ی پلن‌ها و تمدیدها فعال می‌شه 🎉\n\nقلب بذار و کانال رو برای دوستات بفرست تا زودتر برسیم 👇\n@your_channel")
    ids = asyncio.run(post(text, targets=("your_channel",), sticker="❤"))
    st = {}
    if os.path.exists(STATE):
        st = json.load(open(STATE))
    st["challenge"] = {"msg_id": ids["your_channel"], "goal": goal, "done": False, "ts": int(time.time())}
    json.dump(st, open(STATE, "w"))
    print(f"❤️ چالش قلب‌ها با هدف {goal} در کانال منتشر شد")


def check_challenge():
    if not os.path.exists(STATE):
        return
    st = json.load(open(STATE))
    ch = st.get("challenge")
    if not ch or ch.get("done") or time.time() - ch["ts"] > 6 * 86400:
        return
    import chan_stats as cs

    async def count():
        c = await cs.client()
        try:
            m = await c.get_messages("your_channel", ids=ch["msg_id"])
            return sum(r.count for r in m.reactions.results) if m and m.reactions else 0
        finally:
            await c.disconnect()
    n = asyncio.run(count())
    if n >= ch["goal"]:
        ch["done"] = True
        json.dump(st, open(STATE, "w"))
        start(20, 24, "hearts")
        st = json.load(open(STATE))
        st["challenge"] = ch
        json.dump(st, open(STATE, "w"))
    else:
        print(f"challenge: {n}/{ch['goal']}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["start", "stop", "status", "challenge", "check-challenge"])
    ap.add_argument("--pct", type=int, default=20)
    ap.add_argument("--hours", type=float, default=36)
    ap.add_argument("--reason", default="manual")
    ap.add_argument("--goal", type=int, default=10)
    a = ap.parse_args()
    if a.cmd == "start":
        start(a.pct, a.hours, a.reason)
    elif a.cmd == "stop":
        remote_setting({"pct": 0, "until": 0})
        st = json.load(open(STATE)) if os.path.exists(STATE) else {}
        st.update({"pct": 0, "until": 0})
        json.dump(st, open(STATE, "w"))
        print("⏹ جشنواره متوقف شد")
    elif a.cmd == "status":
        v = json.loads(remote_setting(None) or "{}")
        on = v.get("until", 0) > time.time() * 1000
        print(f"{'✅ فعال' if on else '⏸ غیرفعال'}" + (f" — {v['pct']}٪ تا {fmt_until(v['until'])}" if on else ""))
    elif a.cmd == "challenge":
        challenge(a.goal)
    elif a.cmd == "check-challenge":
        check_challenge()


if __name__ == "__main__":
    main()
