"""Ignore the owner's own posting accounts in groups/channels.

@your_support_account (100000001) posts the scheduled HermesVPN ads into
@your_group via the userbot; without this the bot answered those ads.
Only group/channel traffic is dropped — DMs from the same account still reach
the adsaccount profile. The bot's own messages are already dropped by the
Telegram adapter (_is_own_message).
"""
import logging
import re

logger = logging.getLogger(__name__)

IGNORED_GROUP_SENDERS = {"100000001", "100000002", "100000002"}   # Owner userbot + @your_agent_bot + @your_second_agent_bot (their own ads)  # @your_support_account (userbot ad poster)

# --- Moderation of the public HERMES VPN GROUP (owner request 2026-10-24) ---
# Profanity or a foreign link from a non-admin -> delete message, ban sender, DM the owner.
MODERATED_CHATS = {"-1004353962033", "-1003819353196"}   # your_group + iranvpngroup
OWNER_NOTIFY_CHAT = 100000001
EXEMPT_USERS = {"100000001", "100000001", "100000002"}
ALLOWED_LINK_PARTS = ("t.me/your_channel", "t.me/your_group", "t.me/your_sales_bot",
                      "telegram.me/your_channel", "telegram.me/your_group", "telegram.me/your_sales_bot",
                      "example.com")
_LINK_RE = re.compile(
    r"(https?://\S+|www\.\S+|(?:t|telegram)\.me/\S+|tg://\S+|"
    r"\b[\w-]+\.(?:com|ir|net|org|me|io|xyz|info|link|site|top|app|online|shop|live|click|vip|pro|cc|co|tk|ru)\b(?:/\S*)?)",
    re.IGNORECASE)
_BAD_WORDS = {
    "کیر", "کیری", "کیرم", "کیرت", "کص", "کسکش", "کصکش", "کسکیش", "کسخل", "کصخل", "کسخول", "کسشر", "کصشر",
    "کون", "کونی", "کونده", "جنده", "جندە", "مادرجنده", "جاکش", "دیوث", "حرومزاده", "حرامزاده", "حرومی",
    "لاشی", "بیناموس", "پفیوز", "گاییدم", "گاییدمت", "بگام", "بگامت", "گوه", "سیکتیر", "ننتو", "ننتم",
    "kir", "kiri", "kos", "kus", "koskesh", "kuskesh", "kosher", "kesafat", "kooni", "jende", "jendeh",
    "madarjende", "jakesh", "dayus", "harumzade", "haromzade", "lashi", "binamus", "gaeidam", "gayidam",
    "fuck", "fucking", "fucker", "motherfucker", "bitch", "asshole", "dick", "pussy",
}
_BAD_STEMS = ("کسکش", "کصکش", "جنده", "مادرجنده", "گایید", "حرومزاده", "حرامزاده", "کسخل", "کسشر", "کصشر",
              "koskesh", "jende", "madarjende", "fuck")
_admin_cache = {}  # (chat_id, user_id) -> (is_admin, ts)


def _normalize_fa(text):
    t = (text or "").replace("ي", "ی").replace("ك", "ک").replace("ة", "ه")
    t = re.sub("[‌‍ـً-ٟ]", "", t)          # ZWNJ, tatweel, diacritics
    t = re.sub(r"(.)\1{2,}", r"\1", t.lower())                       # کیییییر -> کیر
    return t


def _has_profanity(text):
    norm = _normalize_fa(text)
    for tok in re.findall(r"[\w]+", norm):
        if tok in _BAD_WORDS or any(tok.startswith(st) for st in _BAD_STEMS):
            return True
    joined = re.sub(r"[\s\W_]+", "", norm)                           # "ک ی ر" / "مادر جنده"
    return any(w in joined for w in ("مادرجنده", "کسکش", "کصکش", "madarjende", "motherfucker"))


def _foreign_links(message, text):
    found = [m.group(0) for m in _LINK_RE.finditer(text or "")]
    for ents, body in ((getattr(message, "entities", None), getattr(message, "text", None)),
                       (getattr(message, "caption_entities", None), getattr(message, "caption", None))):
        for e in ents or ():
            etype = str(getattr(e, "type", "")).lower()
            if etype.endswith("text_link") and getattr(e, "url", None):
                found.append(e.url)
            elif etype.endswith("url") and body:
                found.append(body[e.offset:e.offset + e.length])
    return [u for u in found if not any(a in u.lower() for a in ALLOWED_LINK_PARTS)]


