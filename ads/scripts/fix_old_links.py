#!/usr/bin/python3
"""One-time (owner 2026-11-09): edit Owner's already-posted ads so their download links point to the fast
Cloudflare-cached 443 URLs instead of the slow :2087 ones. Only the URLs change.
  fix_old_links.py --dry-run     # list what would change
  fix_old_links.py               # edit
Chats: @your_channel, @your_group, @example_ad_group (only Owner's own messages, last 14 days).
Messages with formatting other than plain links/mentions are skipped (an edit would drop that formatting)."""
import glob, os, sys, json, re, asyncio, time

_HPY = sorted(glob.glob("/root/.hermes/tools/python*/bin/python3"))[-1]
if os.path.realpath(sys.executable) != os.path.realpath(_HPY):
    os.execv(_HPY, [_HPY, os.path.abspath(__file__)] + sys.argv[1:])
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from telethon import TelegramClient, errors
from telethon.tl import types
from public_text_guard import check as guard

SESSION = "/root/.hermes/profiles/adsaccount/userbot/adsaccount"
CHATS = ["your_channel", "your_group", "example_ad_group"]
OLD = re.compile(r"https://hook-369df49b\.example\.com:2087/dl/(HermesVPN-Connect(?:-armv7)?\.apk|HermesVPN-Connect-Setup\.exe)")
NEW = r"https://app.example.com/app/\1"
PLAIN = (types.MessageEntityUrl, types.MessageEntityMention, types.MessageEntityHashtag, types.MessageEntityBotCommand)


async def main():
    dry = "--dry-run" in sys.argv
    cr = json.load(open(SESSION + ".creds.json"))
    c = TelegramClient(SESSION, cr["api_id"], cr["api_hash"])
    await c.connect()
    since = time.time() - 14 * 86400
    stats = {"edited": 0, "skipped_format": 0, "failed": 0}
    try:
        for chat in CHATS:
            async for m in c.iter_messages(chat, limit=400):
                if m.date.timestamp() < since:
                    break
                if not (m.out or (m.post and chat == "your_channel")):
                    continue
                text = m.message or ""
                if not OLD.search(text):
                    continue
                new = OLD.sub(NEW, text)
                if any(not isinstance(e, PLAIN) for e in (m.entities or [])):
                    stats["skipped_format"] += 1
                    print(f"SKIP {chat} {m.id}: has formatting")
                    continue
                if guard(new):
                    stats["failed"] += 1
                    print(f"SKIP {chat} {m.id}: guard {guard(new)}")
                    continue
                if dry:
                    print(f"would edit {chat} {m.id} ({m.date:%m-%d %H:%M})")
                    continue
                try:
                    await c.edit_message(chat, m.id, new, link_preview=False)
                    stats["edited"] += 1
                    print(f"edited {chat} {m.id}")
                except errors.FloodWaitError as e:
                    print(f"FloodWait {e.seconds}s — stopping")
                    stats["failed"] += 1
                    return
                except Exception as e:
                    stats["failed"] += 1
                    print(f"FAILED {chat} {m.id}: {type(e).__name__}: {e}")
                await asyncio.sleep(2)
    finally:
        await c.disconnect()
        print("DONE", stats)


asyncio.run(main())
