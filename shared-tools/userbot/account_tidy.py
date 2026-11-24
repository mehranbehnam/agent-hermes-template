#!/usr/bin/python3
"""Tidy a user's OWN Telegram account (folders / archive / mute) — the user must have asked for it.
Added 2026-11-18: agents wrote ad-hoc Telethon code for this, then deleted folders, archived the Hermes bot chat
and told the user "archiving doesn't work". This does it one reliable way.

  account_tidy.py <session> folders                                  # list folders
  account_tidy.py <session> folder "<title>" <who> [--match RE] [--except RE]   # create/replace a folder (title ≤ 12 chars)
  account_tidy.py <session> archive <who> [--match RE] [--except RE]           # off the main list (+ muted)
  account_tidy.py <session> unarchive <who> [--match RE] [--except RE]
  account_tidy.py <session> mute <who> [--match RE] [--except RE]
  account_tidy.py <session> delete-folder "<title>"
  account_tidy.py <session> join "<folder title>" @chan1 @group2 @some_bot ...   # join channels/groups, /start bots,
        mute + archive each, and add them to that folder (created if missing). Max 8 per call, 10-18 s apart (anti-spam; keeps one call under ~2.5 min).
  account_tidy.py <session> folder-add "<folder title>" @a @b ...                # put existing chats into a folder
  account_tidy.py <session> leave @a @b ...                                       # leave channels/groups / delete bot chats (only ones the user named)
<who> = channels | groups | both | bots | people | private (= people + bots) | clutter (= channels + groups + bots)
«تایم‌لاین را تمیز کن» = archive clutter --except "AGENT HERMES" (people stay on the main list).
RE is a case-insensitive regex on the chat name, e.g. --match "vpn|proxy|فیلترشکن|کانفیگ|v2ray".
Prints JSON. Sends nothing except "/start" to bots the user asked to add; leaves only chats named explicitly.
"""
import asyncio, json, re, shutil, sys, tempfile, time
from telethon import TelegramClient, functions, types

MUTE = 2**31 - 1


def out(x):
    print(json.dumps(x, ensure_ascii=False))


def pick(d, who):
    bot = bool(getattr(d.entity, "bot", False))
    if who == "bots":
        return bot
    if who == "people":
        return not (d.is_channel or d.is_group) and not bot
    if who == "clutter":
        return d.is_channel or d.is_group or bot
    if who == "private":
        return not (d.is_channel or d.is_group)
    if who == "channels":
        return d.is_channel and not d.is_group
    if who == "groups":
        return d.is_group
    return d.is_channel or d.is_group          # both


async def chats(c, who, match, exc):
    res = []
    for archived in (False, True):
        async for d in c.iter_dialogs(archived=archived):
            if pick(d, who) and (not match or re.search(match, d.name or "", re.I)) and not (exc and re.search(exc, d.name or "", re.I)):
                ns = getattr(d.dialog, "notify_settings", None)
                mu = getattr(ns, "mute_until", None)
                muted = bool(mu) and (mu.timestamp() if hasattr(mu, "timestamp") else mu) > time.time()
                res.append((d.name, await c.get_input_entity(d.entity), archived, muted))
    return res


