#!/usr/bin/python3
"""Ad-exchange / paid-ad outreach engine for HERMES VPN — finds Persian channels at scale and prepares
consent-based outreach. SENDING a proposal always goes to a channel's ADMIN (never auto-posting ads inside
other people's channels), is capped per day, and runs only when Owner asks — so the account stays safe.

  partners.py discover [--min 300 --max 200000] [--deep]   # wide auto-discovery (name search + mention snowball)
  partners.py list [--status new|queued|sent|accepted|rejected] [--limit 60]
  partners.py draft <@channel>                             # tailored Persian proposal for that channel's admin
  partners.py queue <@channel|all-open|top N>              # mark channels to contact (Owner reviews the list)
  partners.py send [--max 15]                              # send proposals to QUEUED channels' admins (cap/day)
  partners.py mark <@channel> accepted|rejected|skip
  partners.py stats                                        # funnel: discovered / queued / sent / accepted

Auto-discovery may run on a schedule (safe — it only reads). Auto-SEND never runs on a schedule.
"""
import glob, os, sys, asyncio, json, re, datetime, argparse, random

_HPY = sorted(glob.glob("/root/.hermes/tools/python*/bin/python3"))[-1]
if os.path.realpath(sys.executable) != os.path.realpath(_HPY):
    os.execv(_HPY, [_HPY, os.path.abspath(__file__)] + sys.argv[1:])
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import chan_stats as cs
from telethon import functions, types, errors

# PT_* env lets IranVPN reuse this with its own userbot + brand (separate candidate file).
FILE = os.environ.get("PT_FILE", "/root/.hermes/ads/partners.json")
SESSION = os.environ.get("PT_SESSION", "/root/.hermes/profiles/adsaccount/userbot/adsaccount")
OURS = set(os.environ.get("PT_OURS", "your_channel,your_group,your_sales_bot,your_agent_bot").split(","))
BRAND_LINE = os.environ.get("PT_BRAND_LINE",
    "من از طرف HERMES VPN (@your_channel) هستم؛ فیلترشکن پرسرعت با سرور اختصاصی آلمان.")
SEND_CAP_DEFAULT = 5                       # proposals per day — cold DMs to strangers are the top ban-risk, keep tiny
GAP = (150, 300)                           # 2.5-5 min between cold DMs
# audiences whose members plausibly need a VPN
KEYWORDS = ["فیلترشکن", "وی پی ان", "کانفیگ", "v2ray", "اینترنت آزاد", "پروکسی", "تانل",
            "ترفند تلگرام", "ترفند اینستاگرام", "ترفند موبایل", "تکنولوژی", "اپلیکیشن", "بازی موبایل", "گیم",
            "دانلود فیلم", "سریال", "موزیک", "آموزش کامپیوتر", "هوش مصنوعی", "ارز دیجیتال", "دانشجو",
            "استخدام", "تخفیف", "فروشگاه", "دانلود", "کریپتو", "بیت کوین", "فارکس"]
NEG = re.compile(r"ممنوع|فروش ممنوع|تبادل نمی|تبلیغات نمی|کانال شخصی", re.I)
OPEN = re.compile(r"تبادل|تبلیغات|رزرو تبلیغ|ثبت سفارش تبلیغ|ads|promotion|sponsor", re.I)
ADMIN = re.compile(r"(?:ادمین|مدیر|ارتباط|سفارش تبلیغ|تبادل|پشتیبانی|admin|pv|پیوی)\D{0,20}@([A-Za-z]\w{3,31})", re.I)
FA = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def load():
    try:
        return json.load(open(FILE))
    except Exception:
        return {"chans": {}, "sent_log": []}


def save(d):
    json.dump(d, open(FILE, "w"), ensure_ascii=False, indent=1)


def bucket(n):
    n = n or 0
    return "خیلی بزرگ (۵۰k+)" if n >= 50000 else "بزرگ (۱۰k-۵۰k)" if n >= 10000 else \
           "متوسط (۲k-۱۰k)" if n >= 2000 else "کوچک (۳۰۰-۲k)" if n >= 300 else "ریز (<۳۰۰)"


async def profile(c, ch):
    u = (getattr(ch, "username", None) or "").lower()
    if not u or u in OURS:
        return None
    try:
        full = await c(functions.channels.GetFullChannelRequest(ch))
        n = full.full_chat.participants_count or 0
        about = full.full_chat.about or ""
    except Exception:
        return None
    text = about
    admins = set(a.lower() for a in ADMIN.findall(about) if a.lower() not in OURS)
    try:                                        # admin handles are usually in the channel's post signatures
        async for m in c.iter_messages(ch, limit=8):
            t = (m.raw_text or "")
            text += "\n" + t
            for a in ADMIN.findall(t):
                if a.lower() not in OURS:
                    admins.add(a.lower())
    except Exception:
        pass
    return {"title": ch.title, "members": n, "bucket": bucket(n), "about": about[:240],
            "admins": sorted(admins)[:4], "open_to_ads": bool(OPEN.search(text)),
            "blocked": bool(NEG.search(about)), "status": "new",
            "found": datetime.date.today().isoformat()}


