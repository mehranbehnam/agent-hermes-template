#!/usr/bin/python3
"""Agent Hermes user administration (owner-only), used by the admin-panel plugin buttons and usable by hand.
Prints JSON. Never prints message CONTENT: only status, ids, counts, timestamps (Rule #1: user isolation).

  users_admin.py list                         # every user profile: status, last activity, usage counts
  users_admin.py detail <name>
  users_admin.py create <name>                # new profile cloned from the never-paired 'usertemplate'
  users_admin.py pending                      # pairing requests waiting for approval
  users_admin.py activate <request_id> <name> # approve request + bind its Telegram id to profile <name>
  users_admin.py set <name> on|off            # connect / disconnect (pause) a user
  users_admin.py restart                      # restart the gateway in the background (after activate/set)
  users_admin.py tier <name>                   # tier, expiry, active?
  users_admin.py set-tier <name> basic|premium <days|0=forever>   # sets tier + applies its capabilities
  users_admin.py quote <name>                  # purchase/renew/upgrade options with prices
  users_admin.py order-new <name> basic|premium year|month | order-approve <id> | order-reject <id> | orders
  users_admin.py expire                        # hourly cron: reminders 2 days before / at expiry
  users_admin.py invite <profile>               # single-use link that connects whoever opens it to that EXISTING profile
  users_admin.py trial-new <seats> <days> [basic|premium] [label] | trial-list | trial-close <code> | trial-claim <code> <tg_id> <display>
  users_admin.py ledger <name>                 # customer account: purchases, payments, receipts, documents (owner only)
  users_admin.py ledger-add <name> <type> <amount> <text...>      # manual entry (type: payment|note|refund)
  users_admin.py ledger-file <name> <type> <file> <text...>       # receipt / purchase document (copied into the ledger)
  users_admin.py ledger-backfill               # one-time: entries for customers that existed before the ledger
"""
import json, os, re, sqlite3, subprocess, sys, time, shutil

H = "/root/.hermes"
ENV = f"{H}/.env"
CONFIG = f"{H}/config.yaml"
ROSTER = f"{H}/shared-tools/admin/roster.json"
PENDING = f"{H}/platforms/pairing/telegram-pending.json"
APPROVED = f"{H}/platforms/pairing/telegram-approved.json"
HERMES = "/root/.local/bin/hermes"
TEMPLATE = "usertemplate"
OWNER_ID = "100000001"
# profiles that are not ordinary users (owner's own work profiles, group personas, the template)
NOT_USERS = {"adsaccount", "adsaccount2", "hermesgroup", "iranvpngroup", TEMPLATE}
NAME_RE = re.compile(r"^[a-z][a-z0-9]{1,20}$")


def out(obj):
    print(json.dumps(obj, ensure_ascii=False))


def load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def allowed_ids():
    m = re.search(r"^TELEGRAM_ALLOWED_USERS=(.*)$", open(ENV).read(), re.M)
    return [i.strip() for i in (m.group(1).split(",") if m else []) if i.strip()]


def write_allowed(ids):
    content = open(ENV).read()
    content = re.sub(r"^TELEGRAM_ALLOWED_USERS=.*$", "TELEGRAM_ALLOWED_USERS=" + ",".join(ids), content, flags=re.M)
    tmp = ENV + ".tmp"
    with open(tmp, "w") as f:
        f.write(content)
    os.chmod(tmp, 0o600)
    os.replace(tmp, ENV)


def routes():
    """{profile: chat_id} from gateway.profile_routes (DM routes only)."""
    res, cur = {}, {}
    for line in open(CONFIG):
        m = re.match(r"\s*-\s*name:\s*['\"]?([^'\"\n]+)", line)
        if m:
            cur = {"name": m.group(1)}
        for key in ("chat_id", "profile"):
            m = re.match(rf"\s*{key}:\s*['\"]?(-?[\w]+)", line)
            if m and cur is not None:
                cur[key] = m.group(1)
        if cur.get("profile") and cur.get("chat_id"):
            res[cur["profile"]] = cur["chat_id"]
            cur = {}
    return res


def user_profiles():
    names = sorted(d for d in os.listdir(f"{H}/profiles") if os.path.isdir(f"{H}/profiles/{d}") and d not in NOT_USERS and not d.startswith("."))
    return names


def roster():
    r = load(ROSTER, {})
    for prof, cid in routes().items():          # routes are the source of truth for bound ids
        if prof in user_profiles() and not cid.startswith("-"):
            r[prof] = cid
    return r


def usage(name):
    db = f"{H}/profiles/{name}/state.db"
    res = {"last_activity": None, "msgs_24h": 0, "msgs_7d": 0, "msgs_total": 0, "sessions": 0, "tool_calls_7d": 0}
    if not os.path.exists(db):
        return res
    try:
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
        now = time.time()
        q = lambda sql, *a: c.execute(sql, a).fetchone()[0]
        res["last_activity"] = q("SELECT MAX(timestamp) FROM messages WHERE role='user'")
        res["msgs_24h"] = q("SELECT COUNT(*) FROM messages WHERE role='user' AND timestamp>?", now - 86400)
        res["msgs_7d"] = q("SELECT COUNT(*) FROM messages WHERE role='user' AND timestamp>?", now - 7 * 86400)
        res["msgs_total"] = q("SELECT COUNT(*) FROM messages WHERE role='user'")
        res["sessions"] = q("SELECT COUNT(*) FROM sessions")
        res["tool_calls_7d"] = q("SELECT COUNT(*) FROM messages WHERE role='tool' AND timestamp>?", now - 7 * 86400)
        c.close()
    except Exception as e:
        res["error"] = f"{type(e).__name__}: {e}"
    return res


def info(name, r=None, allowed=None):
    r = roster() if r is None else r
    allowed = allowed_ids() if allowed is None else allowed
    tg = r.get(name)
    status = "unpaired" if not tg else ("on" if tg in allowed else "off")
    d = {"name": name, "label": load(LABELS, {}).get(name, ""), "tg_id": tg, "status": status, **usage(name), **{k: v for k, v in tier_info(name).items() if k != "name"}}
    appr = load(APPROVED, {})
    if tg and tg in appr:
        d["tg_name"] = appr[tg].get("user_name", "")
        d["approved_at"] = appr[tg].get("approved_at")
    d["userbot"] = any(f.endswith(".session") for f in os.listdir(f"{H}/profiles/{name}/userbot")) \
        if os.path.isdir(f"{H}/profiles/{name}/userbot") else False
    try:
        d["created_at"] = os.path.getctime(f"{H}/profiles/{name}/profile.yaml")
    except OSError:
        d["created_at"] = None
    return d


