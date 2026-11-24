#!/usr/bin/python3
"""Agent Hermes ads (owner request via HermesVPN, 2026-11-12): poster + exact caption, posted by the Ads Account
userbot. No LLM. One rotation index PER CHAT (ah01 -> ah04 -> ah01).

  agent_hermes_ads.py <chat>            # post the next ad to that chat (example_ad_group | your_channel)
  agent_hermes_ads.py <chat> --dry-run  # show what would be posted, send nothing

Guards: skip if Owner posted in that chat during the last 20 minutes (slow mode / spacing from the VPN ads);
skip on SlowModeWait/FloodWait (no retry); public_text_guard on every caption.
State /root/.hermes/ads/agent_hermes_state.json; log /root/.hermes/ads/stats/agent_hermes_ads.log (cron).
Exit 0 sent, 4 skipped, 1 failed, 3 guard."""
import glob, os, sys, json, asyncio, datetime

_HPY = sorted(glob.glob("/root/.hermes/tools/python*/bin/python3"))[-1]
if os.path.realpath(sys.executable) != os.path.realpath(_HPY):
    os.execv(_HPY, [_HPY, os.path.abspath(__file__)] + sys.argv[1:])
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from telethon import TelegramClient, errors
from public_text_guard import check as guard

DIR = "/root/.hermes/ads/agent-hermes"
STATE = "/root/.hermes/ads/agent_hermes_state.json"
SESSION = "/root/.hermes/profiles/adsaccount/userbot/adsaccount"
CHATS = ("example_ad_group", "your_channel")
QUIET_MIN = 20


def ads():
    return sorted(os.path.basename(p)[:-4] for p in glob.glob(os.path.join(DIR, "ah*.jpg")) if os.path.exists(p[:-4] + ".txt"))


async def main():
    if len(sys.argv) < 2 or sys.argv[1] not in CHATS:
        sys.exit(__doc__)
    chat, dry = sys.argv[1], "--dry-run" in sys.argv
    st = json.load(open(STATE)) if os.path.exists(STATE) else {}
    pool = ads()
    if not pool:
        sys.exit("no ads in " + DIR)
    i = st.get(chat, 0) % len(pool)
    name = pool[i]
    caption = open(os.path.join(DIR, name + ".txt"), encoding="utf-8").read().strip()
    if guard(caption):
        print(f"BLOCKED by guard ({name}): {guard(caption)}")
        sys.exit(3)
    cr = json.load(open(SESSION + ".creds.json"))
    c = TelegramClient(SESSION, cr["api_id"], cr["api_hash"])
    await c.connect()
    try:
        if not await c.is_user_authorized():
            print("ERROR: session not authorized")
            sys.exit(1)
        me = await c.get_me()
        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=QUIET_MIN)
        async for m in c.iter_messages(chat, from_user=me, limit=3):
            if m.date >= cutoff:
                print(f"SKIP {chat}: Owner posted {int((datetime.datetime.now(datetime.timezone.utc) - m.date).total_seconds() // 60)} min ago (msg {m.id})")
                sys.exit(4)
            break
        if dry:
            print(f"next for {chat}: {name}")
            return
        msg = await c.send_file(chat, os.path.join(DIR, name + ".jpg"), caption=caption)
    except (errors.SlowModeWaitError, errors.FloodWaitError) as e:
        print(f"SKIP {chat}: {type(e).__name__} {e.seconds}s")
        sys.exit(4)
    except SystemExit:
        raise
    except Exception as e:
        print(f"ERROR {chat}: {type(e).__name__}: {e}")
        sys.exit(1)
    finally:
        await c.disconnect()
    st[chat] = i + 1
    st.setdefault("sent", {}).setdefault(chat, 0)
    st["sent"][chat] += 1
    json.dump(st, open(STATE, "w"), indent=1)
    print(f"[agent-hermes] {chat} sent {name} msg {msg.id}")


asyncio.run(main())
