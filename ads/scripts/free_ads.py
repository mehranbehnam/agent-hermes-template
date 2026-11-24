#!/usr/bin/python3
"""HermesVPN ads in FREE, open Iranian ad groups (owner request 2026-11-17).
Posted by the Ads Account userbot. Fully self-cleaning so the owner never has to babysit it
(owner: «وقت منم نگیر»، «شلوغ نکن تایملاین من»):
  1. join     — join a few candidate groups slowly, mute + archive them into the folder FOLDER,
                and post ONE VPN ad as the test (owner: no hello; the ad itself shows if VPN is allowed).
  2. run      — (cron, hourly) first JUDGE: a probe that was deleted / got us restricted, or an ad of ours
                that was deleted within CHECK_MIN, means the group is not really free -> we LEAVE it
                (it disappears from the owner's account). Then post the next ad to PER_RUN groups
                whose probe survived (each group ~1 ad/day).
  3. status   — per group: probe / posts / dropped reason.
State: /root/.hermes/ads/free_state.json  Log: /root/.hermes/ads/stats/free_ads.log
"""
import glob, os, sys, json, random, asyncio, shutil, tempfile, time

_HPY = sorted(glob.glob("/root/.hermes/tools/python*/bin/python3"))[-1]
if os.path.realpath(sys.executable) != os.path.realpath(_HPY):
    os.execv(_HPY, [_HPY, os.path.abspath(__file__)] + sys.argv[1:])
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from telethon import TelegramClient, errors, functions, types
from public_text_guard import check as guard

DIR = "/root/.hermes/ads/posters-divar"
STATE = "/root/.hermes/ads/free_state.json"
SESSION = "/root/.hermes/profiles/adsaccount/userbot/adsaccount"
PER_RUN = 2
CHECK_MIN = 10          # a probe/ad is judged after this many minutes
JOIN_MAX = 8            # joins per 'join' call (Telegram FloodWaits after ~10)
FOLDER = "تبلیغ رایگان"  # Telegram folder titles: max 12 chars
# 2026-11-17 v2: open groups where many different people post daily, no add-N/mute bot messages, and other
# VPN sellers' posts survive. The first list ("divar" groups) was dropped: their bots delete/ban (all left).
GROUPS = [
    "freelancer_proje1", "Do_Zb", "baharartshop", "AccountroChat", "iranbazar_online", "tablighiranonline",
    "group_divar_iran1", "ServerGpp", "Iotuslink11", "tbligatanlainn",
    "freelink_Exchange",
]
DISABLE = (errors.ChatWriteForbiddenError, errors.UserBannedInChannelError, errors.ChannelPrivateError,
           errors.ChatSendMediaForbiddenError, errors.ChatSendPhotosForbiddenError, errors.ChatRestrictedError,
           errors.UsernameNotOccupiedError, errors.UsernameInvalidError, errors.InviteRequestSentError,
           errors.ChannelsTooMuchError)


def log(s):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), s, flush=True)


def load():
    st = json.load(open(STATE)) if os.path.exists(STATE) else {}
    st.setdefault("groups", {})
    for g in GROUPS:
        st["groups"].setdefault(g, {})
        st["groups"][g].setdefault("joined", False)
        st["groups"][g].setdefault("posts", 0)
        st["groups"][g].setdefault("disabled", None)
    return st


def save(st):
    tmp = STATE + ".tmp"
    json.dump(st, open(tmp, "w"), indent=1, ensure_ascii=False)
    os.replace(tmp, STATE)


def ads():
    out = {}
    for t in sorted(glob.glob(os.path.join(DIR, "p*.txt"))):
        base = t[:-4]
        img = next((base + e for e in (".jpg", ".png") if os.path.exists(base + e)), None)
        if img:
            out[os.path.basename(base)] = (img, open(t, encoding="utf-8").read().strip())
    return out


def next_ad(st, names):
    queue = [n for n in st.get("queue", []) if n in names]
    if not queue:
        queue = names[:]
        random.shuffle(queue)
        if len(queue) > 1 and queue[0] == st.get("last_ad"):
            queue[0], queue[1] = queue[1], queue[0]
    return queue[0], queue[1:]


