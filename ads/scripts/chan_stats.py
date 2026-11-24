#!/usr/bin/python3
"""HermesVPN channel + group analytics (Owner's account is the creator of both).

  chan_stats.py collect                 # take a snapshot (cron runs this every hour)
  chan_stats.py report [--days N]       # Persian report: today (Tehran) or the last N days; collects first

What Telegram allows us to know (and what it does NOT):
  channel @your_channel : member count, who joined / left and when (admin log), views / forwards / reactions per
                      post, views gained per day (from hourly snapshots). Telegram NEVER reveals WHO viewed a
                      channel post or who opened the channel — views are anonymous.
  group  @your_group : member count, joins / leaves (admin log), who wrote what, and WHO READ each message
                      ("seen by", Telegram keeps this only for groups under 100 members and messages < 7 days old).
"""
import glob, os, sys, asyncio, json, sqlite3, shutil, time, datetime, argparse

_HPY = sorted(glob.glob("/root/.hermes/tools/python*/bin/python3"))[-1]
if os.path.realpath(sys.executable) != os.path.realpath(_HPY):
    os.execv(_HPY, [_HPY, os.path.abspath(__file__)] + sys.argv[1:])
BASE = os.path.dirname(_HPY)
sys.path.insert(0, os.path.join(os.path.dirname(BASE), "lib", "python3.14", "site-packages"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from telethon import TelegramClient, functions, types

# Env overrides let a second brand (IranVPN) reuse this with its own userbot + channel/group.
SESSION_SRC = os.environ.get("CS_SESSION", "/root/.hermes/profiles/adsaccount/userbot/adsaccount")
DIR = os.environ.get("CS_DIR", "/root/.hermes/ads/stats")
DB = f"{DIR}/stats.db"
CS_LABEL = os.environ.get("CS_LABEL", "HERMES VPN")
CHANNEL = os.environ.get("CS_CHANNEL", "your_channel")
GROUP = os.environ.get("CS_GROUP", "your_group")
TZ = datetime.timezone(datetime.timedelta(hours=3, minutes=30))
os.makedirs(DIR, exist_ok=True)


def db():
    c = sqlite3.connect(DB)
    c.executescript("""
    CREATE TABLE IF NOT EXISTS members (ts INTEGER, chat TEXT, count INTEGER);
    CREATE TABLE IF NOT EXISTS post_views (ts INTEGER, msg_id INTEGER, posted INTEGER, views INTEGER,
                                           forwards INTEGER, reactions INTEGER, text TEXT);
    CREATE TABLE IF NOT EXISTS events (id INTEGER, chat TEXT, ts INTEGER, user_id INTEGER, kind TEXT,
                                       PRIMARY KEY (id, chat));
    CREATE TABLE IF NOT EXISTS reads (chat TEXT, msg_id INTEGER, user_id INTEGER, ts INTEGER,
                                      PRIMARY KEY (chat, msg_id, user_id));
    CREATE TABLE IF NOT EXISTS msgs (chat TEXT, msg_id INTEGER, user_id INTEGER, ts INTEGER, text TEXT,
                                     PRIMARY KEY (chat, msg_id));
    CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, name TEXT, username TEXT);
    """)
    return c


async def client():
    # private copy of the session file so a concurrent userbot script never hits "database is locked"
    # one private copy PER PROCESS: a shared copy got overwritten by a concurrent run (live monitor + hourly
    # collect) and became "database disk image is malformed"
    import atexit
    dst = f"{DIR}/sess_{os.getpid()}.session"
    shutil.copyfile(SESSION_SRC + ".session", dst)
    os.chmod(dst, 0o600)
    atexit.register(lambda: [os.path.exists(p) and os.remove(p) for p in (dst, dst + "-journal")])
    cr = json.load(open(SESSION_SRC + ".creds.json"))
    c = TelegramClient(dst[:-8], cr["api_id"], cr["api_hash"])
    await c.connect()
    return c


def remember_user(d, u):
    if u is None or not hasattr(u, "id"):
        return
    name = ((getattr(u, "first_name", "") or "") + " " + (getattr(u, "last_name", "") or "")).strip() or getattr(u, "title", "") or str(u.id)
    d.execute("INSERT OR REPLACE INTO users VALUES (?,?,?)", (u.id, name, getattr(u, "username", None)))


async def collect():
    c = await client()
    d = db()
    now = int(time.time())
    try:
        for chat in (CHANNEL, GROUP):
            ent = await c.get_entity(chat)
            full = await c(functions.channels.GetFullChannelRequest(ent))
            d.execute("INSERT INTO members VALUES (?,?,?)", (now, chat, full.full_chat.participants_count))
            # joins / leaves from the admin log (last 48h kept by Telegram)
            log = await c(functions.channels.GetAdminLogRequest(
                channel=ent, q="", max_id=0, min_id=0, limit=100,
                events_filter=types.ChannelAdminLogEventsFilter(join=True, leave=True, invite=True)))
            for u in log.users:
                remember_user(d, u)
            for ev in log.events:
                kind = type(ev.action).__name__.replace("ChannelAdminLogEventAction", "")
                kind = {"ParticipantJoin": "join", "ParticipantLeave": "leave", "ParticipantInvite": "added",
                        "ParticipantJoinByInvite": "join", "ParticipantJoinByRequest": "join"}.get(kind, kind)
                uid = ev.user_id
                if kind == "added" and getattr(ev.action, "participant", None) is not None:
                    uid = getattr(ev.action.participant, "user_id", uid)
                d.execute("INSERT OR IGNORE INTO events VALUES (?,?,?,?,?)", (ev.id, chat, int(ev.date.timestamp()), uid, kind))
        # channel posts: views snapshot
        async for m in c.iter_messages(CHANNEL, limit=120):
            reac = sum(r.count for r in m.reactions.results) if getattr(m, "reactions", None) and m.reactions.results else 0
            d.execute("INSERT INTO post_views VALUES (?,?,?,?,?,?,?)",
                      (now, m.id, int(m.date.timestamp()), m.views or 0, m.forwards or 0, reac, (("استیکر " + (m.file.emoji or "")) if m.sticker else ((m.raw_text or "").replace("\n", " ").strip() or "[عکس/فایل]"))[:60]))
        # group messages + who read them (Telegram: groups < 100 members, messages < 7 days)
        gent = await c.get_entity(GROUP)
        week = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7)
        async for m in c.iter_messages(GROUP, limit=150):
            if m.date < week:
                break
            if m.sender:
                remember_user(d, m.sender)
            d.execute("INSERT OR IGNORE INTO msgs VALUES (?,?,?,?,?)",
                      (GROUP, m.id, m.sender_id, int(m.date.timestamp()), (("استیکر " + (m.file.emoji or "")) if m.sticker else ((m.raw_text or "").replace("\n", " ").strip() or "[عکس/فایل]"))[:60]))
            if m.action:
                continue
            try:
                rp = await c(functions.messages.GetMessageReadParticipantsRequest(peer=gent, msg_id=m.id))
                for r in rp:
                    d.execute("INSERT OR IGNORE INTO reads VALUES (?,?,?,?)", (GROUP, m.id, r.user_id, int(r.date.timestamp())))
            except Exception:
                pass
            await asyncio.sleep(0.4)
        # names for readers we have not seen yet
        unknown = [r[0] for r in d.execute("SELECT DISTINCT user_id FROM reads WHERE user_id NOT IN (SELECT user_id FROM users)")]
        for uid in unknown[:50]:
            try:
                remember_user(d, await c.get_entity(uid))
            except Exception:
                pass
        d.commit()
    finally:
        d.close()
        await c.disconnect()


async def presence():
    """Live: who of the channel/group members is online now / when they were last seen (if their privacy allows)."""
    c = await client()
    out = {}
    try:
        for chat in (CHANNEL, GROUP):
            rows = []
            async for u in c.iter_participants(chat, limit=500):
                if u.bot:
                    continue
                st = u.status
                nm = ((u.first_name or "") + " " + (u.last_name or "")).strip() + (f" (@{u.username})" if u.username else "")
                if isinstance(st, types.UserStatusOnline):
                    rows.append((0, nm, "🟢 الان آنلاین"))
                elif isinstance(st, types.UserStatusOffline):
                    ago = (datetime.datetime.now(datetime.timezone.utc) - st.was_online).total_seconds()
                    rows.append((ago, nm, f"⚪ آخرین بازدید {jd(int(st.was_online.timestamp()))}"))
                elif isinstance(st, types.UserStatusRecently):
                    rows.append((10**6, nm, "⚪ به‌تازگی"))
                elif isinstance(st, types.UserStatusLastWeek):
                    rows.append((10**7, nm, "⚪ هفته‌ی گذشته"))
                else:
                    rows.append((10**8, nm, "⚪ مدت‌ها پیش / پنهان"))
            out[chat] = sorted(rows)
    finally:
        await c.disconnect()
    return out


def name(d, uid):
    r = d.execute("SELECT name, username FROM users WHERE user_id=?", (uid,)).fetchone()
    if not r:
        return str(uid)
    return r[0] + (f" (@{r[1]})" if r[1] else "")


def jd(ts):
    from jalali import fmt as jfmt
    return jfmt(datetime.datetime.fromtimestamp(ts, TZ))[5:]   # mm/dd HH:MM (Jalali)


def report(days, hours=0):
    d = db()
    now = time.time()
    if hours:
        start = now - hours * 3600
        title = f"{hours} ساعت اخیر (تا {datetime.datetime.now(TZ):%H:%M})"
    elif days <= 1:
        start = datetime.datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        title = f"امروز تا ساعت {datetime.datetime.now(TZ):%H:%M}"
    else:
        start = now - days * 86400
        title = f"{days} روز گذشته"
    L = [f"📊 گزارش کانال و گروه {CS_LABEL} — {title}", ""]
    S = int(start)
    # ---- channel
    mem = d.execute("SELECT count FROM members WHERE chat=? ORDER BY ts DESC LIMIT 1", (CHANNEL,)).fetchone()
    mem0 = d.execute("SELECT count FROM members WHERE chat=? AND ts>=? ORDER BY ts LIMIT 1", (CHANNEL, S)).fetchone()
    L.append(f"📢 کانال @{CHANNEL} — {mem[0] if mem else '?'} عضو" + (f" ({mem[0] - mem0[0]:+d} در این بازه)" if mem and mem0 else ""))
    for kind, label in (("join", "➕ عضو شدند"), ("added", "➕ اضافه شدند"), ("leave", "➖ لفت دادند")):
        rows = d.execute("SELECT user_id, ts FROM events WHERE chat=? AND kind=? AND ts>=? ORDER BY ts", (CHANNEL, kind, S)).fetchall()
        if rows:
            L.append(f"{label} ({len(rows)}): " + "، ".join(f"{name(d, u)} {jd(t)}" for u, t in rows[:25]))
    # views gained in the period = last snapshot views - views at period start (per post)
    last_ts = d.execute("SELECT MAX(ts) FROM post_views").fetchone()[0]
    gained, per_post = 0, []
    if last_ts:
        for msg_id, posted, views, fw, reac, text in d.execute(
                "SELECT msg_id, posted, views, forwards, reactions, text FROM post_views WHERE ts=?", (last_ts,)):
            base = d.execute("SELECT views FROM post_views WHERE msg_id=? AND ts<=? ORDER BY ts DESC LIMIT 1", (msg_id, S)).fetchone()
            if base is None:
                base = (0,) if posted >= S else d.execute("SELECT views FROM post_views WHERE msg_id=? ORDER BY ts LIMIT 1", (msg_id,)).fetchone()
            g = max(0, views - (base[0] if base else views))
            gained += g
            per_post.append((g, views, fw, reac, posted, text))
    L.append(f"👁 بازدید پست‌ها در این بازه: {gained}")
    top = sorted([p for p in per_post if p[0] > 0 and not p[5].startswith("استیکر")], reverse=True)[:8]
    if top:
        L.append("پربازدیدترین پست‌ها (بازدید این بازه / کل):")
        for g, v, fw, reac, posted, text in top:
            L.append(f"  • {g} / {v} 👁" + (f" · {fw} فوروارد" if fw else "") + (f" · {reac} ری‌اکشن" if reac else "") + f" — {jd(posted)} — {text[:35]}")
    L.append("ℹ️ تلگرام نشان نمی‌دهد چه کسی پست کانال را دیده یا کانال را باز کرده؛ فقط تعداد بازدید.")
    # ---- group
    L.append("")
    gm = d.execute("SELECT count FROM members WHERE chat=? ORDER BY ts DESC LIMIT 1", (GROUP,)).fetchone()
    gm0 = d.execute("SELECT count FROM members WHERE chat=? AND ts>=? ORDER BY ts LIMIT 1", (GROUP, S)).fetchone()
    L.append(f"👥 گروه @{GROUP} — {gm[0] if gm else '?'} عضو" + (f" ({gm[0] - gm0[0]:+d} در این بازه)" if gm and gm0 else ""))
    for kind, label in (("join", "➕ عضو شدند"), ("added", "➕ اضافه شدند"), ("leave", "➖ لفت دادند")):
        rows = d.execute("SELECT user_id, ts FROM events WHERE chat=? AND kind=? AND ts>=? ORDER BY ts", (GROUP, kind, S)).fetchall()
        if rows:
            L.append(f"{label} ({len(rows)}): " + "، ".join(f"{name(d, u)} {jd(t)}" for u, t in rows[:25]))
    readers = d.execute("""SELECT user_id, COUNT(*), COUNT(DISTINCT strftime('%Y-%m-%d %H', ts, 'unixepoch')), MIN(ts), MAX(ts)
                           FROM reads WHERE chat=? AND ts>=? GROUP BY user_id ORDER BY 2 DESC""", (GROUP, S)).fetchall()
    L.append(f"👀 بازدیدکننده‌های گروه (پیام‌ها را خوانده‌اند): {len(readers)} نفر")
    for uid, n, visits, first, last in readers[:30]:
        L.append(f"  • {name(d, uid)} — {n} پیام دیده، حدود {visits} بار سر زده — اولین {jd(first)}، آخرین {jd(last)}")
    writers = d.execute("SELECT user_id, COUNT(*) FROM msgs WHERE chat=? AND ts>=? AND user_id IS NOT NULL GROUP BY user_id ORDER BY 2 DESC",
                        (GROUP, S)).fetchall()
    if writers:
        L.append("✍️ پیام نوشته‌اند: " + "، ".join(f"{name(d, u)} ({n})" for u, n in writers[:15]))
    last_msgs = d.execute("SELECT msg_id, ts, text FROM msgs WHERE chat=? ORDER BY ts DESC LIMIT 5", (GROUP,)).fetchall()
    if last_msgs:
        L.append("آخرین پیام‌های گروه و چه کسانی دیدند:")
        for mid, ts, text in last_msgs:
            who = [name(d, u) for (u,) in d.execute("SELECT user_id FROM reads WHERE chat=? AND msg_id=? ORDER BY ts", (GROUP, mid))]
            L.append(f"  • {jd(ts)} «{text[:30]}» — دیده‌شده توسط {len(who)}: " + ("، ".join(who[:10]) if who else "—"))
    L.append("ℹ️ «سر زده» از روی ساعت‌هایی که پیام‌ها را خوانده تخمین زده می‌شود. تلگرام لیست خواننده‌ها را فقط ۷ روز نگه می‌دارد.")
    d.close()
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["collect", "report"])
    ap.add_argument("--days", type=int, default=1)
    ap.add_argument("--no-collect", action="store_true")
    ap.add_argument("--hours", type=int, default=0, help="report window in hours (e.g. 1 = last hour)")
    ap.add_argument("--live", action="store_true", help="add who is online now / last seen for channel & group members")
    a = ap.parse_args()
    if a.cmd == "collect" or not a.no_collect:
        asyncio.run(collect())
    if a.cmd == "report":
        print(report(a.days, a.hours))
        if a.live:
            pres = asyncio.run(presence())
            L = ["", f"🟢 وضعیت لحظه‌ای اعضا ({datetime.datetime.now(TZ):%H:%M})"]
            for chat, label in ((CHANNEL, "📢 کانال"), (GROUP, "👥 گروه")):
                rows = pres.get(chat, [])
                online = [r for r in rows if r[0] == 0]
                L.append(f"{label}: {len(online)} نفر الان آنلاین از {len(rows)} عضو")
                for _, nm, st in rows[:40]:
                    L.append(f"  • {nm} — {st}")
            L.append("ℹ️ «آخرین بازدید» یعنی آخرین باری که در تلگرام آنلاین بوده (نه لزوماً داخل کانال)؛ اگر حریم خصوصی‌اش بسته باشد پنهان است.")
            print("\n".join(L))


if __name__ == "__main__":
    main()
