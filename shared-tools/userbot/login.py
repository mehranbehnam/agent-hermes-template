"""One-tap login of a PREMIUM user's own Telegram account (userbot) from the admin-panel buttons — no LLM involved,
so the phone, login code and 2FA password never enter the agent's conversation or history.
Uses Agent Hermes' own app (api_id/api_hash): users are never asked for them.

  login.py send <session> <phone>       # Telegram sends a login code to the user's Telegram app
  login.py code <session>               # code read from STDIN (never on the command line)
  login.py password <session>           # 2FA password read from STDIN
  login.py logout <session>             # log the session out on Telegram and delete the files
<session> must be /root/.hermes/profiles/<p>/userbot/<p>. Prints one JSON line.
The session file is a credential (mode 600 inside the user's own profile); no chat content is stored.
"""
import asyncio, json, os, re, sys
from telethon import TelegramClient, errors

APP = "/root/.hermes/userbot/owner.creds.json"          # Agent Hermes' Telegram app (api_id/api_hash)


def out(o):
    print(json.dumps(o, ensure_ascii=False))


def check(session):
    m = re.fullmatch(r"/root/\.hermes/profiles/([a-z][a-z0-9]{1,20})/userbot/\1", session)
    if not m:
        sys.exit(out({"ok": False, "error": "bad_session_path"}))
    try:                                                  # owner decision: only listed profiles may link an account
        allowed = json.load(open("/root/.hermes/shared-tools/admin/account_link_allowed.json"))
    except Exception:
        allowed = []
    sealed = "# >>> sandbox (sandbox_profile.py) >>>" in open(f"/root/.hermes/profiles/{m.group(1)}/config.yaml").read()
    if m.group(1) not in allowed and not ("*" in allowed and (sealed or m.group(1) == "owner2")) and sys.argv[1] != "logout":
        sys.exit(out({"ok": False, "error": "not_enabled"}))
    os.makedirs(os.path.dirname(session), mode=0o700, exist_ok=True)
    os.chmod(os.path.dirname(session), 0o700)


def lock_down(session):
    for f in (session + ".session", session + ".creds.json", session + ".pending_login.json"):
        if os.path.exists(f):
            os.chmod(f, 0o600)


async def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    cmd, session = sys.argv[1], sys.argv[2]
    check(session)
    app = json.load(open(APP))
    pend_f = session + ".pending_login.json"
    c = TelegramClient(session, app["api_id"], app["api_hash"], device_model="Agent Hermes", app_version="1.0")
    await c.connect()
    try:
        if cmd == "send" and len(sys.argv) == 4:
            phone = "+" + re.sub(r"\D", "", sys.argv[3].translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")))
            if phone.startswith("+0"):
                phone = "+98" + phone[2:]                      # 0912... -> +98912...
            if await c.is_user_authorized():
                return out({"ok": True, "already": True})
            r = await c.send_code_request(phone)
            json.dump({"phone": phone, "phone_code_hash": r.phone_code_hash}, open(pend_f, "w"))
            out({"ok": True, "sent": True, "phone_tail": phone[-4:]})
        elif cmd == "code":
            code = re.sub(r"\D", "", sys.stdin.read().translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")))
            p = json.load(open(pend_f))
            try:
                await c.sign_in(p["phone"], code, phone_code_hash=p["phone_code_hash"])
            except errors.SessionPasswordNeededError:
                return out({"ok": True, "needs_password": True})
            await finish(c, session, app, pend_f)
        elif cmd == "password":
            await c.sign_in(password=sys.stdin.read().rstrip("\n"))
            await finish(c, session, app, pend_f)
        elif cmd == "logout":
            if await c.is_user_authorized():
                await c.log_out()
            await c.disconnect()
            for f in (session + ".session", session + ".creds.json", pend_f, session + ".session-journal"):
                if os.path.exists(f):
                    os.remove(f)
            out({"ok": True, "logged_out": True})
        else:
            sys.exit(__doc__)
    except errors.PhoneNumberInvalidError:
        out({"ok": False, "error": "phone_invalid"})
    except (errors.PhoneCodeInvalidError, errors.PhoneCodeEmptyError):
        out({"ok": False, "error": "code_invalid"})
    except errors.PhoneCodeExpiredError:
        out({"ok": False, "error": "code_expired"})
    except errors.PasswordHashInvalidError:
        out({"ok": False, "error": "password_invalid"})
    except errors.FloodWaitError as e:
        out({"ok": False, "error": "flood", "seconds": e.seconds})
    except FileNotFoundError:
        out({"ok": False, "error": "no_pending_login"})
    except Exception as e:
        out({"ok": False, "error": f"{type(e).__name__}: {e}"[:200]})
    finally:
        if c.is_connected():
            await c.disconnect()
        lock_down(session)


async def finish(c, session, app, pend_f):
    me = await c.get_me()
    json.dump({"api_id": app["api_id"], "api_hash": app["api_hash"]}, open(session + ".creds.json", "w"))
    if os.path.exists(pend_f):
        os.remove(pend_f)
    out({"ok": True, "logged_in": True, "name": " ".join(x for x in (me.first_name, me.last_name) if x)})


asyncio.run(main())
