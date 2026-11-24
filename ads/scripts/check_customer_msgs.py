import glob, os, sys, asyncio, json
BASE = os.path.dirname(sorted(glob.glob("/root/.hermes/tools/python*/bin/python3"))[-1])
sys.path.insert(0, os.path.join(os.path.dirname(BASE), "lib", "python3.14", "site-packages"))
from telethon import TelegramClient

SESSION = "/root/.hermes/profiles/adsaccount/userbot/adsaccount"

async def main():
    with open(SESSION + ".creds.json") as f:
        creds = json.load(f)
    c = TelegramClient(SESSION, creds["api_id"], creds["api_hash"])
    await c.connect()
    me = await c.get_me()
    ent = await c.get_entity("your_group")
    print("me.id =", me.id)
    others = []
    total = 0
    async for m in c.iter_messages(ent, limit=30):
        total += 1
        if m.sender_id != me.id:
            txt = (m.text or "").replace("\n", " ")[:80]
            others.append((m.id, m.sender_id, getattr(m.sender, "bot", None), txt))
    print("scanned", total, "messages in your_group")
    if not others:
        print("NO_NON_SELF_MESSAGES")
    for o in sorted(others):
        print("  OTHER id=%s sender=%s bot=%s | %s" % o)
    await c.disconnect()

asyncio.run(main())
