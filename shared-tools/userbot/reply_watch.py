"""«هر وقت فلانی جواب داد خبرم کن» — reply watcher on the OWNER's own Telegram account. No LLM per check.

  reply_watch.py find "<name>"              # fuzzy chat/contact match (fa/en, typo-tolerant): best candidates
  reply_watch.py add "<name or @user or id>" [days=7]   # watch that chat from its CURRENT last message
  reply_watch.py list | cancel <id|name|all>
  reply_watch.py check                      # cron (every 5 min): notify + close watches that got a reply
On a new INCOMING message: the bot messages the owner (name, time, first 200 chars, «💬 باز کردن چت» button);
the watch then closes. Expires after <days>. State: /root/.hermes/userbot/reply_watches.json (600).
Uses a temp COPY of the owner's session file, so it never locks the live session.
"""
import asyncio, difflib, json, os, re, shutil, sys, tempfile, time, urllib.parse, urllib.request
from telethon import TelegramClient

SESS = "/root/.hermes/userbot/owner"
STATE = "/root/.hermes/userbot/reply_watches.json"
OWNER = "100000001"

FA2EN = {"ا": "a", "آ": "a", "ب": "b", "پ": "p", "ت": "t", "ث": "s", "ج": "j", "چ": "ch", "ح": "h", "خ": "kh", "د": "d", "ذ": "z",
         "ر": "r", "ز": "z", "ژ": "zh", "س": "s", "ش": "sh", "ص": "s", "ض": "z", "ط": "t", "ظ": "z", "ع": "", "غ": "gh", "ف": "f",
         "ق": "gh", "ک": "k", "ك": "k", "گ": "g", "ل": "l", "م": "m", "ن": "n", "و": "o", "ه": "e", "ی": "i", "ي": "i", "ئ": "i", "ء": ""}


def out(o):
    print(json.dumps(o, ensure_ascii=False))


def norm(s):
    s = (s or "").lower().replace("‌", " ").replace("ي", "ی").replace("ك", "ک")
    s = re.sub(r"[^\w\s]", " ", s)
    lat = "".join(FA2EN.get(ch, ch) for ch in s)
    lat = lat.replace("kh", "h").replace("gh", "g").replace("ou", "o").replace("u", "o").replace("ee", "i").replace("y", "i")
    lat = re.sub(r"(.)\1+", r"\1", lat)                              # e.g. "sarra" -> "sara"
    lat = re.sub(r"(?<=[^aeio ])h\b", "", lat)
    return " ".join(lat.split())


def score(q, name):
    a, b = norm(q), norm(name)
    if not a or not b:
        return 0.0
    r = difflib.SequenceMatcher(None, a, b).ratio()
    tq = a.split()
    hit = sum(1 for w in tq if any(difflib.SequenceMatcher(None, w, x).ratio() > 0.8 for x in b.split()))
    return max(r, hit / max(1, len(tq)) * 0.95)


def load():
    try:
        return json.load(open(STATE))
    except FileNotFoundError:
        return {"next": 1, "watches": {}}


def save(st):
    json.dump(st, open(STATE + ".tmp", "w"), ensure_ascii=False, indent=1)
    os.chmod(STATE + ".tmp", 0o600)
    os.replace(STATE + ".tmp", STATE)


def bot_send(text, button=None):
    tok = re.search(r"^TELEGRAM_BOT_TOKEN=(.*)$", open("/root/.hermes/.env").read(), re.M).group(1).strip().strip('"')
    data = {"chat_id": OWNER, "text": text}
    if button:
        data["reply_markup"] = json.dumps({"inline_keyboard": [[{"text": "💬 باز کردن چت", "url": button}]]})
    urllib.request.urlopen(urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage",
                                                  data=urllib.parse.urlencode(data).encode()), timeout=20)


async def client():
    cr = json.load(open(SESS + ".creds.json"))
    tmp = tempfile.mkdtemp(prefix="rw")
    shutil.copy2(SESS + ".session", f"{tmp}/s.session")
    c = TelegramClient(f"{tmp}/s", cr["api_id"], cr["api_hash"])
    c._rw_tmp = tmp
    await c.connect()
    return c


async def close(c):
    await c.disconnect()
    shutil.rmtree(c._rw_tmp, ignore_errors=True)


def link_of(ent):
    u = getattr(ent, "username", None)
    if u:
        return f"https://t.me/{u}"
    return f"tg://user?id={ent.id}" if getattr(ent, "first_name", None) is not None else None


