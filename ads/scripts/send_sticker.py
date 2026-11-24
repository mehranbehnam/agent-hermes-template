"""Send an animated sticker as Ads Account (userbot).
usage: send_sticker.py <target> <emoji|mood|random> [--count N] [--pack NAME_or_t.me/addstickers/LINK]
emoji "random" = random big animated emoji (hundreds, no repeats). Packs: AnimatedEmojies, EmojiAnimations, AnimatedEmojiPack, MotionEmoji (big animated emoji, default), UtyaDuck, UtyaDuckFull, HotCherry, MrCat, PepeAnimated."""
import glob, os, sys, asyncio, json, random
_HPY = sorted(glob.glob("/root/.hermes/tools/python*/bin/python3"))[-1]
if os.path.realpath(sys.executable) != os.path.realpath(_HPY):  # run with Hermes' own Python (telethon lives there)
    os.execv(_HPY, [_HPY, os.path.abspath(__file__)] + sys.argv[1:])
BASE = os.path.dirname(sorted(glob.glob("/root/.hermes/tools/python*/bin/python3"))[-1])
sys.path.insert(0, os.path.join(os.path.dirname(BASE), "lib", "python3.14", "site-packages"))
from telethon import TelegramClient, functions, types
SESSION = "/root/.hermes/profiles/adsaccount/userbot/adsaccount"
MOODS = {"hello": "👋", "thanks": "🙏", "love": "❤", "fire": "🔥", "rocket": "🚀", "gift": "🎁", "ok": "👍",
         "done": "✅", "laugh": "😂", "sad": "😢", "money": "💰", "party": "🎉", "cool": "😎", "wow": "😍",
         "think": "🤔", "fast": "⚡", "bot": "🤖", "vip": "💎"}


BIG_PACKS = ["AnimatedEmojies", "EmojiAnimations", "AnimatedEmojiPack", "MotionEmoji"]  # PremiumGifts: premium-only for user accounts (bots can send it)
# never used in ads: negative / rude / violent emojis
BLOCK = set("😢😭😡🤬💩🖕🤮🤢💀☠👿😈🔪🔫💣🩸🍆🍑💦👅😱😨😰😥😓😞😔😟😠😤🤯🥵🥶😵🤒🤕😷🤧⚰🪦💔😒🙄😬😐😑😶🤐🤥😪😴🥱👎🤡👺👹🧟🦠💉💊🚬🍺🍷🍸🥃🍻🥂🎰🔞")
STATE = "/root/.hermes/ads/stickers/sticker_state.json"
# Owner (2026-10-24): ads get ONLY celebration / launch / promo stickers — explosions, fireworks,
# balloons, sparkle, gifts, trophies, money, rockets. No funny faces or hands.
FESTIVE = {e.replace("\ufe0f", "") for e in
           "🎉 🎊 🥳 🎈 🎆 🎇 ✨ 💥 🔥 🚀 ⚡ 🎁 💎 🏆 🥇 👑 🌟 ⭐ 💫 💯 ✅ 🔝 🆕 🆓 📣 📢 🛍 💰 💸 🤑 "
           "🎀 🪅 🧨 🎖 🏅 ❤️‍🔥 🔔 🆙 🪄 🎟 🎫 🏁 🌈".split()}


async def pick_random_ad(c, keep=40):
    """Random big animated emoji for ads, no repeats among the last `keep` sends."""
    try:
        state = json.load(open(STATE))
    except Exception:
        state = {"recent": []}
    pool = []
    for name in BIG_PACKS:
        try:
            r = await c(functions.messages.GetStickerSetRequest(stickerset=types.InputStickerSetShortName(name), hash=0))
        except Exception:
            continue
        alt = {}
        for p in r.packs:
            for d in p.documents:
                alt[d] = p.emoticon.replace("\ufe0f", "")
        pool += [d for d in r.documents if alt.get(d.id, "") in FESTIVE]
    fresh = [d for d in pool if d.id not in state["recent"]] or pool
    doc = random.choice(fresh) if fresh else None
    if doc:
        state["recent"] = (state["recent"] + [doc.id])[-keep:]
        json.dump(state, open(STATE, "w"))
    return doc


