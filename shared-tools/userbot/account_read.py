"""Read-only view of the user's OWN Telegram account through his own userbot session (premium feature).
Only the user's own agent runs this, with the session path inside his own profile. Nothing is stored.

  account_read.py <session> status
  account_read.py <session> contacts [query]          # name, @username, phone (max 200)
  account_read.py <session> dialogs [n]               # recent chats: name, type, unread, last message time (default 30)
  account_read.py <session> history <chat> [n]        # last n messages of one chat (default 20, max 100)
  account_read.py <session> search <text> [n]         # search the user's messages across chats (default 20)
  account_read.py <session> saved [n]                 # the user's Saved Messages, newest first (default 20, max 100)
  account_read.py <session> saved-search <text> [n]   # search inside Saved Messages
  account_read.py <session> saved-get <id>            # one Saved Message in full
  account_read.py <session> tgsearch <text> [n]       # GLOBAL Telegram search: public channels, groups, bots (like the app's search)
<chat> = @username, phone, numeric id, or an exact chat/contact name from 'dialogs'. All times are Tehran time.
"""
import asyncio, json, sys
from telethon import TelegramClient
from telethon.tl.functions.contacts import GetContactsRequest


def teh(d, fmt="%Y-%m-%d %H:%M"):
    """Telegram dates are UTC; the owner and users live on Tehran time (UTC+3:30)."""
    import datetime
    return (d + datetime.timedelta(hours=3, minutes=30)).strftime(fmt) if d else None


def short(t, n=300):
    t = (t or "").replace("\n", " ").strip()
    return t if len(t) <= n else t[:n] + "…"


async def resolve(c, chat):
    try:
        return await c.get_entity(int(chat) if chat.lstrip("-").isdigit() else chat)
    except Exception:
        async for d in c.iter_dialogs(limit=300):
            if (d.name or "").strip() == chat.strip():
                return d.entity
    raise SystemExit(f"NOT_FOUND: {chat}")


