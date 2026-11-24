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
    print("me.id =", me.id, "me.bot =", me.bot)
    for name in ("your_channel", "your_group"):
        ent = await c.get_entity(name)
        print("===", name, "entity_id =", ent.id, "username =", getattr(ent, "username", None))
        before = None
        msgs = []
        async for m in c.iter_messages(ent, limit=8):
            msgs.append(m)
        msgs.reverse()
        for m in msgs:
            txt = (m.text or "").replace("\n", " ")[:70]
            print("  id=%s out=%s sender=%s bot=%s media=%s | %s" % (
                m.id, m.out, m.sender_id, getattr(m.sender, "bot", None), bool(m.media), txt))
    await c.disconnect()

asyncio.run(main())
