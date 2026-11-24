import glob, os, sys, asyncio, json, collections
BASE = os.path.dirname(sorted(glob.glob("/root/.hermes/tools/python*/bin/python3"))[-1])
sys.path.insert(0, os.path.join(os.path.dirname(BASE), "lib", "python3.14", "site-packages"))
from telethon import TelegramClient, functions, types
SESSION = "/root/.hermes/profiles/adsaccount/userbot/adsaccount"
async def main():
    cr = json.load(open(SESSION + ".creds.json"))
    c = TelegramClient(SESSION, cr["api_id"], cr["api_hash"]); await c.connect()
    me = await c.get_me(); print("premium:", getattr(me, "premium", None))
    ids = collections.OrderedDict()
    async for m in c.iter_messages("parisvpnn", limit=80):
        for e in (m.entities or []):
            if isinstance(e, types.MessageEntityCustomEmoji):
                ids[e.document_id] = m.raw_text[e.offset:e.offset + e.length]
    print("custom emoji found:", len(ids))
    docs = await c(functions.messages.GetCustomEmojiDocumentsRequest(document_id=list(ids)[:200])) if ids else []
    sets = collections.Counter(); out = []
    for d in docs:
        alt = None; sset = None
        for a in d.attributes:
            if isinstance(a, types.DocumentAttributeCustomEmoji):
                alt = a.alt; sset = a.stickerset
        sid = getattr(sset, "id", None); sets[sid] += 1
        out.append({"id": d.id, "alt": alt, "set_id": sid, "mime": d.mime_type})
    names = {}
    for sid in list(sets)[:30]:
        try:
            r = await c(functions.messages.GetStickerSetRequest(
                stickerset=types.InputStickerSetID(id=sid, access_hash=next(
                    a.stickerset.access_hash for d in docs for a in d.attributes
                    if isinstance(a, types.DocumentAttributeCustomEmoji) and a.stickerset.id == sid)), hash=0))
            names[sid] = (r.set.short_name, r.set.title, r.set.count)
        except Exception as ex:
            names[sid] = ("?", str(ex)[:40], 0)
    for sid, n in sets.most_common():
        print(n, names.get(sid))
    json.dump({"emoji": out, "sets": {str(k): v for k, v in names.items()}}, open("/root/.hermes/ads/stickers/parisvpnn_emoji.json", "w"), ensure_ascii=False, indent=1)
    await c.disconnect()
asyncio.run(main())