async def client():
    # temp copy of the session: never lock the live file the hourly divar job uses
    d = tempfile.mkdtemp(prefix="freeads-")
    shutil.copy(SESSION + ".session", d + "/s.session")
    cr = json.load(open(SESSION + ".creds.json"))
    c = TelegramClient(d + "/s", cr["api_id"], cr["api_hash"])
    await c.connect()
    if not await c.is_user_authorized():
        log("ERROR userbot session not authorized")
        sys.exit(2)
    return c, d


async def drop(c, st, g, why):
    """Not really free -> leave the group so it vanishes from the owner's account."""
    try:
        await c.delete_dialog(g)
    except Exception as e:
        log(f"FAIL leave {g}: {type(e).__name__}: {e}")
    st["groups"][g].update(joined=False, disabled=f"{why} ({time.strftime('%m-%d %H:%M')})")
    log(f"DROPPED {g}: {why} — left the group")


async def folderize(c, st):
    peers = []
    for g, v in st["groups"].items():
        if v.get("joined"):
            try:
                peers.append(await c.get_input_entity(g))
            except Exception as e:
                log(f"FAIL entity {g}: {type(e).__name__}")
    res = await c(functions.messages.GetDialogFiltersRequest())
    filters = [f for f in getattr(res, "filters", res) if isinstance(f, types.DialogFilter)]
    mine = next((f for f in filters if getattr(f.title, "text", f.title) == FOLDER), None)
    fid = mine.id if mine else max([f.id for f in filters] + [9]) + 1
    if not peers:
        if mine:
            await c(functions.messages.UpdateDialogFilterRequest(id=fid))   # empty folder -> remove it
        return
    await c(functions.messages.UpdateDialogFilterRequest(id=fid, filter=types.DialogFilter(
        id=fid, title=types.TextWithEntities(FOLDER, []), pinned_peers=[], include_peers=peers[:100], exclude_peers=[])))


async def join(st):
    pool = ads()
    name = next_ad(st, sorted(pool))[0]
    img, caption = pool[name]
    if guard(caption):
        sys.exit(f"BLOCKED by public text guard ({name})")
    c, d = await client()
    try:
        todo = [g for g in GROUPS if not st["groups"][g]["joined"] and not st["groups"][g]["disabled"]][:JOIN_MAX]
        for i, g in enumerate(todo):
            try:
                await c(functions.channels.JoinChannelRequest(g))
                p = await c.get_input_entity(g)
                await c(functions.account.UpdateNotifySettingsRequest(
                    peer=types.InputNotifyPeer(p), settings=types.InputPeerNotifySettings(mute_until=2**31 - 1)))
                await c(functions.folders.EditPeerFoldersRequest([types.InputFolderPeer(p, folder_id=1)]))
                st["groups"][g]["joined"] = True
                await asyncio.sleep(random.randint(20, 40))
                # owner 2026-11-17: no hello — the test IS a real VPN ad; if it gets deleted we leave and never post again
                m = await c.send_file(g, img, caption=caption)
                v = st["groups"][g]
                v.update(probe="ok", last=time.strftime("%Y-%m-%d %H:%M"), posts=v["posts"] + 1,
                         ad_msg=m.id, ad_at=time.time(), ad_ok=False)
                log(f"JOINED {g} + test ad {name} msg {m.id}")
            except errors.FloodWaitError as e:
                log(f"STOP join FloodWait {e.seconds}s at {g} — next 'join' continues")
                save(st)
                break
            except DISABLE as e:
                if st["groups"][g]["joined"]:
                    await drop(c, st, g, f"hello refused: {type(e).__name__}")
                else:
                    st["groups"][g]["disabled"] = f"join: {type(e).__name__}"
                    log(f"SKIP {g}: {type(e).__name__}")
            except Exception as e:
                log(f"FAIL join {g}: {type(e).__name__}: {e}")
            save(st)
            if i < len(todo) - 1:
                await asyncio.sleep(random.randint(60, 120))
        await folderize(c, st)
    finally:
        await c.disconnect()
        shutil.rmtree(d, ignore_errors=True)


async def restricted(c, g):
    me = await c.get_me(input_peer=True)
    p = await c.get_permissions(g, me)
    r = getattr(p.participant, "banned_rights", None)
    return bool(getattr(p, "is_banned", False) or (r and (r.send_messages or r.send_media or r.send_photos)))