async def candidates(c, q, n=5):
    seen, res = set(), []
    async for d in c.iter_dialogs(limit=400):
        if d.id in seen:
            continue
        seen.add(d.id)
        names = [d.name or ""] + ([f"@{d.entity.username}"] if getattr(d.entity, "username", None) else [])
        s = max(score(q.lstrip("@"), x.lstrip("@")) for x in names)
        res.append((s, d.id, d.name, getattr(d.entity, "username", None)))
    res.sort(reverse=True)
    return [{"id": i, "name": nm, "username": un, "score": round(s, 2)} for s, i, nm, un in res[:n]]


async def resolve(c, q):
    if re.fullmatch(r"-?\d+", q) or q.startswith("@"):
        e = await c.get_entity(int(q) if q.lstrip("-").isdigit() else q)
        return e.id, " ".join(x for x in (getattr(e, "first_name", None), getattr(e, "last_name", None)) if x) or getattr(e, "title", q), None
    cs = await candidates(c, q)
    if not cs or cs[0]["score"] < 0.6:
        return None, None, cs
    if len(cs) > 1 and cs[1]["score"] > cs[0]["score"] - 0.05:
        return None, None, cs[:3]                                 # ambiguous: two people match about equally
    return cs[0]["id"], cs[0]["name"], None


async def main():
    a = sys.argv[1:]
    cmd = a[0] if a else ""
    st = load()
    if cmd == "list":
        return out([{"id": k, **v} for k, v in st["watches"].items() if v.get("open")])
    if cmd == "cancel" and len(a) == 2:
        n = 0
        for k, v in st["watches"].items():
            if v.get("open") and (a[1] in ("all", k) or score(a[1], v["name"]) > 0.7):
                v["open"], v["closed"] = False, "cancelled"
                n += 1
        save(st)
        return out({"ok": True, "cancelled": n})
    if cmd not in ("find", "add", "check"):
        sys.exit(__doc__)
    if cmd == "check" and not any(v.get("open") for v in st["watches"].values()):
        return out({"ok": True, "open": 0})
    c = await client()
    try:
        if cmd == "find" and len(a) >= 2:
            return out(await candidates(c, " ".join(a[1:])))
        if cmd == "add" and len(a) >= 2:
            days = int(a[2]) if len(a) > 2 and a[2].isdigit() else 7
            pid, name, cands = await resolve(c, a[1])
            if not pid:
                return out({"ok": False, "error": "not_sure_who", "candidates": cands})
            last = [m async for m in c.iter_messages(pid, limit=1)]
            for v in st["watches"].values():
                if v.get("open") and v["peer"] == pid:
                    v["open"], v["closed"] = False, "replaced"
            wid = str(st["next"])
            st["next"] += 1
            st["watches"][wid] = {"peer": pid, "name": name, "since_id": last[0].id if last else 0,
                                  "created": time.time(), "until": time.time() + days * 86400, "open": True}
            save(st)
            sent_last = last[0].out if last else None
            return out({"ok": True, "id": wid, "name": name, "days": days,
                        "last_message_is_mine": sent_last, "last_text": (last[0].message or "")[:200] if last else None})
        if cmd == "check":
            done = 0
            for k, v in st["watches"].items():
                if not v.get("open"):
                    continue
                if time.time() > v["until"]:
                    v["open"], v["closed"] = False, "expired"
                    bot_send(f"⏰ پایش جواب «{v['name']}» تمام شد؛ در این مدت جوابی نداد.")
                    continue
                new = [m async for m in c.iter_messages(v["peer"], min_id=v["since_id"], limit=20) if not m.out]
                if not new:
                    continue
                m = sorted(new, key=lambda x: x.id)[0]
                ent = await c.get_entity(v["peer"])
                body = (m.message or "").strip() or f"({type(m.media).__name__.replace('MessageMedia', '') if m.media else 'پیام'})"
                t = time.strftime("%H:%M", time.gmtime(m.date.timestamp() + 12600))
                bot_send(f"🔔 {v['name']} جواب داد ({t}):\n\n{body[:200]}{'…' if len(body) > 200 else ''}" +
                         (f"\n\n+{len(new) - 1} پیام دیگر" if len(new) > 1 else ""), link_of(ent))
                v["open"], v["closed"], v["reply_id"] = False, "replied", m.id
                done += 1
            save(st)
            return out({"ok": True, "notified": done})
    finally:
        await close(c)


asyncio.run(main())
