#!/root/.hermes/tools/python-3.14.7+20260901-linux-x64/bin/python3
"""Publish ONE HermesVPN cartoon to the channel and group — ONLY after the owner's explicit approval
(owner rule 2026-11-13: «تا تایید نکردم نفرستی»). Posted by the Ads Account account, like the other ads.

  post_cartoon.py <n> --owner-approved [--only your_channel|your_group] [--caption "<new text>"]
  post_cartoon.py <n> --set-caption "<new text>"     # change the proposed text (no posting)
  post_cartoon.py list                                # cartoons and their status (preview / posted)
Refuses without --owner-approved, refuses a cartoon never previewed to the owner, never posts the same one twice.
The clip is fetched from Drive (media.py fetch) and deleted after posting.
"""
import asyncio, json, os, shutil, subprocess, sys, tempfile, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from public_text_guard import check as guard  # noqa: E402

STATE = "/root/.hermes/ads/cartoons/state.json"
SESSION = "/root/.hermes/profiles/adsaccount/userbot/adsaccount"
TARGETS = ("your_channel", "your_group")
DOCS = "/root/.hermes/shared-tools/docs"


def out(o):
    print(json.dumps(o, ensure_ascii=False))


def arg(name):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else None


async def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    st = json.load(open(STATE)) if os.path.exists(STATE) else {}
    if sys.argv[1] == "list":
        return out({k: {"status": v["status"], "caption": v["caption"][:60]} for k, v in st.items()})
    n = sys.argv[1].translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
    rec = st.get(n)
    if not rec:
        return out({"ok": False, "error": f"cartoon {n} was never prepared/previewed to the owner"})
    if arg("--set-caption"):
        rec["caption"] = arg("--set-caption")
        json.dump(st, open(STATE, "w"), ensure_ascii=False, indent=1)
        return out({"ok": True, "caption": rec["caption"], "note": "show the owner the new text; still NOT published"})
    if "--owner-approved" not in sys.argv:
        return out({"ok": False, "error": "refused: publish only after the owner explicitly approves this cartoon"})
    if rec["status"] == "posted":
        return out({"ok": False, "error": f"cartoon {n} was already posted", "posted": rec.get("posted")})
    cap = arg("--caption") or rec["caption"]
    bad = guard(cap)
    if bad:
        return out({"ok": False, "error": f"caption blocked by guard: {bad}"})
    tmp = tempfile.mkdtemp(prefix="cpost")
    try:
        r = subprocess.run([f"{DOCS}/venv/bin/python", f"{DOCS}/media.py", "fetch", str(rec["media_id"]), tmp],
                           capture_output=True, text=True, timeout=600)
        f = json.loads(r.stdout.strip().splitlines()[-1])
        if not f.get("ok") or not f.get("path"):
            return out({"ok": False, "error": f"could not fetch from Drive: {f}"})
        from telethon import TelegramClient, errors
        cr = json.load(open(SESSION + ".creds.json"))
        shutil.copy2(SESSION + ".session", tmp + "/s.session")
        c = TelegramClient(tmp + "/s", cr["api_id"], cr["api_hash"])
        await c.connect()
        posted = {}
        try:
            for t in ([arg("--only")] if arg("--only") in TARGETS else TARGETS):
                try:
                    m = await c.send_file(t, f["path"], caption=cap, supports_streaming=True)
                    posted[t] = m.id
                except (errors.SlowModeWaitError, errors.FloodWaitError) as e:
                    posted[t] = f"skipped: {type(e).__name__} {e.seconds}s"
                await asyncio.sleep(3)
        finally:
            await c.disconnect()
        rec.update(status="posted" if any(isinstance(v, int) for v in posted.values()) else rec["status"], posted=posted,
                   posted_at=time.time(), caption=cap)
        json.dump(st, open(STATE, "w"), ensure_ascii=False, indent=1)
        out({"ok": True, "posted": posted})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


asyncio.run(main())