async def discover(mn, mx, deep):
    d = load()
    chans = d["chans"]
    c = await cs.client()
    seeds = {}
    try:
        for w in KEYWORDS:
            try:
                r = await c(functions.contacts.SearchRequest(q=w, limit=100))
            except errors.FloodWaitError as e:
                if e.seconds > 120:
                    break
                await asyncio.sleep(e.seconds + 2)
                continue
            except Exception:
                continue
            for ch in r.chats:
                if getattr(ch, "broadcast", False) and getattr(ch, "username", None):
                    seeds[ch.username.lower()] = ch
            print(f"«{w}» → {len(seeds)} کاندید", flush=True)
            await asyncio.sleep(1.2)
        # snowball: channels mentioned inside the seeds (one hop) widen the net a lot
        if deep:
            for u, ch in list(seeds.items())[:80]:
                try:
                    async for m in c.iter_messages(ch, limit=15):
                        for h in set(re.findall(r"(?:t\.me/|@)([A-Za-z]\w{4,31})", m.raw_text or "")):
                            hl = h.lower()
                            if hl in seeds or hl in chans or hl.endswith("bot") or hl in OURS:
                                continue
                            try:
                                e = await c.get_entity(h)
                                if getattr(e, "broadcast", False):
                                    seeds[hl] = e
                            except errors.FloodWaitError as fe:
                                if fe.seconds > 120:
                                    raise
                                await asyncio.sleep(fe.seconds + 2)
                            except Exception:
                                pass
                            await asyncio.sleep(0.5)
                except errors.FloodWaitError:
                    break
                except Exception:
                    pass
        added = 0
        for u, ch in seeds.items():
            if u in chans:
                continue
            p = await profile(c, ch)
            if not p or p["blocked"] or not (mn <= p["members"] <= mx):
                continue
            chans[u] = p
            added += 1
            await asyncio.sleep(0.8)
    finally:
        await c.disconnect()
    save(d)
    reach = sum(v["members"] for v in chans.values() if v["status"] == "new")
    print(f"✅ {added} کانال جدید اضافه شد (کل: {len(chans)} کانال، مجموع عضو قابل‌دسترس ~{reach:,}).")


def score(v):
    return (v["status"] == "new", v["open_to_ads"], bool(v["admins"]), min(v["members"] or 0, 30000))


def show_list(status, limit):
    d = load()["chans"]
    items = [(u, v) for u, v in d.items() if status in (None, v["status"])]
    items.sort(key=lambda kv: score(kv[1]), reverse=True)
    print(f"🤝 کانال‌ها ({len(items)}" + (f"، وضعیت {status}" if status else "") + "):")
    for u, v in items[:limit]:
        adm = ("ادمین @" + v["admins"][0]) if v["admins"] else "ادمین نامشخص"
        flags = (" ✅اهل‌تبادل" if v["open_to_ads"] else "") + {"queued": " 📋صف", "sent": " 📤ارسال‌شده",
                 "accepted": " 🤝قبول", "rejected": " ❌رد"}.get(v["status"], "")
        print(f"• @{u} — {v['title'][:32]} — {v['members']:,} عضو [{v['bucket']}] — {adm}{flags}")


def draft_text(u, v):
    big = (v["members"] or 0) >= 5000
    offer = ("• تبادل هم‌زمان: یک پست از شما در کانال ما، یک پست از ما در کانال شما\n"
             "• یا تبلیغ پولی در کانال شما با تعرفه‌ی خودتان\n"
             "• هدیه: چند اکانت VPN رایگان برای شما و اعضای کانالتان 🎁") if big else \
            ("• تبادل هم‌زمان پست (۲۴ ساعت)\n• یا به‌جای تبادل، یک اکانت VPN رایگان یک‌ماهه هدیه 🎁")
    return (f"سلام، وقت‌تون بخیر 🌹\n"
            f"{BRAND_LINE}\n"
            f"کانال «{v.get('title', u)}» رو دیدم و برای همکاری تبلیغاتی پیشنهاد دارم:\n{offer}\n\n"
            f"اگر مایل بودید، متن و زمان رو هماهنگ کنیم. ممنونم 🙏")


def draft(u):
    u = u.lstrip("@").lower()
    v = load()["chans"].get(u, {"title": u})
    print(draft_text(u, v))


def queue(arg):
    d = load()
    ch = d["chans"]
    targets = []
    if arg == "all-open":
        targets = [u for u, v in ch.items() if v["status"] == "new" and v["open_to_ads"] and v["admins"]]
    elif arg and arg.startswith("top"):
        n = int(arg[3:].strip() or "20")
        cand = sorted([(u, v) for u, v in ch.items() if v["status"] == "new" and v["admins"]],
                      key=lambda kv: score(kv[1]), reverse=True)
        targets = [u for u, _ in cand[:n]]
    elif arg:
        u = arg.lstrip("@").lower()
        if u in ch:
            targets = [u]
    for u in targets:
        ch[u]["status"] = "queued"
    save(d)
    print(f"📋 {len(targets)} کانال به صف ارسال اضافه شد. با «partners.py list --status queued» ببین و با «partners.py send» بفرست.")