async def _is_admin(bot, chat_id, user_id):
    import time
    key = (chat_id, user_id)
    hit = _admin_cache.get(key)
    if hit and time.time() - hit[1] < 600:
        return hit[0]
    try:
        member = await bot.get_chat_member(chat_id=int(chat_id), user_id=int(user_id))
        is_admin = str(getattr(member, "status", "")).lower().split(".")[-1] in ("administrator", "creator", "owner")
    except Exception:
        logger.warning("moderation: get_chat_member failed for %s in %s", user_id, chat_id, exc_info=True)
        return True  # unsure -> never ban
    _admin_cache[key] = (is_admin, time.time())
    return is_admin


async def _moderate(event, source):
    """Return True when the message was removed and the sender banned."""
    chat_id = str(getattr(source, "chat_id", ""))
    user_id = str(getattr(source, "user_id", "") or "")
    message = getattr(event, "raw_message", None)
    if chat_id not in MODERATED_CHATS or not user_id or user_id in EXEMPT_USERS or message is None:
        return False
    text = "\n".join(x for x in (getattr(event, "text", None), getattr(message, "text", None),
                                  getattr(message, "caption", None)) if x)
    reason = None
    if _has_profanity(text):
        reason = "فحاشی"
    else:
        links = _foreign_links(message, text)
        if links:
            reason = "لینک: " + links[0][:80]
    if not reason:
        return False
    try:
        bot = message.get_bot()
    except Exception:
        logger.warning("moderation: no bot handle on message", exc_info=True)
        return False
    if await _is_admin(bot, chat_id, user_id):
        return False
    name = getattr(source, "user_name", None) or user_id
    try:
        await bot.delete_message(chat_id=int(chat_id), message_id=int(message.message_id))
    except Exception:
        logger.warning("moderation: delete failed", exc_info=True)
    banned = False
    try:
        await bot.ban_chat_member(chat_id=int(chat_id), user_id=int(user_id), revoke_messages=True)
        banned = True
    except Exception:
        logger.warning("moderation: ban failed for %s", user_id, exc_info=True)
    logger.warning("moderation: chat=%s user=%s (%s) reason=%s banned=%s", chat_id, user_id, name, reason, banned)
    try:
        await bot.send_message(
            chat_id=OWNER_NOTIFY_CHAT,
            text=(f"🚫 گروه HERMES VPN: کاربر {name} (ID {user_id}) "
                  f"{'بن و حذف شد' if banned else 'پیامش پاک شد ولی بن نشد'}.\n"
                  f"دلیل: {reason}\nمتن: {text[:200]}"))
    except Exception:
        logger.warning("moderation: owner notify failed", exc_info=True)
    return True


async def _on_pre_gateway_dispatch(event=None, **_kwargs):
    source = getattr(event, "source", None)
    if source is None:
        return None
    platform = getattr(getattr(source, "platform", None), "value", getattr(source, "platform", None))
    if str(platform) != "telegram":
        return None
    if str(getattr(source, "chat_type", "dm")) == "dm":
        return None
    if str(getattr(source, "user_id", "")) in IGNORED_GROUP_SENDERS:
        # Safety net: a self-made "sticker" (no sticker set) or a webp/gif file from the ad
        # account in the public group is deleted on sight. Real pack stickers have a set_name.
        try:
            msg = getattr(event, "raw_message", None)
            st = getattr(msg, "sticker", None)
            doc = getattr(msg, "document", None)
            fake = (st is not None and not getattr(st, "set_name", None)) or (
                doc is not None and str(getattr(doc, "mime_type", "")).lower() in ("image/webp", "image/gif", "video/webm"))
            if fake and str(getattr(source, "chat_id", "")) in MODERATED_CHATS:
                await msg.get_bot().delete_message(chat_id=int(source.chat_id), message_id=int(msg.message_id))
                logger.warning("deleted self-made sticker/file from ad account in group: msg=%s", msg.message_id)
        except Exception:
            logger.warning("fake-sticker cleanup failed", exc_info=True)
        return {"action": "skip", "reason": "own ad account in group"}
    try:
        if await _moderate(event, source):
            return {"action": "skip", "reason": "moderated: profanity/link"}
    except Exception:
        logger.warning("moderation failed", exc_info=True)
    # Public group: the support persona answers [SILENT] for chit-chat. Without this the
    # gateway treats every group message as needing a reply and posts the English
    # "model returned only a silence marker" warning into the group.
    if str(getattr(source, "chat_id", "")) in MODERATED_CHATS:
        _pending_group_msgs.append((str(source.chat_id), getattr(event, "message_id", None), _time.time()))
        try:
            event.reply_expected = False
        except Exception:
            logger.warning("could not mark reply_expected=False", exc_info=True)
    return None