async def pick(c, emoji, packs):
    if emoji in ("random", "ad", "any", "festive"):
        return await pick_random_ad(c)
    emoji = MOODS.get(emoji.lower(), emoji).replace("️", "")
    fallback = []
    for name in packs:
        r = await c(functions.messages.GetStickerSetRequest(stickerset=types.InputStickerSetShortName(name), hash=0))
        alts = {}
        for p in r.packs:
            for d in p.documents:
                alts[d] = p.emoticon.replace("️", "")
        hits = [d for d in r.documents if alts.get(d.id) == emoji]
        if hits:
            return random.choice(hits)
        fallback += r.documents
    return random.choice(fallback) if fallback else None


async def send(c, target, emoji, packs=("AnimatedEmojies", "EmojiAnimations", "AnimatedEmojiPack", "MotionEmoji", "UtyaDuck", "HotCherry")):
    packs = [p for p in packs if p != "PremiumGifts"]   # the userbot is not premium
    for _ in range(4):
        doc = await pick(c, emoji, packs)
        if not doc:
            return False
        try:
            await c.send_file(target, doc)
            return True
        except Exception as e:   # premium-only sticker etc. -> try another
            if "Premium" not in type(e).__name__:
                raise
    return False


ALL_PACKS = BIG_PACKS + ["UtyaDuck", "UtyaDuckFull", "HotCherry", "MrCat", "PepeAnimated"]


def pack_name(x):
    """accepts a short name or a t.me/addstickers/<name> link"""
    x = x.strip().rstrip("/")
    return x.split("/addstickers/")[-1].split("/")[-1] if "addstickers" in x else x


async def pick_any(c, emoji, packs):
    """Custom order: exact emoji from the given/known packs, else Telegram's own sticker search."""
    doc = None
    try:
        doc = await pick(c, emoji, packs) if emoji not in ("random", "ad", "any", "festive") else await pick_random_ad(c)
        if doc is not None and emoji not in ("random", "ad", "any", "festive"):
            # pick() falls back to a random sticker when the emoji is missing; verify the match
            alts = [a.alt for a in doc.attributes if hasattr(a, "alt")]
            want = MOODS.get(emoji.lower(), emoji).replace("\ufe0f", "")
            if alts and want not in [x.replace("\ufe0f", "") for x in alts]:
                doc = None
    except Exception as e:
        print("pack lookup failed:", e)
    if doc is None and emoji not in ("random", "ad", "any", "festive"):
        want = MOODS.get(emoji.lower(), emoji)
        r = await c(functions.messages.GetStickersRequest(emoticon=want, hash=0))
        docs = getattr(r, "stickers", []) or []
        anim = [d for d in docs if d.mime_type in ("application/x-tgsticker", "video/webm")] or docs
        doc = random.choice(anim) if anim else None
    return doc


async def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("target", help="your_channel | your_group | @username | numeric id")
    ap.add_argument("emoji", help="emoji, mood word (rocket/fire/gift/...), or random (festive ad sticker)")
    ap.add_argument("pack_pos", nargs="?", help="optional pack name (legacy positional)")
    ap.add_argument("--count", type=int, default=1, help="how many stickers (1-10)")
    ap.add_argument("--pack", help="sticker pack short name or t.me/addstickers/... link")
    a = ap.parse_args()
    packs = [pack_name(a.pack or a.pack_pos)] if (a.pack or a.pack_pos) else ALL_PACKS
    n = max(1, min(10, a.count))
    cr = json.load(open(SESSION + ".creds.json"))
    c = TelegramClient(SESSION, cr["api_id"], cr["api_hash"])
    await c.connect()
    tgt = int(a.target) if a.target.lstrip("-").isdigit() else a.target
    sent, used = 0, set()
    for _ in range(n):
        doc = None
        for _try in range(4):
            doc = await pick_any(c, a.emoji, packs)
            if doc is None or doc.id not in used:
                break
        if doc is None:
            break
        used.add(doc.id)
        try:
            await c.send_file(tgt, doc)
        except Exception as e:   # premium-only sticker for this non-premium account -> pick another
            if "Premium" in type(e).__name__:
                continue
            raise
        sent += 1
        await asyncio.sleep(0.7)
    await c.disconnect()
    print(f"sent {sent} sticker(s) to {a.target}" if sent else "no sticker found for that emoji/pack")


if __name__ == "__main__":
    asyncio.run(main())
