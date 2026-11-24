#!/usr/bin/python3
"""HermesVPN ads in the third-party ad groups @example_ad_group + @example_ad_group2
(owner-approved set, 2026-11-08; second group added 2026-11-14 by owner request).
One poster + its EXACT caption per run, posted by the Ads Account userbot. No sticker (someone else's group).
Both groups get the SAME ad in the SAME run (mirror pattern).
Order: random shuffle per cycle, every ad once before any repeats, never the same ad twice in a row
(also across cycle boundaries). Ads = /root/.hermes/ads/posters-divar/pNN-name.{jpg,png} + pNN-name.txt;
an ad without a poster is skipped until its poster arrives.
  divar_ads.py            # post the next ad to all targets
  divar_ads.py --dry-run  # show the next ad, send nothing, don't advance
State: /root/.hermes/ads/divar_state.json. Exit 0 = sent, 1 = failed, 2 = session, 3 = guard, 4 = slow mode/flood wait.
"""
import glob, os, sys, json, random, asyncio, urllib.request

_HPY = sorted(glob.glob("/root/.hermes/tools/python*/bin/python3"))[-1]
if os.path.realpath(sys.executable) != os.path.realpath(_HPY):
    os.execv(_HPY, [_HPY, os.path.abspath(__file__)] + sys.argv[1:])
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from telethon import TelegramClient, errors
from public_text_guard import check as guard

# Owner-approved 2026-11-17: tell the Oracle fallback (HermesVPN session) that Hetzner posted, so its :07 backup
# skips even if group admins delete our post. Best-effort: never blocks or fails the post.
HEARTBEAT = "https://hook.example.com:2087/hb/divar?id={}"


def heartbeat(msg_id):
    try:
        with urllib.request.urlopen(HEARTBEAT.format(msg_id), timeout=10) as r:
            print(f"[divar] heartbeat -> oracle HTTP {r.status}")
    except Exception as e:
        print(f"[divar] heartbeat failed (ignored): {type(e).__name__}: {e}")


DIR = "/root/.hermes/ads/posters-divar"
STATE = "/root/.hermes/ads/divar_state.json"
SESSION = "/root/.hermes/profiles/adsaccount/userbot/adsaccount"
TARGET = "example_ad_group"
# Group #2 (owner request 2026-11-14): same ad, same run, mirror pattern.
# example_ad_group2 currently blocks this account (anti-spam bot deletes/bans the
# sender), so it is disabled until the owner gets send permission there.
TARGETS = [
    ("example_ad_group", True),
    ("example_ad_group2", False),
]


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
        if len(queue) > 1 and queue[0] == st.get("last"):
            queue[0], queue[1] = queue[1], queue[0]
    return queue[0], queue[1:]


async def main():
    dry = "--dry-run" in sys.argv
    st = json.load(open(STATE)) if os.path.exists(STATE) else {}
    pool = ads()
    if not pool:
        sys.exit("no ads in " + DIR)
    name, rest = next_ad(st, sorted(pool))
    img, caption = pool[name]
    if guard(caption):
        print(f"BLOCKED by public text guard ({name}): " + "; ".join(guard(caption)))
        sys.exit(3)
    if dry:
        print("next: %s (%d left in this cycle) -> %s" % (
            name, len(rest),
            ", ".join(t for t, on in TARGETS if on) or "(none enabled)"))
        return
    cr = json.load(open(SESSION + ".creds.json"))
    c = TelegramClient(SESSION, cr["api_id"], cr["api_hash"])
    sent = {}
    failed = []
    await c.connect()
    try:
        if not await c.is_user_authorized():
            print("ERROR: userbot session not authorized")
            sys.exit(2)
        for t, enabled in TARGETS:
            if not enabled:
                continue
            try:
                m = await c.send_file(t, img, caption=caption)
                sent[t] = getattr(m, "id", None)
                print(f"[divar] sent {name} -> {t} msg {sent[t]}")
                if t == "example_ad_group":
                    heartbeat(sent[t])
            except (errors.SlowModeWaitError, errors.FloodWaitError) as e:
                print(f"WAIT {name} -> {t}: {type(e).__name__} {e.seconds}s — not sent, will retry next run")
                failed.append(t)
            except Exception as e:
                print(f"ERROR {name} -> {t}: {type(e).__name__}: {e}")
                failed.append(t)
    finally:
        await c.disconnect()
    if not sent:
        print("nothing sent")
        sys.exit(1)
    # Advance the cycle as long as every ENABLED target got the ad.
    # A disabled target can't block the rotation; a failing enabled one retries next run.
    if failed:
        print(f"not advanced (failed: {', '.join(failed)})")
        sys.exit(1)
    st.update({"queue": rest, "last": name, "last_msg": sent.get(TARGETS[0][0]),
               "last_msgs": sent, "sent": st.get("sent", 0) + 1})
    json.dump(st, open(STATE, "w"), indent=1)
    print(f"[divar] done {name} ({len(rest)} left in this cycle)")


asyncio.run(main())