# ---------------- tiers (basic / premium) ----------------
TIERS = f"{H}/shared-tools/admin/tiers.json"
TIERS_CFG = f"{H}/shared-tools/admin/tiers_config.json"
ORDERS = f"{H}/shared-tools/admin/orders.json"
USERBOT_SKILLS = ("telegram-userbot", "telegram-userbot-setup")
USERBOT_HEAD = "## Sending Telegram messages from the user's own account (userbot)"
PREMIUM_HEAD = "## کانال و تبلیغات خودم (پرمیوم)"
PREMIUM_BLOCK = """## کانال و تبلیغات خودم (پرمیوم)

این کاربر اشتراک پرمیوم دارد. بعد از راه‌اندازی یوزربات (بخش بالا)، می‌تواند کانال یا گروهی را که **خودش مالک یا ادمین آن است** از همین‌جا مدیریت کند:

    /root/.hermes/tools/python-3.14.7+20260901-linux-x64/bin/python3 /root/.hermes/shared-tools/userbot/channel_admin.py /root/.hermes/profiles/{name}/userbot/{name} <post|reply|pin|unpin|delete|stats> <@channel> [متن یا شناسه]

- پست/تبلیغ در کانال یا گروه خودش: `post`. برای تبلیغ زمان‌بندی‌شده (مثلاً روزی ۲ بار)، با ابزار cronjob یک کار تکراری بساز که همین دستور را اجرا کند؛ حداکثر ۶ پست در روز در هر کانال.
- آمار اعضا و بازدید: `stats`.
- فقط در کانال و گروهی که خود کاربر مالک یا ادمین آن است. هرگز پیام انبوه به اشخاص، هرگز عضو کردن آدم‌ها بدون اجازه‌ی خودشان، هرگز پست در گروه‌های دیگران — این کارها خلاف قوانین تلگرام است و شماره‌ی خود کاربر را مسدود می‌کند. اگر خواست، توضیح بده چرا نه.

**دسترسی به حساب تلگرام خود کاربر (فقط خواندن، فقط وقتی خودش بخواهد):** با همان یوزربات، مخاطب‌ها و چت‌های حساب خودش را ببین:

    /root/.hermes/tools/python-3.14.7+20260901-linux-x64/bin/python3 /root/.hermes/shared-tools/userbot/account_read.py /root/.hermes/profiles/{name}/userbot/{name} <status|contacts [جستجو]|dialogs [تعداد]|history <چت> [تعداد]|search <متن> [تعداد]>

- مثال‌ها: «مخاطب‌هام رو نشون بده»، «شماره‌ی علی رو پیدا کن»، «آخرین چت‌هام چیه؟»، «چت با مادرم رو خلاصه کن»، «کی درباره‌ی قرارداد پیام داده؟».
- اگر NOT_LOGGED_IN گفت، اول یوزربات را با مراحل بالا راه بینداز.
- پیام‌ها و اطلاعات دیگران را فقط به خود کاربر نشان بده؛ هرگز در حافظه یا فایل نگه ندار مگر خودش صریحاً بخواهد، و هرگز برای کس دیگری نفرست.
"""


def tiers_cfg():
    return load(TIERS_CFG, {})


def tiers():
    return load(TIERS, {})


def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def tier_info(name):
    t = tiers().get(name) or {}
    tier = t.get("tier", "basic")
    until = t.get("until")
    active = (until is None or until > time.time()) and not t.get("paused")
    return {"name": name, "tier": tier, "until": until, "active": active, "paused": bool(t.get("paused")),
            "title": tiers_cfg().get("tiers", {}).get(tier, {}).get("title", tier)}


def apply_tier(name, tier):
    """basic: userbot skills + SOUL sections locked away; premium: restored + own-channel section."""
    d = f"{H}/profiles/{name}"
    locked = f"{d}/skills-locked"
    soul_p = f"{d}/SOUL.md"
    soul = open(soul_p, encoding="utf-8").read()
    saved = f"{d}/.soul-userbot-section.md"
    if tier == "basic":
        os.makedirs(locked, exist_ok=True)
        for sk in USERBOT_SKILLS:
            if os.path.isdir(f"{d}/skills/{sk}"):
                shutil.rmtree(f"{locked}/{sk}", ignore_errors=True)
                shutil.move(f"{d}/skills/{sk}", f"{locked}/{sk}")
        if PREMIUM_HEAD in soul:
            soul = soul[:soul.index(PREMIUM_HEAD)].rstrip() + "\n"
        if USERBOT_HEAD in soul:
            i = soul.index(USERBOT_HEAD)
            j = soul.find("\n## ", i + 5)
            section = soul[i:] if j < 0 else soul[i:j]
            open(saved, "w", encoding="utf-8").write(section)
            soul = soul[:i].rstrip() + "\n" + ("" if j < 0 else soul[j:])
        soul = soul.rstrip() + "\n\n## سطح اشتراک: معمولی\nاین کاربر نسخه‌ی معمولی دارد: گفتگو، مشاور حقوقی، جستجو، فایل و پیام صوتی. پیام از حساب شخصی (یوزربات)، مدیریت کانال و تبلیغات فقط در نسخه‌ی پرمیوم است؛ اگر خواست، کوتاه بگو با دکمه‌ی «⭐ اشتراک من» می‌تواند ارتقا بدهد.\n" \
            if "## سطح اشتراک: معمولی" not in soul else soul
    else:
        for sk in USERBOT_SKILLS:
            if os.path.isdir(f"{locked}/{sk}") and not os.path.isdir(f"{d}/skills/{sk}"):
                shutil.move(f"{locked}/{sk}", f"{d}/skills/{sk}")
        if "## سطح اشتراک: معمولی" in soul:
            i = soul.index("## سطح اشتراک: معمولی")
            j = soul.find("\n## ", i + 5)
            soul = soul[:i].rstrip() + "\n" + ("" if j < 0 else soul[j:])
        if USERBOT_HEAD not in soul and os.path.exists(saved):
            soul = soul.rstrip() + "\n\n" + open(saved, encoding="utf-8").read().strip() + "\n"
        if PREMIUM_HEAD not in soul:
            soul = soul.rstrip() + "\n\n" + PREMIUM_BLOCK.replace("{name}", name)
    shutil.copy2(soul_p, f"/root/backups/{name}-SOUL.md.bak-{time.strftime('%Y%m%d-%H%M%S')}-tier")
    open(soul_p, "w", encoding="utf-8").write(soul)


