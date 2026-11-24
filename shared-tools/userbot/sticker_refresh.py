"""Install NEW / trending stickers, animated custom emoji and GIFs on the owner's accounts (owner request 2026-11-13).
Source of «new & popular» = Telegram's own Trending lists (GetFeaturedStickers / GetFeaturedEmojiStickers, newest first),
plus the packs Owner's account has and the ad library, plus trending GIFs from @gif. Installing is personal-use only.

  sticker_refresh.py <session> [--stickers N] [--emoji N] [--gifs N] [--replace]   (--replace: may push oldest saved GIFs out)
Animated / video packs first. Never removes anything the user installed; GIFs are only added while there is room
(Telegram keeps max 200 saved GIFs for non-Premium and drops the oldest otherwise — so we never push his own GIFs out).
Stops on a long FloodWait. Prints one JSON summary.
"""
import asyncio, json, random, shutil, sys, tempfile
from telethon import TelegramClient, errors, functions, types

LIB_PACKS = ["AnimatedEmojies", "PremiumGifts", "EmojiAnimations", "AnimatedEmojiPack", "MotionEmoji", "UtyaDuck", "UtyaDuckFull",
             "HotCherry", "MrCat", "PepeAnimated"]
GIF_QUERIES = ["wow", "omg", "celebrate", "party", "congratulations", "fire", "applause", "thank you", "love", "happy",
               "dance", "excited", "yes", "cool", "money", "sale", "new", "surprise", "amazing", "hello", "welcome", "lets go"]


def arg(name, default):
    return int(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default


def is_motion(doc):
    return getattr(doc, "mime_type", "") in ("application/x-tgsticker", "video/webm")


async def main():
    sess = sys.argv[1]
    n_st, n_em, n_gif = arg("--stickers", 100), arg("--emoji", 60), arg("--gifs", 150)
    cr = json.load(open(sess + ".creds.json"))
    tmp = tempfile.mkdtemp()
    shutil.copy2(sess + ".session", tmp + "/s.session")         # copy: never lock the live session file
    c = TelegramClient(tmp + "/s", cr["api_id"], cr["api_hash"])
    await c.connect()
    res = {"stickers": 0, "emoji": 0, "gifs": 0, "skipped": 0, "errors": 0, "stopped": None}

    async def install(inp):
        try:
            await c(functions.messages.InstallStickerSetRequest(stickerset=inp, archived=False))
            await asyncio.sleep(random.uniform(1.2, 2.2))
            return True
        except errors.FloodWaitError as e:
            if e.seconds > 90:
                res["stopped"] = f"FloodWait {e.seconds}s"
                raise
            await asyncio.sleep(e.seconds + 2)
            return await install(inp)
        except Exception as e:
            res["errors"] += 1
            print(f"install failed: {type(e).__name__}: {e}", file=sys.stderr)
            return False

    try:
        have = {s.id for s in (await c(functions.messages.GetAllStickersRequest(hash=0))).sets}
        have |= {s.id for s in (await c(functions.messages.GetEmojiStickersRequest(hash=0))).sets}
        # 1) stickers: library + Owner's packs first, then Trending (animated/video first, Telegram's order = newest)
        cand = [types.InputStickerSetShortName(n) for n in LIB_PACKS]
        feat = list(getattr(await c(functions.messages.GetFeaturedStickersRequest(hash=0)), "sets", []))   # Trending, newest first
        motion = [s for s in feat if (getattr(s, "cover", None) and is_motion(s.cover)) or
                  any(is_motion(d) for d in (getattr(s, "covers", None) or []))]
        static = [s for s in feat if s not in motion]
        for s in motion + static:
            if s.set.id not in have:
                cand.append(types.InputStickerSetID(id=s.set.id, access_hash=s.set.access_hash))
        done = 0
        for inp in cand:
            if done >= n_st:
                break
            if isinstance(inp, types.InputStickerSetShortName):
                try:
                    full = await c(functions.messages.GetStickerSetRequest(stickerset=inp, hash=0))
                    if full.set.id in have:
                        continue
                except Exception:
                    res["skipped"] += 1
                    continue
            if await install(inp):
                done += 1
                have.add(getattr(inp, "id", None))
        res["stickers"] = done
        # 2) animated custom emoji packs (Trending emoji)
        fe = await c(functions.messages.GetFeaturedEmojiStickersRequest(hash=0))
        done = 0
        for s in fe.sets:
            if done >= n_em:
                break
            if s.set.id in have:
                continue
            if await install(types.InputStickerSetID(id=s.set.id, access_hash=s.set.access_hash)):
                done += 1
        res["emoji"] = done
        # 3) trending GIFs from @gif, only while there is room (never push the user's own GIFs out)
        saved = await c(functions.messages.GetSavedGifsRequest(hash=0))
        # --replace (owner OK'd for his 2nd account): new GIFs may push his oldest saved GIFs out
        room = n_gif if "--replace" in sys.argv else max(0, min(n_gif, 200 - len(saved.gifs)))
        have_g = {g.id for g in saved.gifs}
        bot = await c.get_input_entity("gif")
        added = 0
        queries = sys.argv[sys.argv.index("--gif-queries") + 1].split(",") if "--gif-queries" in sys.argv else GIF_QUERIES
        for q in queries:
            if added >= room:
                break
            try:
                br = await c(functions.messages.GetInlineBotResultsRequest(bot=bot, peer="me", query=q, offset=""))
            except Exception as e:
                print(f"gif search {q}: {e}", file=sys.stderr)
                continue
            for it in br.results[:arg("--per-query", 8)]:
                doc = getattr(it, "document", None)
                if added >= room or not doc or doc.id in have_g:
                    continue
                try:
                    await c(functions.messages.SaveGifRequest(id=types.InputDocument(id=doc.id, access_hash=doc.access_hash,
                                                                                     file_reference=doc.file_reference), unsave=False))
                    have_g.add(doc.id)
                    added += 1
                    await asyncio.sleep(random.uniform(0.6, 1.2))
                except errors.FloodWaitError as e:
                    res["stopped"] = f"FloodWait {e.seconds}s (gifs)"
                    break
                except Exception as e:
                    res["errors"] += 1
                    print(f"save gif: {type(e).__name__}", file=sys.stderr)
            if res["stopped"]:
                break
        res["gifs"] = added
        res["gif_room_left"] = room - added
    except errors.FloodWaitError:
        pass
    finally:
        await c.disconnect()
        shutil.rmtree(tmp, ignore_errors=True)
    print(json.dumps(res, ensure_ascii=False))


asyncio.run(main())
