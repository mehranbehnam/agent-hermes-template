import glob, os, sys, asyncio, json
BASE = os.path.dirname(sorted(glob.glob("/root/.hermes/tools/python*/bin/python3"))[-1])
sys.path.insert(0, os.path.join(os.path.dirname(BASE), "lib", "python3.14", "site-packages"))
from telethon import TelegramClient
SESSION = "/root/.hermes/profiles/adsaccount/userbot/adsaccount"
async def main():
    cr = json.load(open(SESSION + ".creds.json")); c = TelegramClient(SESSION, cr["api_id"], cr["api_hash"]); await c.connect()
    for t in ["your_channel", "your_group"]:
        async for m in c.iter_messages(t, limit=12):
            kind = "sticker" if m.sticker else ("photo" if m.photo else ("doc:" + (m.file.mime_type if m.file else "") if m.document else "text"))
            print(t, m.id, m.date.strftime("%m-%d %H:%M"), "out" if m.out else ("from=%s" % m.sender_id), kind, (m.raw_text or "")[:40].replace("\n", " "))
    await c.disconnect()
asyncio.run(main())
