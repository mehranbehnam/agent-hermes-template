"""Builds /root/.hermes/ads/stickers/library.json from animated sticker packs (bot-specific file_ids
for @your_agent_bot). Re-run after adding pack names to PACKS."""
import json, urllib.request, urllib.parse, collections
PACKS = ["AnimatedEmojies", "PremiumGifts", "EmojiAnimations", "AnimatedEmojiPack", "MotionEmoji", "UtyaDuck", "UtyaDuckFull", "HotCherry", "MrCat", "PepeAnimated"]
tok = [l.split("=", 1)[1].strip().strip('"\'') for l in open("/root/.hermes/.env") if l.startswith("TELEGRAM_BOT_TOKEN=")][0]
lib = {"packs": PACKS, "by_emoji": collections.defaultdict(list)}
for name in PACKS:
    r = json.load(urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/getStickerSet",
                                         data=urllib.parse.urlencode({"name": name}).encode(), timeout=20))["result"]
    for s in r["stickers"]:
        if s.get("is_animated") or s.get("is_video"):
            e = (s.get("emoji") or "").replace("️", "")
            lib["by_emoji"][e].append({"file_id": s["file_id"], "pack": name})
json.dump(lib, open("/root/.hermes/ads/stickers/library.json", "w"), ensure_ascii=False, indent=0)
print(sum(len(v) for v in lib["by_emoji"].values()), "stickers,", len(lib["by_emoji"]), "emojis")