def set_tier(name, tier, days, own=True):
    if name not in user_profiles():
        raise ValueError("no_such_profile")
    if tier not in ("basic", "premium"):
        raise ValueError("bad_tier")
    t = tiers()
    cur = t.get(name) or {}
    until = None
    if days:
        base = cur.get("until") if cur.get("tier") == tier and cur.get("until") and cur["until"] > time.time() else time.time()
        until = base + days * 86400
    owned = dict(cur.get("owned") or {})
    if own:                                  # admin grant or paid order = the user owns this version (not a free trial)
        owned[tier] = True
    t[name] = {"tier": tier, "until": until, "set_at": time.time(), "reminded": None, "owned": owned}
    save_json(TIERS, t)
    apply_tier(name, tier)
    return tier_info(name)


# HermesVPN plan/bundle prices and their 0-20% discounted values (rounded like the sales bot, to 1,000).
# If HermesVPN changes its prices, update this list (ask the HermesVPN session).
VPN_BASE_PRICES = (60000, 100000, 150000, 250000, 450000, 800000, 1200000, 2000000)
VPN_AMOUNTS = {max(1000, int(round(p * (100 - d) / 100 / 1000.0)) * 1000) for p in VPN_BASE_PRICES for d in range(0, 21)}


def quote(name, tier, period):
    """Price = one-time purchase of the version (only if not owned; upgrade pays the difference)
    + hosting subscription for the period - credit for unused paid days of a lower version."""
    cfg = tiers_cfg()
    T, days = cfg["tiers"], cfg["periods"][period]
    rec = tiers().get(name) or {}
    owned = dict(rec.get("owned") or {})
    if owned.get("premium"):
        owned["basic"] = True                 # premium owners may switch to basic without buying it
    hosting = T[tier]["hosting_year" if period == "year" else "hosting_month"]
    purchase, credit, kind = 0, 0, "renew"
    if not owned.get(tier):
        if tier == "premium" and owned.get("basic"):
            purchase, kind = T["premium"]["purchase"] - T["basic"]["purchase"], "upgrade"
            until = rec.get("until")
            if rec.get("tier") == "basic" and until and until > time.time():   # unused basic hosting -> credit
                credit = int((until - time.time()) / 86400 * T["basic"]["hosting_year"] / 365 / 1000) * 1000
        else:
            purchase, kind = T[tier]["purchase"], "buy"
    total = max(0, purchase + hosting - credit)
    while total in VPN_AMOUNTS:                 # never equal a HermesVPN price: same card, the VPN sales bot
        total += 1000                           # auto-matches bank deposits by amount (HermesVPN 2026-11-11)
    return {"tier": tier, "period": period, "days": days, "kind": kind, "purchase": purchase,
            "hosting": hosting, "credit": credit, "price": total, "title": T[tier]["title"]}


def cmd_quote(name):
    if name not in user_profiles():
        return out({"error": "no_such_profile"})
    out([quote(name, t, p) for t in ("premium", "basic") for p in ("year", "month")])


# ---------------- customer ledger (owner's business record of each customer: never the customer's messages) ----------------
LEDGER = os.environ.get("HERMES_LEDGER_DIR") or f"{H}/shared-tools/admin/ledger"   # env override only for tests


def ledger_add(name, typ, amount=0, text="", ref=None, file=None):
    d = f"{LEDGER}/{name}"
    os.makedirs(f"{d}/files", mode=0o700, exist_ok=True)
    for x in (LEDGER, d, f"{d}/files"):
        os.chmod(x, 0o700)
    led = load(f"{d}/ledger.json", {"entries": []})
    e = {"id": len(led["entries"]) + 1, "ts": time.time(), "type": typ, "amount": int(amount or 0), "text": text}
    if ref:
        e["ref"] = str(ref)
    if file and os.path.exists(file):
        dst = f"{d}/files/{e['id']:04d}-{typ}{os.path.splitext(file)[1].lower() or '.bin'}"
        shutil.copy2(file, dst)
        os.chmod(dst, 0o600)
        e["file"] = dst
    led["entries"].append(e)
    save_json(f"{d}/ledger.json", led)
    return e


def ledger_view(name):
    led = load(f"{LEDGER}/{name}/ledger.json", {"entries": []})
    E = led["entries"]
    paid = sum(e["amount"] for e in E if e["type"] in ("payment", "manual_payment"))
    refund = sum(e["amount"] for e in E if e["type"] == "refund")
    buys = [e for e in E if e["type"] in ("payment", "manual_payment")]
    return {"name": name, "tier": tier_info(name) if name in user_profiles() else None, "entries": E,
            "summary": {"paid": paid, "refund": refund, "net": paid - refund, "purchases": len(buys),
                        "orders": sum(1 for e in E if e["type"] == "order"),
                        "receipts": sum(1 for e in E if e.get("file") and e["type"] == "receipt"),
                        "docs": sum(1 for e in E if e.get("file") and e["type"] != "receipt"),
                        "first": E[0]["ts"] if E else None, "last_purchase": buys[-1]["ts"] if buys else None}}


def ledger_backfill():
    done = []
    for name, rec in tiers().items():
        if name in NOT_USERS or os.path.exists(f"{LEDGER}/{name}/ledger.json"):
            continue
        ledger_add(name, "tier", 0, f"نسخه‌ی {rec.get('tier')} (ثبت‌شده پیش از دفتر حساب)" + (" · دائمی" if not rec.get("until") else ""))
        led = load(f"{LEDGER}/{name}/ledger.json", {"entries": []})
        led["entries"][-1]["ts"] = rec.get("set_at") or time.time()
        save_json(f"{LEDGER}/{name}/ledger.json", led)
        done.append(name)
    return {"ok": True, "backfilled": done}


def cmd_order_new(name, tier, period="year"):
    cfg = tiers_cfg()
    if name not in user_profiles() or tier not in cfg.get("tiers", {}) or period not in cfg.get("periods", {}):
        return out({"ok": False, "error": "bad_args"})
    q = quote(name, tier, period)
    o = load(ORDERS, {"next": 1, "orders": {}})
    oid = str(o["next"])
    o["next"] += 1
    o["orders"][oid] = {"name": name, **q, "status": "awaiting_receipt", "created": time.time()}
    save_json(ORDERS, o)
    ledger_add(name, "order", q["price"], f"سفارش #{oid}: {q['title']} · {'سالانه' if period == 'year' else 'ماهانه'} · منتظر فیش", ref=oid)
    out({"ok": True, "id": oid, **o["orders"][oid], "card_number": cfg["card_number"], "card_holder": cfg["card_holder"]})


def order_set(oid, status):
    o = load(ORDERS, {"next": 1, "orders": {}})
    od = o["orders"].get(oid)
    if not od:
        return None, "not_found"
    if od["status"] in ("approved", "rejected"):
        return od, "already_" + od["status"]
    od["status"] = status
    od["decided"] = time.time()
    save_json(ORDERS, o)
    return od, None