# --- Animated stickers in group replies (owner request 2026-10-24) ---
# The group persona may end a reply with [STICKER:🚀] (an emoji or a mood word). The marker is
# stripped from the text and an animated sticker for that emoji is sent to the group a few
# seconds after the text. Library: /root/.hermes/ads/stickers/library.json (bot file_ids).
import collections, json as _json, os as _os, random as _random, threading as _threading, time as _time
import urllib.parse as _uparse, urllib.request as _ureq

STICKER_LIBRARY = "/root/.hermes/ads/stickers/library.json"
_STICKER_RE = re.compile(r"\s*\[\s*STICKER\s*:\s*([^\]\n]{1,24})\]\s*", re.IGNORECASE)
_MOODS = {"hello": "👋", "hi": "👋", "salam": "👋", "thanks": "🙏", "love": "❤", "heart": "❤", "fire": "🔥",
          "hot": "🔥", "rocket": "🚀", "speed": "🚀", "gift": "🎁", "ok": "👍", "done": "✅", "laugh": "😂",
          "sad": "😢", "sorry": "😢", "money": "💰", "party": "🎉", "cool": "😎", "wow": "😍", "think": "🤔",
          "fast": "⚡", "bot": "🤖", "vip": "💎", "lock": "🔒"}
_BIG_PACKS = {"AnimatedEmojies", "EmojiAnimations", "AnimatedEmojiPack", "MotionEmoji", "PremiumGifts"}
_pending_group_msgs = collections.deque(maxlen=50)  # (chat_id, message_id, ts)
_lib_cache = {"mtime": 0, "data": {}}


def _sticker_lib():
    try:
        m = _os.path.getmtime(STICKER_LIBRARY)
        if m != _lib_cache["mtime"]:
            _lib_cache["data"] = _json.load(open(STICKER_LIBRARY)).get("by_emoji", {})
            _lib_cache["mtime"] = m
    except Exception:
        logger.warning("sticker library unreadable", exc_info=True)
    return _lib_cache["data"]


_FESTIVE = {e.replace("\ufe0f", "") for e in
             "🎉 🎊 🥳 🎈 🎆 🎇 ✨ 💥 🔥 🚀 ⚡ 🎁 💎 🏆 🥇 👑 🌟 ⭐ 💫 💯 ✅ 🔝 🆕 🆓 📣 📢 🛍 💰 💸 🤑 "
             "🎀 🪅 🧨 🎖 🏅 ❤️‍🔥 🔔 🆙 🪄 🎟 🎫 🏁 🌈".split()}


def _pick_sticker(key):
    key = (key or "").strip().lower().replace("️", "")
    emoji = _MOODS.get(key, key)
    lib = _sticker_lib()
    if emoji not in _FESTIVE:   # owner: only celebration/promo stickers, no funny faces/hands
        pool = [x for e in _FESTIVE for x in lib.get(e, []) if x.get("pack") in _BIG_PACKS]
        return _random.choice(pool)["file_id"] if pool else None
    choices = lib.get(emoji) or lib.get(_MOODS.get("ok"), [])
    big = [x for x in choices if x.get("pack") in _BIG_PACKS]   # owner likes the big animated emoji style
    choices = big or choices
    return _random.choice(choices)["file_id"] if choices else None


def _bot_token():
    tok = _os.environ.get("TELEGRAM_BOT_TOKEN")
    if tok:
        return tok
    try:
        for line in open("/root/.hermes/.env"):
            if line.startswith("TELEGRAM_BOT_TOKEN="):
                return line.split("=", 1)[1].strip().strip("\"'")
    except Exception:
        return None


def _send_sticker_later(chat_id, file_id, reply_to=None, delay=3.0):
    def run():
        tok = _bot_token()
        if not tok:
            return
        data = {"chat_id": chat_id, "sticker": file_id}
        if reply_to:
            data["reply_parameters"] = _json.dumps({"message_id": int(reply_to), "allow_sending_without_reply": True})
        try:
            _ureq.urlopen(f"https://api.telegram.org/bot{tok}/sendSticker",
                          data=_uparse.urlencode(data).encode(), timeout=15).read()
        except Exception:
            logger.warning("sendSticker failed chat=%s", chat_id, exc_info=True)
    t = _threading.Timer(delay, run)
    t.daemon = True
    t.start()


_BUY_RE = re.compile(r"\s*\[\s*BUY\s*\]\s*", re.IGNORECASE)