async def main(a):
    if len(a) < 2:
        sys.exit(__doc__)
    sess, cmd = a[0], a[1]
    opts = {k: a[a.index(k) + 1] for k in ("--match", "--except") if k in a and a.index(k) + 1 < len(a)}
    pos = [x for i, x in enumerate(a[2:]) if x not in opts and x not in ("--match", "--except")]
    cr = json.load(open(sess + ".creds.json"))
    d = tempfile.mkdtemp(prefix="tidy-")
    shutil.copy(sess + ".session", d + "/s.session")          # never lock the live session file
    c = TelegramClient(d + "/s", cr["api_id"], cr["api_hash"])
    await c.connect()
    try:
        if not await c.is_user_authorized():
            return out({"ok": False, "error": "NOT_LOGGED_IN"})
        filters = (await c(functions.messages.GetDialogFiltersRequest())).filters
        title_of = lambda f: getattr(getattr(f, "title", None), "text", getattr(f, "title", None))
        if cmd == "folders":
            return out([{"id": getattr(f, "id", None), "title": title_of(f), "type": type(f).__name__,
                         "chats": len(getattr(f, "include_peers", []) or [])} for f in filters if getattr(f, "id", None)])
        if cmd in ("join", "folder-add") and len(pos) >= 2:
            title, names = pos[0], [x.lstrip("@").split("t.me/")[-1].strip("/") for x in pos[1:]][:8]
            if len(title) > 12:
                return out({"ok": False, "error": "folder title max 12 characters"})
            from telethon import errors as E
            import random
            res, peers = [], []
            for i, n in enumerate(names):
                try:
                    ent = await c.get_entity(n)
                    p = await c.get_input_entity(ent)
                    if cmd == "join":
                        if getattr(ent, "bot", False):
                            await c.send_message(ent, "/start")
                        elif isinstance(ent, types.Channel):
                            await c(functions.channels.JoinChannelRequest(ent))
                        await c(functions.account.UpdateNotifySettingsRequest(peer=types.InputNotifyPeer(p),
                                                                              settings=types.InputPeerNotifySettings(mute_until=MUTE)))
                        await c(functions.folders.EditPeerFoldersRequest([types.InputFolderPeer(p, 1)]))
                    peers.append(p)
                    res.append({"name": n, "ok": True, "title": getattr(ent, "title", None) or getattr(ent, "first_name", None)})
                except E.FloodWaitError as e:
                    res.append({"name": n, "ok": False, "error": f"Telegram limit: wait {e.seconds}s — stop and tell the user"})
                    break
                except Exception as e:
                    res.append({"name": n, "ok": False, "error": type(e).__name__})
                if cmd == "join" and i < len(names) - 1:
                    await asyncio.sleep(random.randint(10, 18))
            filters = (await c(functions.messages.GetDialogFiltersRequest())).filters
            old = next((f for f in filters if title_of(f) == title and isinstance(f, types.DialogFilter)), None)
            fid = old.id if old else max([getattr(f, "id", 0) or 0 for f in filters] + [1]) + 1
            from telethon import utils as U
            keep, have = [], set()
            for x in (list(old.include_peers) if old else []) + peers:      # de-duplicate by real peer id
                pid = U.get_peer_id(x)
                if pid not in have:
                    have.add(pid)
                    keep.append(x)
            if keep:
                await c(functions.messages.UpdateDialogFilterRequest(id=fid, filter=types.DialogFilter(
                    id=fid, title=types.TextWithEntities(title, []), pinned_peers=[], include_peers=keep[:100], exclude_peers=[])))
            return out({"ok": True, "folder": title, "folder_total": len(keep), "results": res})
        if cmd == "leave" and pos:
            res = []
            for n in [x.lstrip("@").split("t.me/")[-1].strip("/") for x in pos][:30]:
                try:
                    await c.delete_dialog(n)
                    res.append({"name": n, "ok": True})
                except Exception as e:
                    res.append({"name": n, "ok": False, "error": type(e).__name__})
                await asyncio.sleep(1)
            return out({"ok": True, "results": res})
        if cmd == "delete-folder" and pos:
            f = next((f for f in filters if title_of(f) == pos[0]), None)
            if not f:
                return out({"ok": False, "error": "no such folder"})
            await c(functions.messages.UpdateDialogFilterRequest(id=f.id))
            return out({"ok": True, "deleted": pos[0]})
        if cmd == "folder" and len(pos) >= 2:
            title, who = pos[0], pos[1]
            if len(title) > 12:
                return out({"ok": False, "error": "folder title max 12 characters"})
            lst = await chats(c, who, opts.get("--match"), opts.get("--except"))
            old = next((f for f in filters if title_of(f) == title and isinstance(f, types.DialogFilter)), None)
            fid = old.id if old else max([getattr(f, "id", 0) or 0 for f in filters] + [1]) + 1
            await c(functions.messages.UpdateDialogFilterRequest(id=fid, filter=types.DialogFilter(
                id=fid, title=types.TextWithEntities(title, []), pinned_peers=[], include_peers=[x[1] for x in lst][:100], exclude_peers=[])))
            return out({"ok": True, "folder": title, "chats": len(lst), "names": [x[0] for x in lst][:100]})
        if cmd in ("archive", "unarchive", "mute") and pos:
            from telethon import errors as E
            lst = await chats(c, pos[0], opts.get("--match"), opts.get("--except"))
            note = ""
            try:
                for _, p, _, muted in lst:
                    if cmd in ("archive", "mute") and not muted:      # only chats not muted yet (Telegram rate-limits this)
                        await c(functions.account.UpdateNotifySettingsRequest(peer=types.InputNotifyPeer(p),
                                                                              settings=types.InputPeerNotifySettings(mute_until=MUTE)))
                        await asyncio.sleep(0.5)
            except E.FloodWaitError as e:
                note = f"mute limited by Telegram for {e.seconds}s; archived anyway"
            todo = [p for _, p, a_, _ in lst if a_ != (cmd == "archive")]
            if cmd != "mute" and todo:
                await c(functions.folders.EditPeerFoldersRequest([types.InputFolderPeer(p, 1 if cmd == "archive" else 0) for p in todo]))
            # verify instead of guessing
            arch = {n for n, _, a_, _ in await chats(c, pos[0], opts.get("--match"), opts.get("--except")) if a_}
            return out({"ok": True, "action": cmd, "chats": len(lst), "now_archived": len(arch), "note": note, "names": [x[0] for x in lst][:100]})
        sys.exit(__doc__)
    finally:
        await c.disconnect()
        shutil.rmtree(d, ignore_errors=True)


asyncio.run(main(sys.argv[1:]))