def cmd_order_approve(oid):
    od, err = order_set(oid, "approved")
    if err:
        return out({"ok": False, "error": err})
    inf = set_tier(od["name"], od["tier"], od["days"])
    ledger_add(od["name"], "payment", od["price"], f"پرداخت سفارش #{oid} تأیید شد: {od.get('title', od['tier'])} · {od['days']} روز", ref=oid)
    out({"ok": True, "id": oid, **od, "tg_id": roster().get(od["name"]), "tier_info": inf})


def cmd_order_reject(oid):
    od, err = order_set(oid, "rejected")
    if err:
        return out({"ok": False, "error": err})
    ledger_add(od["name"], "reject", 0, f"فیش سفارش #{oid} رد شد", ref=oid)
    out({"ok": True, "id": oid, **od, "tg_id": roster().get(od["name"])})


def bot_send(chat_id, text):
    import urllib.request, urllib.parse
    tok = re.search(r"^TELEGRAM_BOT_TOKEN=(.*)$", open(ENV).read(), re.M).group(1).strip().strip('"')
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    urllib.request.urlopen(urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage", data=data), timeout=20)


def credit_check():
    """Paid model (Haiku 5.5 for the owner + user2, 2026-11-14): warn the owner once a day when OpenRouter credit or the
    key's spending cap falls below $2. Runs from the hourly expire cron."""
    import urllib.request
    key = re.search(r"^OPENROUTER_API_KEY=(.*)$", open(ENV).read(), re.M).group(1).strip().strip('"')
    get = lambda u: json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"Authorization": f"Bearer {key}"}), timeout=20)).get("data", {})
    try:
        cr, k = get("https://openrouter.ai/api/v1/credits"), get("https://openrouter.ai/api/v1/key")
    except Exception as e:
        print(f"credit check failed: {e}", file=sys.stderr)
        return None
    balance = float(cr.get("total_credits") or 0) - float(cr.get("total_usage") or 0)
    cap_left = k.get("limit_remaining")
    low = [f"اعتبار حساب: {balance:.2f} دلار"] if balance < 2 else []
    cap = k.get("limit")
    # warn when less than 20% of the key's cap (or under $1) is left; a small cap must not alarm from day one
    if cap_left is not None and cap and float(cap_left) < max(1.0, 0.2 * float(cap)) and float(cap_left) < float(cap):
        low.append(f"سقف ماهانه‌ی کلید: {float(cap_left):.2f} دلار مانده از {cap}")
    stf = f"{H}/shared-tools/admin/credit_alert.json"
    last = load(stf, {}).get("ts", 0)
    if low and time.time() - last > 86400:
        bot_send(OWNER_ID, "⚠️ اعتبار OpenRouter (مدل Haiku ایجنت شما و کاربر۲) کم شده:\n" + "\n".join(low) +
                 "\nبرای ادامه، حساب را شارژ کنید یا سقف کلید را بالا ببرید. اگر تمام شود، ایجنت‌ها خودکار روی مدل رایگان می‌روند.")
        save_json(stf, {"ts": time.time(), "low": low})
    return {"balance": round(balance, 2), "cap_left": cap_left, "alerted": bool(low)}


PAID_ALLOWED = {"default", "user2"}     # owner 2026-11-14: ONLY his admin agent + user2 may use paid models (Haiku)


def paid_model_watch():
    """Hourly: any OTHER profile that used a non-free model in the last 2 h -> warn the owner (once per profile per day)."""
    import glob, sqlite3
    hits = []
    since = time.time() - 7200
    for db in [f"{H}/state.db"] + glob.glob(f"{H}/profiles/*/state.db"):
        prof = "default" if db == f"{H}/state.db" else db.split("/")[-2]
        if prof in PAID_ALLOWED:
            continue
        try:
            c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            for (m,) in c.execute("SELECT DISTINCT model FROM session_model_usage WHERE last_seen > ?", (since,)):
                ml = (m or "").lower()
                if ml.endswith(":free") or ml.startswith(("gemini-", "baidu/", "meituan/", "stepfun/")) and ":free" in ml:
                    continue
                if ml.startswith("gemini-"):            # Google AI Studio free tier (own key), not OpenRouter credit
                    continue
                hits.append((prof, m))
        except Exception as e:
            print(f"paid watch skip {db}: {e}", file=sys.stderr)
    stf = f"{H}/shared-tools/admin/paid_watch.json"
    seen = load(stf, {})
    today = time.strftime("%Y-%m-%d")
    new = [(p, m) for p, m in hits if seen.get(f"{p}|{m}") != today]
    if new:
        bot_send(OWNER_ID, "⚠️ هشدار مدل پولی: این ایجنت‌ها از مدلی غیر از مدل‌های رایگان استفاده کردند:\n" +
                 "\n".join(f"• {p}: {m}" for p, m in new) + "\nبه من خبر بده تا بررسی و قطعش کنم.")
        for p, m in new:
            seen[f"{p}|{m}"] = today
        save_json(stf, seen)
    return hits


def cmd_expire():
    try:
        credit_check()
    except Exception as e:
        print(f"credit check error: {e}", file=sys.stderr)
    try:
        paid_model_watch()
    except Exception as e:
        print(f"paid model watch error: {e}", file=sys.stderr)
    """Hourly: one reminder 2 days before expiry, one notice at expiry (user + owner). Access itself is
    enforced by the admin-panel plugin (expired users only see the subscription menu)."""
    t, r, now, sent = tiers(), roster(), time.time(), []
    for name, rec in t.items():
        until, tg = rec.get("until"), r.get(name)
        if not until or not tg:
            continue
        title = tiers_cfg().get("tiers", {}).get(rec["tier"], {}).get("title", rec["tier"])
        try:
            trial = bool(re.fullmatch(r"test\d{2,3}", name))
            if rec.get("paused"):
                continue
            if until > now and until - now < (2 * 3600 if trial else 2 * 86400) and rec.get("reminded") != "soon":
                bot_send(tg, f"⏰ اشتراک {title} ایجنت هرمس تا {int((until - now) // 3600)} ساعت دیگر تمام می‌شود.\nبرای تمدید «⭐ اشتراک من» را بزن.")
                rec["reminded"] = "soon"
                sent.append((name, "soon"))
            elif until <= now and rec.get("reminded") != "expired":
                bot_send(tg, f"⛔ اشتراک {title} ایجنت هرمس تمام شد.\nبرای تمدید «⭐ اشتراک من» را بزن.")
                bot_send(OWNER_ID, f"⛔ اشتراک {title} کاربر {name} تمام شد.")
                rec["reminded"] = "expired"
                sent.append((name, "expired"))
        except Exception as e:
            print(f"expire notify {name}: {e}", file=sys.stderr)
    save_json(TIERS, t)
    out({"ok": True, "sent": sent})


