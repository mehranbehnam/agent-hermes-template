#!/usr/bin/python3
"""Owner's Telegram contacts — ONLY on Owner's explicit request (never on the agent's own initiative,
never shared with anyone else, never posted publicly).

  contacts.py count                       # how many contacts the account has
  contacts.py search "علی"                 # find contacts by name / username / phone
  contacts.py list [--limit 100]          # name | @username | phone | id
  contacts.py import-vcf /path/file.vcf   # import a phone-contacts export (.vcf) into the Telegram contacts

The server only sees contacts saved in the Telegram account. To get all phone contacts here, either turn on
Telegram > Settings > Privacy and Security > Sync Contacts (on Owner's phone), or send a .vcf export.
"""
import glob, os, sys, asyncio, json, random, re, datetime

_HPY = sorted(glob.glob("/root/.hermes/tools/python*/bin/python3"))[-1]
if os.path.realpath(sys.executable) != os.path.realpath(_HPY):
    os.execv(_HPY, [_HPY, os.path.abspath(__file__)] + sys.argv[1:])
BASE = os.path.dirname(_HPY)
sys.path.insert(0, os.path.join(os.path.dirname(BASE), "lib", "python3.14", "site-packages"))
from telethon import TelegramClient, functions
from telethon.tl.types import InputPhoneContact

SESSION = "/root/.hermes/profiles/adsaccount/userbot/adsaccount"
STATE = "/root/.hermes/ads/contacts_import_state.json"
IMPORT_DAILY_CAP = 150
FA = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def norm_phone(p):
    d = re.sub(r"\D", "", (p or "").translate(FA))
    if d.startswith("00"):
        d = d[2:]
    if d.startswith("0") and len(d) == 11:
        d = "98" + d[1:]
    elif len(d) == 10 and d.startswith("9"):
        d = "98" + d
    return "+" + d if 10 <= len(d) <= 15 else None


def name_of(u):
    return ((u.first_name or "") + " " + (u.last_name or "")).strip()


async def contacts(c):
    r = await c(functions.contacts.GetContactsRequest(hash=0))
    return [u for u in r.users if not u.deleted]


def row(u):
    return f"{name_of(u) or '-'} | {'@' + u.username if u.username else '-'} | {'+' + u.phone if u.phone else '-'} | {u.id}"


def parse_vcf(path):
    out, name = [], None
    for line in open(path, encoding="utf-8", errors="ignore"):
        line = line.strip()
        if line.upper().startswith("FN:") or line.upper().startswith("FN;"):
            name = line.split(":", 1)[1].strip()
        elif line.upper().startswith("TEL"):
            p = norm_phone(line.split(":", 1)[-1])
            if p:
                out.append((name or p, p))
        elif line.upper() == "END:VCARD":
            name = None
    seen, uniq = set(), []
    for n, p in out:
        if p not in seen:
            seen.add(p)
            uniq.append((n, p))
    return uniq


async def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        return
    cmd = sys.argv[1]
    cr = json.load(open(SESSION + ".creds.json"))
    c = TelegramClient(SESSION, cr["api_id"], cr["api_hash"])
    await c.connect()
    try:
        if cmd == "count":
            print(f"تعداد مخاطب‌های تلگرام: {len(await contacts(c))}")
        elif cmd == "list":
            lim = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 100
            us = await contacts(c)
            print(f"{len(us)} مخاطب (نمایش {min(lim, len(us))}):")
            for u in us[:lim]:
                print("•", row(u))
        elif cmd == "search":
            q = " ".join(sys.argv[2:]).strip().lower().translate(FA)
            qp = re.sub(r"\D", "", q)
            hits = [u for u in await contacts(c)
                    if q in name_of(u).lower() or (u.username and q.lstrip("@") in u.username.lower())
                    or (qp and len(qp) >= 4 and u.phone and qp[-9:] in u.phone)]
            print(f"{len(hits)} نتیجه:")
            for u in hits[:50]:
                print("•", row(u))
        elif cmd == "import-vcf":
            items = parse_vcf(sys.argv[2])
            try:
                st = json.load(open(STATE))
            except Exception:
                st = {}
            today = datetime.date.today().isoformat()
            if st.get("day") != today:
                st = {"day": today, "n": 0}
            room = max(0, IMPORT_DAILY_CAP - st["n"])
            todo, later = items[:room], items[room:]
            found = 0
            for i in range(0, len(todo), 10):
                batch = todo[i:i + 10]
                r = await c(functions.contacts.ImportContactsRequest([
                    InputPhoneContact(client_id=random.randrange(1, 2**31), phone=p, first_name=n[:60], last_name="")
                    for n, p in batch]))
                found += len(r.imported)
                st["n"] += len(batch)
                json.dump(st, open(STATE, "w"))
                await asyncio.sleep(random.uniform(4, 8))
            print(f"از {len(items)} شماره‌ی فایل: {len(todo)} بررسی شد، {found} نفر تلگرام دارند و به مخاطب‌ها اضافه شدند، "
                  f"{len(todo) - found} نفر تلگرام ندارند یا پیدا نشدند" + (f"، {len(later)} نفر برای فردا (سقف روزانه)" if later else ""))
        else:
            print(__doc__)
    finally:
        await c.disconnect()


asyncio.run(main())
