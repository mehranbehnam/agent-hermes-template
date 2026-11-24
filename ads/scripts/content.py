#!/usr/bin/python3
"""Content calendar for the HermesVPN channel/group (owner item 10). Posts are DRAFTS until Owner approves.

  content.py add "1405/08/05 10:30" "متن پست" [--target both|channel|group] [--poster auto|none|/path.jpg] [--sticker random|none|🎉]
  content.py list [--all]          # upcoming drafts/approved posts with ids
  content.py show <id>             # full text of one post
  content.py approve <id>|all      # Owner approved → will be published at its time
  content.py edit <id> "متن جدید"
  content.py remove <id>
  content.py publish-due           # post every approved item whose time has come (run every 10 min by cron)

Time: Tehran time, Jalali "1405/08/05 10:30" or Gregorian "2026-10-26 10:30".
Every text passes public_text_guard before it can be approved or published.
"""
import glob, os, sys, json, random, datetime, argparse, asyncio

_HPY = sorted(glob.glob("/root/.hermes/tools/python*/bin/python3"))[-1]
if os.path.realpath(sys.executable) != os.path.realpath(_HPY):
    os.execv(_HPY, [_HPY, os.path.abspath(__file__)] + sys.argv[1:])
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from public_text_guard import check as guard

FILE = "/root/.hermes/ads/content_calendar.json"
POSTERS = "/root/.hermes/ads/posters"
TZ = datetime.timezone(datetime.timedelta(hours=3, minutes=30))
TARGETS = {"both": ["your_channel", "your_group"], "channel": ["your_channel"], "group": ["your_group"]}


def load():
    try:
        return json.load(open(FILE))
    except Exception:
        return {"next_id": 1, "posts": []}


def save(d):
    json.dump(d, open(FILE, "w"), ensure_ascii=False, indent=1)


def parse_when(s):
    s = s.strip().translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
    date, _, tm = s.partition(" ")
    hh, mm = (tm or "10:00").split(":")[:2]
    y, m, d = [int(x) for x in date.replace("-", "/").split("/")]
    if y < 1700:
        from jalali import j2g
        y, m, d = j2g(y, m, d)
    return datetime.datetime(y, m, d, int(hh), int(mm), tzinfo=TZ).timestamp()


def fmt(ts):
    from jalali import fmt as jfmt
    return jfmt(datetime.datetime.fromtimestamp(ts, TZ))


def find(d, pid):
    for p in d["posts"]:
        if p["id"] == int(pid):
            return p
    sys.exit(f"پست #{pid} پیدا نشد")


async def publish(p):
    import send_sticker as ss
    from telethon import TelegramClient
    cr = json.load(open(ss.SESSION + ".creds.json"))
    c = TelegramClient(ss.SESSION, cr["api_id"], cr["api_hash"])
    await c.connect()
    poster = p.get("poster", "auto")
    if poster == "auto":
        files = sorted(glob.glob(os.path.join(POSTERS, "*.jpg")) + glob.glob(os.path.join(POSTERS, "*.png")))
        poster = random.choice(files) if files else "none"
    try:
        for t in TARGETS[p.get("target", "both")]:
            if poster != "none" and os.path.exists(poster) and len(p["text"]) <= 1024:
                await c.send_file(t, poster, caption=p["text"])
            else:
                await c.send_message(t, p["text"])
            if p.get("sticker", "random") != "none":
                await ss.send(c, t, p.get("sticker", "random"))
    finally:
        await c.disconnect()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["add", "list", "show", "approve", "edit", "remove", "publish-due"])
    ap.add_argument("a1", nargs="?")
    ap.add_argument("a2", nargs="?")
    ap.add_argument("--target", default="both", choices=list(TARGETS))
    ap.add_argument("--poster", default="auto")
    ap.add_argument("--sticker", default="random")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    d = load()
    if a.cmd == "add":
        probs = guard(a.a2 or "")
        if probs:
            sys.exit("متن رد شد (قفل متن عمومی): " + "; ".join(probs))
        p = {"id": d["next_id"], "when": parse_when(a.a1), "text": a.a2, "target": a.target, "poster": a.poster,
             "sticker": a.sticker, "status": "draft"}
        d["next_id"] += 1
        d["posts"].append(p)
        save(d)
        print(f"📝 پیش‌نویس #{p['id']} برای {fmt(p['when'])} ثبت شد (منتظر تأیید Owner)")
    elif a.cmd == "list":
        now = datetime.datetime.now(TZ).timestamp()
        rows = sorted([p for p in d["posts"] if a.all or p["status"] in ("draft", "approved")], key=lambda p: p["when"])
        icon = {"draft": "📝 پیش‌نویس", "approved": "✅ تأییدشده", "posted": "📤 منتشر شد", "failed": "⚠️ خطا"}
        print(f"🗓 تقویم محتوا ({len(rows)} پست):")
        for p in rows:
            late = " (زمانش گذشته)" if p["status"] == "draft" and p["when"] < now else ""
            print(f"#{p['id']} — {fmt(p['when'])} — {icon.get(p['status'], p['status'])}{late} — {p['target']} — {p['text'][:70].replace(chr(10), ' ')}")
    elif a.cmd == "show":
        p = find(d, a.a1)
        print(f"#{p['id']} — {fmt(p['when'])} — {p['status']} — مقصد: {p['target']} — پوستر: {p['poster']} — استیکر: {p['sticker']}\n\n{p['text']}")
    elif a.cmd == "approve":
        ids = [p["id"] for p in d["posts"] if p["status"] == "draft"] if a.a1 == "all" else [int(a.a1)]
        for pid in ids:
            p = find(d, pid)
            if guard(p["text"]):
                print(f"#{pid} رد شد: متن قفل عمومی را رد نمی‌کند")
                continue
            p["status"] = "approved"
        save(d)
        print(f"✅ تأیید شد: {', '.join('#' + str(i) for i in ids)} — سر وقتش منتشر می‌شود")
    elif a.cmd == "edit":
        p = find(d, a.a1)
        probs = guard(a.a2 or "")
        if probs:
            sys.exit("متن رد شد: " + "; ".join(probs))
        p["text"], p["status"] = a.a2, "draft"
        save(d)
        print(f"✏️ #{p['id']} ویرایش شد و دوباره پیش‌نویس است (تأیید لازم)")
    elif a.cmd == "remove":
        d["posts"] = [p for p in d["posts"] if p["id"] != int(a.a1)]
        save(d)
        print(f"🗑 #{a.a1} حذف شد")
    elif a.cmd == "publish-due":
        now = datetime.datetime.now(TZ).timestamp()
        for p in sorted(d["posts"], key=lambda p: p["when"]):
            if p["status"] == "approved" and p["when"] <= now and now - p["when"] < 6 * 3600:
                if guard(p["text"]):
                    p["status"] = "failed"
                    continue
                try:
                    asyncio.run(publish(p))
                    p["status"], p["posted_at"] = "posted", now
                    print(f"📤 #{p['id']} منتشر شد")
                except Exception as e:
                    p["status"], p["error"] = "failed", type(e).__name__
                    print(f"⚠️ #{p['id']} منتشر نشد: {type(e).__name__}")
                save(d)


if __name__ == "__main__":
    main()