def cmd_model_usage():
    """Exact OpenRouter free-model counter for today (from OpenRouter itself) + agent replies written today
    (assistant messages since 00:00 UTC in every profile). sessions.api_call_count is cumulative per session,
    so it must not be used for daily numbers (agent-hermes-65 correction, 2026-11-11)."""
    import calendar, urllib.request
    t0 = calendar.timegm(time.gmtime()[:3] + (0, 0, 0, 0, 0, 0))
    res = {"since_utc_midnight": t0, "openrouter": None, "replies_today": 0}
    try:
        key = re.search(r"^OPENROUTER_API_KEY=(.*)$", open(ENV).read(), re.M).group(1).strip()
        d = json.load(urllib.request.urlopen(urllib.request.Request("https://openrouter.ai/api/v1/key",
                                                                    headers={"Authorization": "Bearer " + key}), timeout=20))["data"]
        res["openrouter"] = d.get("free_model_daily_requests")
    except Exception as e:
        print(f"model-usage openrouter: {e}", file=sys.stderr)
    dbs = [f"{H}/state.db"] + [f"{H}/profiles/{d}/state.db" for d in os.listdir(f"{H}/profiles")]
    for db in dbs:
        if os.path.exists(db):
            try:
                c = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
                res["replies_today"] += c.execute("SELECT COUNT(*) FROM messages WHERE role='assistant' AND timestamp>=?", (t0,)).fetchone()[0]
                c.close()
            except Exception as e:
                print(f"model-usage {db}: {e}", file=sys.stderr)
    out(res)


def cmd_list():
    r, allowed = roster(), allowed_ids()
    out([info(n, r, allowed) for n in user_profiles()])


def cmd_create(name):
    if not NAME_RE.match(name):
        return out({"ok": False, "error": "bad_name"})
    if os.path.exists(f"{H}/profiles/{name}"):
        return out({"ok": False, "error": "exists"})
    if os.path.exists(f"{H}/profiles/{TEMPLATE}/DO_NOT_PAIR.txt") is False:
        return out({"ok": False, "error": "template_missing"})
    p = subprocess.run([HERMES, "profile", "create", name, "--clone-from", TEMPLATE, "--no-alias"],
                       capture_output=True, text=True, timeout=300)
    d = f"{H}/profiles/{name}"
    if p.returncode or not os.path.isdir(d):
        return out({"ok": False, "error": "create_failed", "detail": (p.stderr or p.stdout)[-300:]})
    for root, _, files in os.walk(d):
        for fn in files:
            if fn.endswith((".md", ".yaml")) and "/skills/" in root + "/" or fn in ("SOUL.md",):
                fp = os.path.join(root, fn)
                try:
                    s = open(fp, encoding="utf-8").read()
                except (UnicodeDecodeError, OSError):
                    continue
                if TEMPLATE in s:
                    open(fp, "w", encoding="utf-8").write(s.replace(TEMPLATE, name))
    for leftover in ("DO_NOT_PAIR.txt", "memories/MEMORY.md", "memories/USER.md", "skills/.curator_ledger.jsonl", "skills/.curator_state"):
        try:
            os.remove(f"{d}/{leftover}")
        except FileNotFoundError:
            pass
    shutil.rmtree(f"{d}/skills/.archive", ignore_errors=True)
    r = load(ROSTER, {})
    r.setdefault(name, None)
    json.dump(r, open(ROSTER, "w"), ensure_ascii=False, indent=2)
    # Rule #1: every new user profile gets its own sealed container (sandbox_profile.py) from the start
    sb = subprocess.run([sys.executable, f"{H}/shared-tools/admin/sandbox_profile.py", "on", name], capture_output=True, text=True, timeout=60)
    if sb.returncode:
        print(f"sandbox failed for {name}: {sb.stderr[-200:]}", file=sys.stderr)
    out({"ok": True, "name": name})


def cmd_pending():
    p = load(PENDING, {})
    now = time.time()
    res = []
    for rid, inf in p.items():
        created = inf.get("created_at") or inf.get("created") or now
        res.append({"request_id": rid, "user_id": str(inf.get("user_id", "")), "user_name": inf.get("user_name", ""),
                    "age_min": int((now - float(created)) / 60)})
    out(res)


def add_route(name, chat_id):
    text = open(CONFIG).read()
    if re.search(rf"chat_id:\s*['\"]?{re.escape(chat_id)}['\"]?\s*\n\s*profile:", text):
        return "exists"
    m = re.search(r"^(\s*)-\s*name:\s*['\"]?user2-dm", text, re.M) or re.search(r"^(\s*)-\s*name:\s*\S+-dm", text, re.M)
    if not m:
        raise RuntimeError("could not find profile_routes in config.yaml")
    ind = m.group(1)
    block = (f"{ind}- name: {name}-dm\n{ind}  platform: telegram\n{ind}  chat_id: '{chat_id}'\n{ind}  profile: {name}\n")
    shutil.copy2(CONFIG, f"/root/backups/config.yaml.bak-{time.strftime('%Y%m%d-%H%M%S')}-adduser")
    text = text[:m.start()] + block + text[m.start():]
    open(CONFIG, "w").write(text)
    return "added"


def cmd_activate(rid, name):
    if name not in user_profiles():
        return out({"ok": False, "error": "no_such_profile"})
    if roster().get(name):
        return out({"ok": False, "error": "profile_already_bound"})
    req = load(PENDING, {}).get(rid)
    if not req:
        return out({"ok": False, "error": "request_not_found"})
    uid = str(req.get("user_id"))
    if uid == OWNER_ID or uid in routes().values():
        return out({"ok": False, "error": "id_already_routed"})
    p = subprocess.run([HERMES, "pairing", "approve", "telegram", rid], capture_output=True, text=True, timeout=60)
    if "Approved" not in p.stdout:
        return out({"ok": False, "error": "approve_failed", "detail": (p.stdout + p.stderr)[-300:]})
    route = bind(name, uid)
    trial = tiers_cfg().get("trial_days", 3)
    if name not in tiers():
        set_tier(name, "basic", trial, own=False)   # new users: basic, free trial (not owned yet)
    out({"ok": True, "name": name, "user_id": uid, "user_name": req.get("user_name", ""), "route": route,
         "restart_needed": True, "tier": tier_info(name)})


