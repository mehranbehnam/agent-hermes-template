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
    gr = await c.get_entity("your_group")
    n = 0
    questions = []
    async for m in c.iter_messages(gr, limit=60):
        n += 1
        if m.sender_id == me.id:
            continue
        if getattr(m.sender, "bot", False):
            continue
        txt = (m.text or "").strip()
        questions.append({"id": m.id, "sender": m.sender_id, "text": txt[:80]})
    print("scanned", n, "messages; non-self non-bot:", len(questions))
    for q in questions[-15:]:
        print(json.dumps(q, ensure_ascii=False))
    await c.disconnect()

asyncio.run(main())