def _send_buy_buttons_later(chat_id, delay=1.5):
    """Owner item: buy / free-trial buttons under price & purchase answers in the group."""
    def run():
        tok = _bot_token()
        if not tok:
            return
        kb = {"inline_keyboard": [[{"text": "🛒 خرید آنی", "url": "https://t.me/your_sales_bot?start=buy"},
                                   {"text": "🧪 تست رایگان", "url": "https://t.me/your_sales_bot?start=trial"}]]}
        try:
            _ureq.urlopen(f"https://api.telegram.org/bot{tok}/sendMessage", data=_uparse.urlencode(
                {"chat_id": chat_id, "text": "👇 خرید آنی یا تست رایگان ۵۰۰ مگ / ۲۴ ساعت:",
                 "reply_markup": _json.dumps(kb)}).encode(), timeout=15).read()
        except Exception:
            logger.warning("buy buttons failed chat=%s", chat_id, exc_info=True)
    t = _threading.Timer(delay, run)
    t.daemon = True
    t.start()


def _handle_sticker_markers(text):
    markers = _STICKER_RE.findall(text or "")
    buy = bool(_BUY_RE.search(text or ""))
    if not markers and not buy:
        return None
    clean = _BUY_RE.sub(" ", _STICKER_RE.sub(" ", text)).strip()
    now = _time.time()
    target = None
    while _pending_group_msgs:
        chat_id, msg_id, ts = _pending_group_msgs.pop()   # newest first
        if now - ts < 300:
            target = (chat_id, msg_id)
            break
    if target:
        if buy:
            _send_buy_buttons_later(int(target[0]))
        if markers:
            fid = _pick_sticker(markers[0])
            if fid:
                _send_sticker_later(int(target[0]), fid)
    return clean or "[SILENT]"


# The group-support persona answers [SILENT] for chit-chat; models sometimes
# misspell it ("[silient]"), which would then be posted to the group verbatim.
_SILENT_TYPO = re.compile(r"^\W*(s[il]{1,3}e?n?t|si?l[ie]{1,2}n?t|no[ _]?reply)\W*$", re.IGNORECASE)


def _on_transform_llm_output(response_text=None, **_kwargs):
    try:
        cleaned = _handle_sticker_markers(response_text)
    except Exception:
        logger.warning("sticker marker handling failed", exc_info=True)
        cleaned = None
    if cleaned is not None:
        return cleaned
    text = (response_text or "").strip()
    if text and len(text) <= 16 and _SILENT_TYPO.match(text):
        return "[SILENT]"
    return None


# --- Hard block: the agent must never fabricate stickers/posters (owner, 2026-10-24) ---
# Twice it drew its own WebP "stickers" with ffmpeg/PIL and posted them to the channel/group.
# Real animated stickers come only from /root/.hermes/ads/scripts/send_sticker.py / auto_ads.py.
_MAKE_RE = re.compile(r"ffmpeg|libwebp|imagedraw|image\.new\(|lottie|rlottie|gifsicle|imagemagick|\bmagick\b|"
                      r"make_sticker|create_sticker|\.webp\b|\.gif\b|\.tgs\b|\.webm\b", re.IGNORECASE)
_TOPIC_RE = re.compile(r"sticker|استیکر|your_channel|your_group|poster|پوستر|webp|tgs", re.IGNORECASE)
_BLOCK_MSG = ("BLOCKED by owner policy: never create or post self-made stickers, WebP/GIF/TGS or images. "
              "For ads + animated stickers run exactly: /root/.hermes/tools/python-3.14.7+20260901-linux-x64/bin/python3 "
              "/root/.hermes/ads/scripts/auto_ads.py   (single sticker: .../send_sticker.py <target> random). "
              "Tell Owner you used the ready-made script.")


def _on_pre_tool_call(tool_name=None, args=None, **_kwargs):
    try:
        blob = _json.dumps(args, ensure_ascii=False) if not isinstance(args, str) else args
    except Exception:
        blob = str(args)
    if "/root/.hermes/ads/scripts/" in blob and not _re_has_generation(blob):
        return None
    if _MAKE_RE.search(blob) and _TOPIC_RE.search(blob):
        logger.warning("blocked self-made sticker/image tool call: tool=%s", tool_name)
        return {"action": "block", "message": _BLOCK_MSG}
    return None


def _re_has_generation(blob):
    return bool(re.search(r"ffmpeg|imagedraw|image\.new\(|lottie|make_sticker", blob, re.IGNORECASE))


def register(ctx) -> None:
    ctx.register_hook("pre_tool_call", _on_pre_tool_call)
    ctx.register_hook("pre_gateway_dispatch", _on_pre_gateway_dispatch)
    ctx.register_hook("transform_llm_output", _on_transform_llm_output)