def cmd_set(name, action):
    uid = roster().get(name)
    if not uid:
        return out({"ok": False, "error": "unpaired"})
    if uid == OWNER_ID:
        return out({"ok": False, "error": "owner"})
    ids = allowed_ids()
    if action == "off":
        ids = [i for i in ids if i != uid]
    elif action == "on":
        if uid not in ids:
            ids.append(uid)
    else:
        return out({"ok": False, "error": "bad_action"})
    write_allowed(ids)
    out({"ok": True, "name": name, "status": action, "restart_needed": True})


RESTART_FLAG = f"{H}/shared-tools/admin/.restart-pending"


def cmd_restart(delay=5):
    # detached (the caller is often the gateway itself) and debounced: several activations in a row -> one restart
    try:
        if time.time() - os.path.getmtime(RESTART_FLAG) < 90:
            return out({"ok": True, "restart": "already_scheduled"})
    except FileNotFoundError:
        pass
    open(RESTART_FLAG, "w").write(str(time.time()))
    subprocess.Popen(["/bin/sh", "-c", f"sleep {delay}; rm -f {RESTART_FLAG}; {HERMES} gateway restart >/tmp/hermes-admin-restart.log 2>&1"],
                     start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    out({"ok": True, "restart": "scheduled"})


# ---------------- trial invite links ----------------
TRIALS = f"{H}/shared-tools/admin/trials.json"


def bind(name, uid):
    """route + roster + allow-list (pairing approval itself is done in-process by the plugin)."""
    route = add_route(name, uid)
    r = load(ROSTER, {})
    r[name] = uid
    json.dump(r, open(ROSTER, "w"), ensure_ascii=False, indent=2)
    ids = allowed_ids()
    if uid not in ids:
        ids.append(uid)
        write_allowed(ids)
    return route


LABELS = f"{H}/shared-tools/admin/labels.json"


def remember_name(name, label):
    """The tester's name (given by the owner when making the link): the agent remembers it and calls them by it."""
    d = f"{H}/profiles/{name}"
    os.makedirs(f"{d}/memories", exist_ok=True)
    um = f"{d}/memories/USER.md"
    entry = f"User: {label} (اسم این کاربر «{label}» است؛ او تست‌کننده‌ی ایجنت هرمس است). همیشه او را با همین اسم، «{label}»، صدا بزن."
    old = open(um, encoding="utf-8").read().strip() if os.path.exists(um) else ""
    if label not in old:
        open(um, "w", encoding="utf-8").write(entry + ("\n§\n" + old if old else "") + "\n")
    soul = f"{d}/SOUL.md"
    if os.path.exists(soul) and "## اسم کاربر" not in open(soul, encoding="utf-8").read():
        with open(soul, "a", encoding="utf-8") as f:
            f.write(f"\n\n## اسم کاربر\nاسم این کاربر «{label}» است (تست‌کننده‌ی ایجنت هرمس). در جواب‌ها او را با همین اسم صدا بزن، گرم و محترمانه.\n")


def remove_route(name):
    text = open(CONFIG).read()
    # only this route's own lines: the "- name:" line + its deeper-indented keys (never the next "- name:" item)
    m = re.search(rf"^([ \t]*)-[ \t]*name:[ \t]*['\"]?{re.escape(name)}-dm['\"]?[ \t]*\n(?:\1[ \t]+(?!-)[^\n]*\n){{0,6}}", text, re.M)
    if not m:
        return "absent"
    shutil.copy2(CONFIG, f"/root/backups/config.yaml.bak-{time.strftime('%Y%m%d-%H%M%S')}-deluser")
    open(CONFIG, "w").write(text[:m.start()] + text[m.end():])
    return "removed"


TRIAL_TOKENS_DEFAULT = 300_000      # owner 2026-11-16: token quota per 24 h test (input + output); +10% per bonus press


def trial_usage(code, t=None):
    """Tokens (input + output, cache reads excluded) used by a test account since it was opened, against its quota."""
    t = t or load(TRIALS, {})
    v = t.get(code) or {}
    base = int(v.get("quota") or tiers_cfg().get("trial_tokens") or TRIAL_TOKENS_DEFAULT)
    quota = base + int(v.get("bonus_tokens") or 0)
    used = 0
    if v.get("used"):
        name, since = v["used"][0]["name"], v["used"][0].get("at") or 0
        try:
            c = sqlite3.connect(f"file:{H}/profiles/{name}/state.db?mode=ro", uri=True)
            used = c.execute("SELECT COALESCE(SUM(input_tokens),0) + COALESCE(SUM(output_tokens),0) FROM session_model_usage WHERE last_seen >= ?",
                             (since,)).fetchone()[0] or 0
        except Exception as e:
            print(f"usage {code}: {e}", file=sys.stderr)
    return {"code": code, "used": int(used), "quota": quota, "base": base, "bonus": int(v.get("bonus_tokens") or 0),
            "pct": round(used * 100 / quota, 1) if quota else 0}


def trial_bonus(code):
    """+10% of the base quota (owner button «➕ ۱۰٪ سهمیه‌ی بیشتر»)."""
    t = load(TRIALS, {})
    v = t.get(code)
    if not v:
        return {"ok": False, "error": "not_found"}
    u = trial_usage(code, t)
    add = int(round(u["base"] * 0.10))
    v["bonus_tokens"] = int(v.get("bonus_tokens") or 0) + add
    v.setdefault("bonus_log", []).append({"at": time.time(), "tokens": add})
    v.pop("quota_alerted", None)
    save_json(TRIALS, t)
    return {"ok": True, "added": add, **trial_usage(code, t)}


def trial_extend(code):
    """Owner button «⏱ تمدید ۲۴ ساعت» (2026-11-17): +24 h to the test window (from now if it already ended), un-pause,
    + one full base token quota (owner chose this), logged in trials.json; the tester is told."""
    t = load(TRIALS, {})
    v = t.get(code)
    if not v or v.get("profile") or not v.get("used"):
        return {"ok": False, "error": "not_found"}
    u = v["used"][0]
    name, uid, now = u["name"], u["uid"], time.time()
    tt = tiers()
    rec = tt.get(name)
    if not rec:
        return {"ok": False, "error": "no_tier"}
    rec["until"] = max(rec.get("until") or now, now) + 86400
    rec["paused"] = False
    rec["reminded"] = None
    save_json(TIERS, tt)
    restart = False
    ids = allowed_ids()
    if uid not in ids:                              # paused/expired the old way: put the id back
        write_allowed(ids + [uid])
        restart = True
    base = trial_usage(code, t)["base"]
    v["bonus_tokens"] = int(v.get("bonus_tokens") or 0) + base
    v.setdefault("extensions", []).append({"at": now, "hours": 24, "tokens": base, "until": rec["until"]})
    v.pop("quota_alerted", None)
    save_json(TRIALS, t)
    try:
        bot_send(uid, "⏱ تست ایجنت هرمس ۲۴ ساعت تمدید شد و سهمیه‌ات هم تازه شد. می‌توانی ادامه بدهی 🌹")
    except Exception as e:
        print(f"extend notice {name}: {e}", file=sys.stderr)
    return {"ok": True, "name": name, "until": rec["until"], "count": len(v["extensions"]), "restart_needed": restart,
            **trial_usage(code, t)}


def trial_accounts():
    """Every test link with its account: who, profile, status (waiting / active / paused / expired / closed), days left."""
    res = []
    allowed = allowed_ids()
    for code, v in sorted(load(TRIALS, {}).items(), key=lambda kv: -kv[1].get("created", 0)):
        if v.get("profile"):                      # 'join-' invites to existing profiles are not test links
            continue
        row = {"code": code, "label": v.get("label") or "", "tier": v.get("tier", "premium"), "days": v.get("days"),
               "ext": len(v.get("extensions") or []),
               "created": v.get("created"), "link": f"https://t.me/your_agent_bot?start=test-{code}"}
        if v.get("deleted"):
            row["status"] = "deleted"
        elif v["used"]:
            u = v["used"][0]
            name = u["name"]
            ti = tier_info(name) if name in user_profiles() else {}
            row.update(profile=name, uid=u["uid"], display=u.get("display"), at=u.get("at"), until=ti.get("until"))
            row.update({k: v_ for k, v_ in trial_usage(code).items() if k in ("used", "quota", "pct")})
            try:
                row["last_activity"] = info(name).get("last_activity") if name in user_profiles() else None
            except Exception as e:
                print(f"trial info {name}: {e}", file=sys.stderr)
            row["status"] = ("paused" if (ti.get("paused") or u["uid"] not in allowed) else "expired" if not ti.get("active", True) else "active")
        else:
            row["status"] = "waiting" if v.get("open") else "closed"
        res.append(row)
    return res


def trial_control(code, action):
    t = load(TRIALS, {})
    v = t.get(code)
    if not v or v.get("profile"):
        return {"ok": False, "error": "not_found"}
    if not v["used"]:                               # never opened: pause/delete = close the link
        v["open"] = False
        if action == "delete":
            v["deleted"] = time.time()
        save_json(TRIALS, t)
        return {"ok": True, "closed_link": True}
    u = v["used"][0]
    name, uid = u["name"], u["uid"]
    ids = allowed_ids()
    if action in ("pause", "resume"):
        tt = tiers()
        if name in tt:
            tt[name]["paused"] = action == "pause"
            save_json(TIERS, tt)
        if action == "resume" and uid not in ids:     # older pauses removed the id from the allow-list
            ids.append(uid)
            write_allowed(ids)
            return {"ok": True, "name": name, "status": "active", "restart_needed": True}
        return {"ok": True, "name": name, "status": "paused" if action == "pause" else "active"}
    if action == "delete":
        if not re.fullmatch(r"test\d{2,3}", name):    # safety: only auto-created test accounts are ever deleted here
            return {"ok": False, "error": "not_a_test_profile"}
        sess = f"{H}/profiles/{name}/userbot/{name}"
        if os.path.exists(sess + ".session"):         # tester linked their Telegram: end that login on Telegram's side too
            try:
                subprocess.run([f"{H}/tools/python-3.14.7+20260901-linux-x64/bin/python3", f"{H}/shared-tools/userbot/login.py", "logout", sess],
                               capture_output=True, text=True, timeout=60)
            except Exception as e:
                print(f"trial logout {name}: {e}", file=sys.stderr)
        write_allowed([i for i in ids if i != uid])
        remove_route(name)
        r = load(ROSTER, {})
        r.pop(name, None)
        json.dump(r, open(ROSTER, "w"), ensure_ascii=False, indent=2)
        for f in (TIERS, LABELS):
            d = load(f, {})
            d.pop(name, None)
            save_json(f, d)
        subprocess.run(["/bin/sh", "-c", f"docker ps -aq --filter volume=/root/.hermes/profiles/{name}/home | xargs -r docker rm -f; "
                        f"for c in $(docker ps -aq --filter ancestor=hermes-user-sandbox:1); do docker inspect $c --format '{{{{range .Mounts}}}}{{{{.Source}}}} {{{{end}}}}' | grep -q '/profiles/{name}/' && docker rm -f $c; done"],
                       capture_output=True, timeout=60)
        shutil.rmtree(f"{H}/profiles/{name}", ignore_errors=True)   # owner asked for full deletion: the tester's data goes too
        # the gateway may still write a "logs" dir while it stops serving the profile: sweep again a bit later
        subprocess.Popen(["/bin/sh", "-c", f"sleep 45; rm -rf '{H}/profiles/{name}'"], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        v["deleted"] = time.time()
        v["open"] = False
        save_json(TRIALS, t)
        return {"ok": True, "name": name, "status": "deleted", "restart_needed": True}
    return {"ok": False, "error": "bad_action"}


def cmd_trial_new(seats, days, tier="premium", label=""):
    import secrets
    if tier not in ("basic", "premium"):
        return out({"ok": False, "error": "bad_tier"})
    t = load(TRIALS, {})
    code = secrets.token_hex(4)
    t[code] = {"seats": seats, "days": days, "tier": tier, "label": label.strip()[:40], "used": [], "created": time.time(), "open": True}
    save_json(TRIALS, t)
    out({"ok": True, "code": code, "link": f"https://t.me/your_agent_bot?start=test-{code}", **t[code]})


def cmd_invite(name):
    import secrets
    if name not in user_profiles():
        return out({"ok": False, "error": "no_such_profile"})
    if roster().get(name):
        return out({"ok": False, "error": "already_bound", "tg_id": roster().get(name)})
    t = load(TRIALS, {})
    for c, v in t.items():                       # reuse an open, unused invite for the same profile
        if v.get("profile") == name and v.get("open") and not v["used"]:
            return out({"ok": True, "code": c, "link": f"https://t.me/your_agent_bot?start=join-{c}", "reused": True})
    code = secrets.token_hex(4)
    t[code] = {"seats": 1, "days": tiers_cfg().get("trial_days", 3), "tier": "basic", "profile": name, "label": name,
               "used": [], "created": time.time(), "open": True}
    save_json(TRIALS, t)
    out({"ok": True, "code": code, "link": f"https://t.me/your_agent_bot?start=join-{code}"})


def cmd_trial_claim(code, uid, display):
    t = load(TRIALS, {})
    tr = t.get(code)
    if not tr or not tr.get("open"):
        return out({"ok": False, "error": "closed"})
    if len(tr["used"]) >= tr["seats"]:
        return out({"ok": False, "error": "full"})
    if uid == OWNER_ID or uid in routes().values() or uid in roster().values():
        return out({"ok": False, "error": "already_user"})
    if tr.get("profile"):                         # invite to an existing, still unbound profile
        name = tr["profile"]
        if roster().get(name):
            return out({"ok": False, "error": "closed"})
        bind(name, uid)
        if name not in tiers():
            set_tier(name, "basic", tr["days"], own=False)
    else:
        n = 1
        while os.path.exists(f"{H}/profiles/test{n:02d}"):
            n += 1
        name = f"test{n:02d}"
        p = subprocess.run([sys.executable, __file__, "create", name], capture_output=True, text=True, timeout=300)
        if '"ok": true' not in p.stdout:
            return out({"ok": False, "error": "create_failed", "detail": p.stdout[-200:]})
        bind(name, uid)
        set_tier(name, tr.get("tier", "premium"), tr["days"], own=False)
    tr["used"].append({"uid": uid, "name": name, "display": display, "at": time.time()})
    ledger_add(name, "trial", 0, f"شروع آزمایشی {tr['days']} روزه ({tr.get('tier', 'premium')})" + (f" · {tr['label']}" if tr.get("label") else ""))
    if len(tr["used"]) >= tr["seats"]:
        tr["open"] = False                     # personal link: used up
    save_json(TRIALS, t)
    if tr.get("label"):
        lb = load(LABELS, {})
        lb[name] = tr["label"]
        save_json(LABELS, lb)
        remember_name(name, tr["label"])
    out({"ok": True, "name": name, "days": tr["days"], "tier": tiers().get(name, {}).get("tier", tr.get("tier", "premium")),
         "label": tr.get("label", ""), "invite": bool(tr.get("profile")),
         "left": tr["seats"] - len(tr["used"])})


def main():
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    c = a[0]
    if c == "list":
        cmd_list()
    elif c == "detail" and len(a) == 2:
        out(info(a[1]) if a[1] in user_profiles() else {"error": "no_such_profile"})
    elif c == "create" and len(a) == 2:
        cmd_create(a[1].strip().lower())
    elif c == "pending":
        cmd_pending()
    elif c == "activate" and len(a) == 3:
        cmd_activate(a[1], a[2].strip().lower())
    elif c == "set" and len(a) == 3:
        cmd_set(a[1].strip().lower(), a[2].strip().lower())
    elif c == "tier" and len(a) == 2:
        out(tier_info(a[1]))
    elif c == "set-tier" and len(a) == 4:
        try:
            r = set_tier(a[1].strip().lower(), a[2], int(a[3]))
            ledger_add(a[1].strip().lower(), "tier", 0, f"ادمین نسخه را {a[2]} کرد · " + (f"{a[3]} روز" if int(a[3]) else "دائمی"))
            out({"ok": True, **r})
        except ValueError as e:
            out({"ok": False, "error": str(e)})
    elif c == "order-new" and len(a) in (3, 4):
        cmd_order_new(a[1], a[2], a[3] if len(a) == 4 else "year")
    elif c == "quote" and len(a) == 2:
        cmd_quote(a[1])
    elif c == "order-receipt" and len(a) in (2, 3):
        od, err = order_set(a[1].lstrip("#"), "receipt_sent")
        if od and not err:
            ledger_add(od["name"], "receipt", od["price"], f"فیش سفارش #{a[1].lstrip('#')} رسید", ref=a[1].lstrip("#"), file=a[2] if len(a) == 3 else None)
        out({"ok": err is None, "error": err})
    elif c == "ledger" and len(a) == 2:
        out(ledger_view(a[1].strip().lower()))
    elif c == "ledger-add" and len(a) >= 4:
        typ = {"payment": "manual_payment"}.get(a[2], a[2])
        if typ not in ("manual_payment", "note", "refund") or a[1] not in user_profiles():
            out({"ok": False, "error": "bad_args"})
        else:
            out({"ok": True, **ledger_add(a[1], typ, int(re.sub(r"\D", "", a[3]) or 0), " ".join(a[4:]))})
    elif c == "ledger-file" and len(a) >= 4:
        if a[2] not in ("receipt", "doc") or a[1] not in user_profiles() or not os.path.exists(a[3]):
            out({"ok": False, "error": "bad_args"})
        else:
            out({"ok": True, **ledger_add(a[1], a[2], 0, " ".join(a[4:]) or ("فیش" if a[2] == "receipt" else "سند خرید"), file=a[3])})
    elif c == "ledger-backfill":
        out(ledger_backfill())
    elif c == "order-approve" and len(a) == 2:
        cmd_order_approve(a[1].lstrip("#"))
    elif c == "order-reject" and len(a) == 2:
        cmd_order_reject(a[1].lstrip("#"))
    elif c == "orders":
        out(load(ORDERS, {"next": 1, "orders": {}}))
    elif c == "expire":
        cmd_expire()
    elif c == "trial-new" and len(a) in (3, 4, 5):
        cmd_trial_new(int(a[1]), int(a[2]), a[3] if len(a) >= 4 else "premium", a[4] if len(a) == 5 else "")
    elif c == "trial-usage" and len(a) == 2:
        out(trial_usage(a[1]))
    elif c == "trial-bonus" and len(a) == 2:
        out(trial_bonus(a[1]))
    elif c == "trial-extend" and len(a) == 2:
        out(trial_extend(a[1]))
    elif c == "trial-accounts":
        out(trial_accounts())
    elif c in ("trial-pause", "trial-resume", "trial-delete") and len(a) == 2:
        out(trial_control(a[1], c.split("-")[1]))
    elif c == "trial-list":
        out(load(TRIALS, {}))
    elif c == "trial-close" and len(a) == 2:
        t = load(TRIALS, {})
        if a[1] in t:
            t[a[1]]["open"] = False
            save_json(TRIALS, t)
        out({"ok": a[1] in t})
    elif c == "invite" and len(a) == 2:
        cmd_invite(a[1].strip().lower())
    elif c == "trial-claim" and len(a) == 4:
        cmd_trial_claim(a[1], a[2], a[3])
    elif c == "credit":
        out(credit_check())
    elif c == "paid-watch":
        out({"hits": paid_model_watch()})
    elif c == "model-usage":
        cmd_model_usage()
    elif c == "restart":
        cmd_restart()
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