async def send(cap):
    d = load()
    today = datetime.date.today().isoformat()
    sent_today = sum(1 for t in d["sent_log"] if t.startswith(today))
    # extra safety: at most 1 send-session worth per 6h window is plenty for B2B outreach
    room = max(0, cap - sent_today)
    q = [u for u, v in d["chans"].items() if v["status"] == "queued" and v["admins"]][:room]
    if not q:
        print(f"چیزی برای ارسال نیست (امروز {sent_today} ارسال شده، سقف {cap}).")
        return
    c = await cs.client()
    ok = fail = 0
    try:
        try:                       # if the account is flood-limited right now, stop before touching anyone
            await c.get_me()
            await c(functions.account.GetAuthorizationsRequest())
        except errors.FloodWaitError as e:
            print(f"⏸ اکانت الان محدوده ({e.seconds}s ≈ {e.seconds//60} دقیقه). الان هیچ پیامی نمی‌ره؛ بعداً دوباره send بزن. صف دست‌نخورده موند.")
            return
        for u in q:
            v = d["chans"][u]
            admin = v["admins"][0]
            try:
                await c.send_message(admin, draft_text(u, v))
                v["status"] = "sent"
                v["sent_to"] = admin
                v["sent_at"] = datetime.datetime.now().isoformat(timespec="minutes")
                d["sent_log"].append(today)
                ok += 1
                print(f"📤 @{u} → @{admin}")
            except errors.FloodWaitError as e:
                print(f"⏸ محدودیت تلگرام ({e.seconds}s ≈ {e.seconds//60} دقیقه) — {ok} ارسال شد، بقیه در صف ماند. بعداً دوباره send بزن.")
                break
            except (errors.UserPrivacyRestrictedError, errors.UserIsBlockedError, errors.PeerIdInvalidError) as e:
                v["status"] = "unreachable"; v["error"] = type(e).__name__; fail += 1
                save(d); continue
            except errors.PeerFloodError:
                print(f"⛔ تلگرام اکانت را به‌خاطر اسپم علامت زد — فوراً متوقف شد ({ok} ارسال شد). تا ۲۴ ساعت send نزن.")
                break
            except Exception as e:
                v["status"] = "send_failed"
                v["error"] = type(e).__name__
                fail += 1
            save(d)
            await asyncio.sleep(random.uniform(*GAP))
    finally:
        await c.disconnect()
    save(d)
    print(f"✅ {ok} پیشنهاد ارسال شد، {fail} ناموفق. فردا «send» دوباره، بقیه‌ی صف ادامه پیدا می‌کنه.")


def stats():
    d = load()["chans"]
    cnt = {}
    reach = 0
    for v in d.values():
        cnt[v["status"]] = cnt.get(v["status"], 0) + 1
        if v["status"] in ("accepted",):
            reach += v["members"] or 0
    print("📊 قیف تبادل تبلیغ:")
    for k, lbl in (("new", "کشف‌شده"), ("queued", "در صف"), ("sent", "پیشنهاد ارسال‌شده"),
                   ("accepted", "قبول‌شده"), ("rejected", "ردشده"), ("send_failed", "ارسال ناموفق")):
        print(f"• {lbl}: {cnt.get(k, 0)}")
    print(f"• مجموع عضو کانال‌های قبول‌شده (برد تبلیغ): ~{reach:,}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["discover", "list", "draft", "queue", "send", "mark", "stats", "check"])
    ap.add_argument("arg", nargs="?")
    ap.add_argument("arg2", nargs="?")
    ap.add_argument("--min", type=int, default=300)
    ap.add_argument("--max", type=int, default=200000)
    ap.add_argument("--deep", action="store_true")
    ap.add_argument("--status")
    ap.add_argument("--limit", type=int, default=60)
    a = ap.parse_args()
    if a.cmd == "discover":
        asyncio.run(discover(a.min, a.max, a.deep))
    elif a.cmd == "list":
        show_list(a.status, a.limit)
    elif a.cmd == "draft":
        draft(a.arg)
    elif a.cmd == "queue":
        queue(a.arg)
    elif a.cmd == "send":
        asyncio.run(send(a.limit if a.limit != 60 else SEND_CAP_DEFAULT))
    elif a.cmd == "mark":
        d = load()
        u = (a.arg or "").lstrip("@").lower()
        if u in d["chans"]:
            d["chans"][u]["status"] = a.arg2
            save(d)
            print(f"@{u} → {a.arg2}")
    elif a.cmd == "stats":
        stats()
    elif a.cmd == "check":
        d = load(); today = datetime.date.today().isoformat()
        used = sum(1 for t in d["sent_log"] if t.startswith(today))
        q = sum(1 for v in d["chans"].values() if v["status"] == "queued")
        print(f"امروز {used} پیشنهاد ارسال شده (سقف {SEND_CAP_DEFAULT}/روز). در صف: {q}. "
              + ("ظرفیت امروز پر است، فردا." if used >= SEND_CAP_DEFAULT else f"امکان ارسال {SEND_CAP_DEFAULT-used} پیشنهاد دیگه."))


if __name__ == "__main__":
    main()