async def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    session, cmd, rest = sys.argv[1], sys.argv[2], sys.argv[3:]
    if session != "/root/.hermes/userbot/owner" and ("/profiles/" not in session or "/userbot/" not in session):
        sys.exit("REFUSED: session must be inside the user's own profile")
    try:
        creds = json.load(open(session + ".creds.json"))
    except FileNotFoundError:
        sys.exit("NOT_LOGGED_IN: the userbot is not set up yet (run the telegram-userbot-setup steps first)")
    c = TelegramClient(session, creds["api_id"], creds["api_hash"])
    await c.connect()
    try:
        if not await c.is_user_authorized():
            sys.exit("NOT_LOGGED_IN: the userbot session is not authorized")
        if cmd == "status":
            me = await c.get_me()
            print(json.dumps({"logged_in": True, "name": " ".join(x for x in (me.first_name, me.last_name) if x),
                              "username": me.username}, ensure_ascii=False))
        elif cmd == "contacts":
            q = (rest[0] if rest else "").lower()
            res = await c(GetContactsRequest(hash=0))
            out = []
            for u in res.users:
                name = " ".join(x for x in (u.first_name, u.last_name) if x)
                if q and q not in name.lower() and q not in (u.username or "").lower() and q not in (u.phone or ""):
                    continue
                out.append({"name": name, "username": u.username, "phone": u.phone, "id": u.id,
                            "link": f"https://t.me/{u.username}" if u.username else f"tg://user?id={u.id}"})
            print(json.dumps({"count": len(out), "contacts": out[:200]}, ensure_ascii=False))
        elif cmd == "dialogs":
            n = min(int(rest[0]) if rest else 30, 100)
            out = []
            async for d in c.iter_dialogs(limit=n):
                kind = "channel" if d.is_channel and not d.is_group else ("group" if d.is_group else "private")
                ent = d.entity
                uname = getattr(ent, "username", None) or ((getattr(ent, "usernames", None) or [None])[0] and ent.usernames[0].username)
                if uname:
                    link = f"https://t.me/{uname}"
                elif kind == "private":
                    link = f"tg://user?id={ent.id}"
                else:
                    link = f"https://t.me/c/{ent.id}/999999999"   # private group/channel: opens for members
                out.append({"name": d.name, "type": kind, "unread": d.unread_count,
                            "last": teh(d.date), "id": d.id, "link": link})
            print(json.dumps(out, ensure_ascii=False))
        elif cmd == "history" and rest:
            ent = await resolve(c, rest[0])
            n = min(int(rest[1]) if len(rest) > 1 else 20, 100)
            out = []
            async for m in c.iter_messages(ent, limit=n):
                out.append({"date": teh(m.date), "from_me": m.out, "text": short(m.message),
                            "media": type(m.media).__name__ if m.media else None})
            print(json.dumps(list(reversed(out)), ensure_ascii=False))
        elif cmd == "search" and rest:
            n = min(int(rest[1]) if len(rest) > 1 else 20, 100)
            out = []
            async for m in c.iter_messages(None, search=rest[0], limit=n):
                chat = await m.get_chat()
                out.append({"chat": getattr(chat, "title", None) or " ".join(x for x in (getattr(chat, "first_name", None), getattr(chat, "last_name", None)) if x),
                            "date": teh(m.date), "from_me": m.out, "text": short(m.message)})
            print(json.dumps(out, ensure_ascii=False))
        elif cmd == "tgsearch" and rest:
            from telethon.tl.functions.contacts import SearchRequest
            n = min(int(rest[1]) if len(rest) > 1 else 40, 100)
            r = await c(SearchRequest(q=rest[0], limit=n))
            out = []
            for ch in r.chats:
                if not getattr(ch, "username", None) and not getattr(ch, "usernames", None):
                    continue                                    # private chats you are in: not a public result
                un = ch.username or ch.usernames[0].username
                out.append({"type": "channel" if getattr(ch, "broadcast", False) else "group", "title": ch.title, "username": un,
                            "members": getattr(ch, "participants_count", None), "link": f"https://t.me/{un}"})
            for u in r.users:
                if getattr(u, "bot", False) and u.username:
                    out.append({"type": "bot", "title": " ".join(x for x in (u.first_name, u.last_name) if x), "username": u.username,
                                "members": None, "link": f"https://t.me/{u.username}"})
            print(json.dumps(out, ensure_ascii=False))
        elif cmd in ("saved", "saved-search", "saved-get"):
            if cmd == "saved-get" and rest:
                msgs = [await c.get_messages("me", ids=int(rest[0]))]
                n_text = 4000
            else:
                q = rest[0] if cmd == "saved-search" and rest else None
                n = min(int(rest[1 if q else 0]) if len(rest) > (1 if q else 0) else 20, 100)
                msgs = [m async for m in c.iter_messages("me", limit=n, search=q)]
                n_text = 300
            out = []
            for m in msgs:
                if not m:
                    continue
                fwd = None
                if m.fwd_from:
                    try:
                        src = await m.get_forward_sender() or (await c.get_entity(m.fwd_from.from_id) if m.fwd_from.from_id else None)
                        fwd = getattr(src, "title", None) or " ".join(x for x in (getattr(src, "first_name", None), getattr(src, "last_name", None)) if x) or m.fwd_from.from_name
                    except Exception:
                        fwd = m.fwd_from.from_name
                out.append({"id": m.id, "date": teh(m.date), "text": short(m.message, n_text),
                            "media": type(m.media).__name__.replace("MessageMedia", "") if m.media else None,
                            "file": m.file.name if m.file and m.file.name else None, "from": fwd})
            print(json.dumps(out, ensure_ascii=False))
        else:
            sys.exit(__doc__)
    finally:
        await c.disconnect()


asyncio.run(main())