async def judge(c, st):
    """Drop groups where our hello or our ad was deleted, or where we got muted/banned."""
    changed = False
    for g, v in st["groups"].items():
        if not v.get("joined"):
            continue
        checks = []
        if v.get("probe") == "pending" and time.time() - v.get("probe_at", 0) > CHECK_MIN * 60:
            checks.append(("hello", v["probe_msg"]))
        if v.get("ad_msg") and not v.get("ad_ok") and time.time() - v.get("ad_at", 0) > CHECK_MIN * 60:
            checks.append(("ad", v["ad_msg"]))
        if not checks:
            continue
        try:
            if await restricted(c, g):
                await drop(c, st, g, "muted/banned by the group")
                changed = True
                continue
            for kind, mid in checks:
                if not await c.get_messages(g, ids=mid):
                    await drop(c, st, g, f"our {kind} was deleted")
                    changed = True
                    break
                if kind == "hello":
                    v["probe"] = "ok"
                    log(f"OK {g}: hello survived {CHECK_MIN} min")
                else:
                    v["ad_ok"] = True
                    log(f"OK {g}: ad survived {CHECK_MIN} min")
        except DISABLE as e:
            await drop(c, st, g, f"{type(e).__name__}")
            changed = True
        except Exception as e:
            log(f"FAIL judge {g}: {type(e).__name__}: {e}")
        save(st)
    if changed:
        await folderize(c, st)


async def run(st, dry):
    pool = ads()
    if not pool:
        sys.exit("no ads in " + DIR)
    name, rest = next_ad(st, sorted(pool))
    img, caption = pool[name]
    if guard(caption):
        log(f"BLOCKED by public text guard ({name}): " + "; ".join(guard(caption)))
        sys.exit(3)
    if dry:
        ok = [g for g in GROUPS if st["groups"][g].get("probe") == "ok" and st["groups"][g]["joined"]]
        log(f"next: {name} -> ready groups: {', '.join(ok) or '(none yet)'}")
        return
    c, d = await client()
    try:
        await judge(c, st)
        ready = [g for g in GROUPS if st["groups"][g]["joined"] and st["groups"][g].get("probe") == "ok"
                 and (not st["groups"][g].get("ad_msg") or st["groups"][g].get("ad_ok"))]
        ready.sort(key=lambda g: st["groups"][g].get("last") or "")      # longest-waiting first
        ready = [g for g in ready if time.time() - st["groups"][g].get("ad_at", 0) > 20 * 3600][:PER_RUN]  # ≤ 1 ad / group / 20 h
        sent = 0
        for i, g in enumerate(ready):
            try:
                m = await c.send_file(g, img, caption=caption)
                v = st["groups"][g]
                v.update(last=time.strftime("%Y-%m-%d %H:%M"), posts=v["posts"] + 1, ad_msg=m.id, ad_at=time.time(), ad_ok=False)
                sent += 1
                log(f"SENT {name} -> {g} msg {m.id}")
            except errors.SlowModeWaitError as e:
                log(f"WAIT {g}: slow mode {e.seconds}s — next time")
            except errors.FloodWaitError as e:
                log(f"STOP FloodWait {e.seconds}s at {g}")
                break
            except DISABLE as e:
                await drop(c, st, g, f"send refused: {type(e).__name__}")
                await folderize(c, st)
            except Exception as e:
                log(f"FAIL {g}: {type(e).__name__}: {e}")
            save(st)
            if i < len(ready) - 1:
                await asyncio.sleep(random.randint(40, 90))
        if sent:
            st.update(queue=rest, last_ad=name)
            save(st)
    finally:
        await c.disconnect()
        shutil.rmtree(d, ignore_errors=True)


def status(st):
    g = {k: st["groups"][k] for k in GROUPS}
    print(f"joined {sum(v['joined'] for v in g.values())}/{len(GROUPS)}, hello-ok {sum(v.get('probe') == 'ok' for v in g.values())}, "
          f"dropped {sum(bool(v['disabled']) for v in g.values())}, ads total {sum(v['posts'] for v in g.values())}")
    for k, v in g.items():
        print(f"{k:28s} {'J' if v['joined'] else '-'} hello {v.get('probe') or '-':8s} ads {v['posts']:3d} last {v.get('last') or '-':16s} {v['disabled'] or ''}")


if __name__ == "__main__":
    a = sys.argv[1:]
    st = load()
    if a[:1] == ["join"]:
        asyncio.run(join(st))
    elif a[:1] == ["run"] or "--dry-run" in a:
        asyncio.run(run(st, "--dry-run" in a))
    elif a[:1] == ["status"]:
        status(st)
    else:
        sys.exit(__doc__)
