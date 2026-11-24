#!/usr/bin/python3
"""Agent Hermes doctor: deterministic health checks + a few SAFE fixes, for the owner's admin panel when no
Claude session is around. No LLM involved. Never prints secrets or user content. Prints JSON.

  doctor.py check                 # all checks -> [{"id","ok","level","title","detail","fix"}]
  doctor.py fix restart           # restart the gateway (detached, ~20 s)
  doctor.py fix clean             # free disk: Hermes caches older than 2 days, rotated journals
  doctor.py fix nous-login        # start a Nous Portal device login; prints the approval link; on success the
                                  #   background waiter restarts the gateway and messages the owner
  doctor.py user <profile>        # checks for ONE user's profile (route, access, subscription, DB, recent errors, stuck turn)
  doctor.py userfix <profile>     # safe repairs for that profile; restarts the gateway only when needed
"""
import glob, json, os, re, subprocess, sys, time, calendar, urllib.request

H = "/root/.hermes"
ENV = f"{H}/.env"
HERMES = "/root/.local/bin/hermes"
OWNER = "100000001"
CONFIGS = [f"{H}/config.yaml"] + sorted(glob.glob(f"{H}/profiles/*/config.yaml"))


def sh(cmd, timeout=60):
    p = subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout + p.stderr).strip()


def env(key):
    m = re.search(rf"^{key}=(.*)$", open(ENV).read(), re.M)
    return m.group(1).strip().strip('"') if m else ""


def item(cid, ok, title, detail="", fix=None, level=None):
    return {"id": cid, "ok": ok, "level": level or ("ok" if ok else "fail"), "title": title, "detail": detail, "fix": fix}


def check():
    res = []
    rc, o = sh(["systemctl", "--user", "is-active", "hermes-gateway"])
    res.append(item("gateway", o == "active", "سرویس ایجنت (گیت‌وی)", "فعال" if o == "active" else f"وضعیت: {o}", None if o == "active" else "restart"))

    rc, o = sh("journalctl --user -u hermes-gateway --since '-30min' --no-pager", 60)
    connected = "Connected to Telegram" in o
    rc2, o2 = sh("journalctl --user -u hermes-gateway --since '-6h' --no-pager | grep -c 'Connected to Telegram'", 60)
    res.append(item("telegram", connected or (o2.strip() not in ("", "0")), "اتصال به تلگرام",
                    "وصل" if (connected or o2.strip() not in ("", "0")) else "در ۶ ساعت اخیر اتصال ثبت نشده", "restart"))
    errs = {"429 سقف/شلوغی مدل": len(re.findall(r"Error code: 429", o)), "404 مدل": len(re.findall(r"Error code: 404", o)),
            "401/403 ورود": len(re.findall(r"Error code: 40[13]", o)), "Traceback": o.count("Traceback")}
    bad = {k: v for k, v in errs.items() if v}
    res.append(item("errors", not bad, "خطاهای ۳۰ دقیقه‌ی اخیر",
                    "خطایی نیست" if not bad else " · ".join(f"{k}: {v}" for k, v in bad.items()), None, None if not bad else "warn"))

    import yaml
    broken = []
    for f in CONFIGS:
        try:
            yaml.safe_load(open(f))
        except Exception as e:
            broken.append(f"{f.replace(H + '/', '')}: {str(e)[:60]}")
    res.append(item("configs", not broken, "فایل‌های تنظیمات", f"همه‌ی {len(CONFIGS)} فایل سالم" if not broken else "؛ ".join(broken)))

    try:
        a = json.load(open(f"{H}/auth.json"))
        pool = (a.get("credential_pool") or {}).get("nous") or []
        err = (a.get("providers", {}).get("nous", {}).get("last_auth_error") or {})
        nous_ok = bool(pool) and not err.get("relogin_required")
    except Exception as e:
        nous_ok, err = False, {"message": str(e)}
    res.append(item("nous", nous_ok, "ورود به Nous (مدل‌های LongCat/StepFun)", "برقرار" if nous_ok else "ورود منقضی شده — ورود دوباره لازم است",
                    None if nous_ok else "nous-login"))

    try:
        key = env("OPENROUTER_API_KEY")
        d = json.load(urllib.request.urlopen(urllib.request.Request("https://openrouter.ai/api/v1/key",
                                                                    headers={"Authorization": "Bearer " + key}), timeout=20))["data"]
        q = d.get("free_model_daily_requests") or {}
        exp = d.get("expires_at", "")[:10]
        left = q.get("remaining", 0)
        res.append(item("openrouter", left > 0, "سهمیه‌ی رایگان OpenRouter (ERNIE)",
                        f"امروز {q.get('used', 0)} از {q.get('limit', 0)} · باقی {left} · انقضای کلید {exp}"
                        + ("" if left > 0 else " — تا ۳:۳۰ بامداد تهران با مدل‌های پشتیبان جواب داده می‌شود؛ راه دائمی: شارژ ۱۰ دلار"),
                        None, None if left > 0 else "warn"))
    except Exception as e:
        res.append(item("openrouter", False, "سهمیه‌ی رایگان OpenRouter (ERNIE)", f"خواندن ممکن نشد: {type(e).__name__}", None, "warn"))

    try:
        gk = env("GEMINI_API_KEY")
        urllib.request.urlopen(urllib.request.Request("https://generativelanguage.googleapis.com/v1beta/models?pageSize=1",
                                                      headers={"x-goog-api-key": gk}), timeout=20)
        res.append(item("gemini", True, "کلید Gemini (مدل اصلی)", "فعال"))
    except urllib.error.HTTPError as e:
        res.append(item("gemini", False, "کلید Gemini (مدل اصلی)",
                        f"خطای {e.code} — اگر 403 است احتمالاً گوگل کلید را مسدود کرده؛ ایجنت خودکار با ERNIE ادامه می‌دهد. کلید تازه در aistudio.google.com/apikey بساز."))
    except Exception as e:
        res.append(item("gemini", False, "کلید Gemini (مدل اصلی)", f"بررسی ممکن نشد: {type(e).__name__}", None, "warn"))
    rc, o = sh("df -P / | awk 'NR==2{print $5}'")
    pct = int(o.strip().rstrip("%") or 0)
    res.append(item("disk", pct < 90, "فضای دیسک", f"{pct}% پر", None if pct < 90 else "clean", "ok" if pct < 85 else ("warn" if pct < 90 else "fail")))

    flag = f"{H}/shared-tools/admin/.restart-pending"
    stuck = os.path.exists(flag) and time.time() - os.path.getmtime(flag) > 300
    res.append(item("restartflag", not stuck, "ری‌استارت در انتظار", "گیر کرده (بیش از ۵ دقیقه)" if stuck else "عادی", "restart" if stuck else None))

    try:
        last = os.path.getmtime(f"{H}/ads/stats/divar_ads.log")
        ok = time.time() - last < 2 * 3600
        res.append(item("divar", ok, "تبلیغ ساعتی دیوار", f"آخرین اجرا {int((time.time() - last) // 60)} دقیقه پیش",
                        None, "ok" if ok else "warn"))
    except FileNotFoundError:
        pass
    return res


ADMIN = f"{H}/shared-tools/admin"


def _uinfo(name):
    roster = json.load(open(f"{ADMIN}/roster.json"))
    tg = roster.get(name)
    routed = bool(tg) and bool(re.search(rf"chat_id:\s*['\"]?{tg}['\"]?\s*\n\s*profile:\s*{name}\b", open(f"{H}/config.yaml").read()))
    allowed = bool(tg) and tg in (re.search(r"^TELEGRAM_ALLOWED_USERS=(.*)$", open(ENV).read(), re.M).group(1).split(","))
    try:
        t = json.load(open(f"{ADMIN}/tiers.json")).get(name) or {}
    except FileNotFoundError:
        t = {}
    until = t.get("until")
    return tg, routed, allowed, t.get("tier", "basic"), until, (until is None or until > time.time())


def user_check(name):
    d = f"{H}/profiles/{name}"
    if not os.path.isdir(d):
        return [item("profile", False, "پروفایل", "پیدا نشد")]
    res = []
    tg, routed, allowed, tier, until, active = _uinfo(name)
    res.append(item("bound", bool(tg), "اتصال به تلگرام", f"شناسه {tg}" if tg else "هنوز به کسی وصل نشده"))
    if tg:
        res.append(item("route", routed, "مسیر پیام‌ها به این پروفایل", "درست" if routed else "مسیر ثبت نشده — پیامش به پروفایل درست نمی‌رسد", "route"))
        res.append(item("allowed", allowed, "اجازه‌ی دسترسی", "دارد" if allowed else "قطع است (اگر عمداً قطع کرده‌ای، درست است)", None, "ok" if allowed else "warn"))
    res.append(item("tier", active, "اشتراک", ("پرمیوم" if tier == "premium" else "معمولی") + (" · دائمی" if until is None else
                    f" · تا {time.strftime('%Y-%m-%d', time.gmtime(until + 12600))}") + ("" if active else " — منقضی شده"), None, "ok" if active else "warn"))
    import yaml
    try:
        yaml.safe_load(open(f"{d}/config.yaml"))
        res.append(item("config", True, "تنظیمات پروفایل", "سالم"))
    except Exception as e:
        res.append(item("config", False, "تنظیمات پروفایل", f"خراب: {str(e)[:60]}"))
    db = f"{d}/state.db"
    try:
        import sqlite3
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
        qc = c.execute("PRAGMA quick_check").fetchone()[0]
        last_u = c.execute("SELECT MAX(timestamp) FROM messages WHERE role='user'").fetchone()[0] or 0
        last_a = c.execute("SELECT MAX(timestamp) FROM messages WHERE role='assistant'").fetchone()[0] or 0
        c.close()
        res.append(item("db", qc == "ok", "پایگاه داده‌ی گفتگوها", "سالم" if qc == "ok" else f"مشکل: {qc[:60]}", "dbrepair"))
        stuck = last_u > last_a + 120 and time.time() - last_u < 6 * 3600
        res.append(item("stuck", not stuck, "آخرین پیام کاربر", "جواب گرفته" if not stuck else
                        f"آخرین پیامش ({int((time.time() - last_u) // 60)} دقیقه پیش) جوابی نگرفته", "restart", "ok" if not stuck else "warn"))
    except Exception as e:
        res.append(item("db", False, "پایگاه داده‌ی گفتگوها", f"باز نشد: {type(e).__name__}", "dbrepair"))
    rc, o = sh(f"journalctl --user -u hermes-gateway --since '-2h' --no-pager | grep -E 'agent:{name}:' | grep -ciE 'error|failed|429|Traceback'", 60)
    n = int(o.strip() or 0) if o.strip().isdigit() else 0
    res.append(item("errors", n == 0, "خطاهای ۲ ساعت اخیر این کاربر", "ندارد" if n == 0 else f"{n} خطا (معمولاً شلوغی/سقف مدل)", None, "ok" if n == 0 else "warn"))
    return res


def user_fix(name):
    done, need_restart = [], False
    checks = {c["id"]: c for c in user_check(name)}
    tg, routed, allowed, tier, until, active = _uinfo(name)
    if tg and not routed:
        sys.path.insert(0, ADMIN)
        import importlib.util
        spec = importlib.util.spec_from_file_location("ua", f"{ADMIN}/users_admin.py")
        ua = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ua)
        ua.add_route(name, tg)
        done.append("مسیر پیام‌ها دوباره ثبت شد")
        need_restart = True
    if not checks.get("db", {}).get("ok", True):
        rc, o = sh([HERMES, "-p", name, "sessions", "repair"], 300)
        done.append("پایگاه داده‌ی گفتگوها تعمیر شد (با بک‌آپ)" if rc == 0 else "تعمیر پایگاه داده انجام نشد")
        need_restart = True
    rc, o = sh([HERMES, "-p", name, "sessions", "repair-prompts", "--apply", "--json"], 120)
    if rc == 0 and re.search(r'"cleared"\s*:\s*[1-9]', o):
        done.append("دستورالعمل‌های خراب گفتگو پاک شد")
    rc, o = sh([HERMES, "-p", name, "sessions", "repair-routing", "--apply"], 120)
    if not checks.get("stuck", {}).get("ok", True) or not checks.get("errors", {}).get("ok", True):
        need_restart = True
    if need_restart:
        fix("restart")
        done.append("ایجنت ری‌استارت شد تا تغییرات اعمال شود")
    if not done:
        done.append("مشکل فنی در حساب پیدا نشد؛ همه‌چیز بررسی و تأیید شد")
    notes = []
    if tg and not allowed:
        notes.append("دسترسی این کاربر قطع است؛ اگر باید وصل باشد، از صفحه‌ی کاربر «✅ وصل دسترسی» را بزن.")
    if not active:
        notes.append("اشتراکش تمام شده؛ تا تمدید نکند فقط منوی اشتراک را می‌بیند.")
    if any(c["id"] == "errors" and not c["ok"] for c in checks.values()):
        notes.append("خطاها بیشتر از شلوغی یا تمام شدن سهمیه‌ی مدل‌هاست که با شارژ OpenRouter کم می‌شود.")
    return {"ok": True, "done": done, "notes": notes, "restarted": need_restart}


def fix(action):
    if action == "restart":
        subprocess.Popen(["/bin/sh", "-c", f"sleep 3; rm -f {H}/shared-tools/admin/.restart-pending; {HERMES} gateway restart >/tmp/hermes-doctor-restart.log 2>&1"],
                         start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"ok": True, "msg": "ری‌استارت ایجنت شروع شد (حدود ۲۰ ثانیه)."}
    if action == "clean":
        before = sh("df -P / | awk 'NR==2{print $4}'")[1]
        sh(f"find {H}/cache {H}/profiles/*/cache -type f -mtime +2 -delete 2>/dev/null; journalctl --vacuum-time=7d >/dev/null 2>&1; "
           f"journalctl --user --vacuum-time=7d >/dev/null 2>&1", 300)
        after = sh("df -P / | awk 'NR==2{print $4}'")[1]
        freed = (int(after or 0) - int(before or 0)) // 1024
        return {"ok": True, "msg": f"پاک‌سازی انجام شد؛ حدود {max(0, freed)} مگابایت آزاد شد."}
    if action == "nous-login":
        log = "/tmp/hermes-doctor-nous-login.log"
        sh("tmux kill-session -t doctornous 2>/dev/null")
        tok = env("TELEGRAM_BOT_TOKEN")
        waiter = (f"cd /root && {HERMES} auth add nous --type oauth --no-browser --label doctor-{time.strftime('%Y%m%d%H%M')} > {log} 2>&1; "
                  f"if grep -q 'Saved nous' {log}; then {HERMES} gateway restart >/dev/null 2>&1; "
                  f"curl -s -o /dev/null --data-urlencode 'chat_id={OWNER}' --data-urlencode 'text=✅ ورود Nous انجام شد و ایجنت ری‌استارت شد.' "
                  f"https://api.telegram.org/bot{tok}/sendMessage; fi")
        subprocess.run(["tmux", "new-session", "-d", "-s", "doctornous", waiter], check=False)
        for _ in range(20):
            time.sleep(1)
            txt = open(log).read() if os.path.exists(log) else ""
            m = re.search(r"https://portal\.nousresearch\.com/\S+", txt)
            if m:
                return {"ok": True, "msg": "این لینک را باز کن و با حساب Nous تأیید بزن؛ بعدش ایجنت خودش ری‌استارت می‌شود و خبرت می‌کنم:",
                        "link": m.group(0)}
        return {"ok": False, "msg": "لینک ورود ساخته نشد؛ کمی بعد دوباره امتحان کن."}
    return {"ok": False, "msg": "کار ناشناخته"}


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["check"]:
        print(json.dumps(check(), ensure_ascii=False))
    elif a[:1] == ["user"] and len(a) == 2:
        print(json.dumps(user_check(a[1]), ensure_ascii=False))
    elif a[:1] == ["userfix"] and len(a) == 2:
        print(json.dumps(user_fix(a[1]), ensure_ascii=False))
    elif a[:1] == ["fix"] and len(a) == 2:
        print(json.dumps(fix(a[1]), ensure_ascii=False))
    else:
        sys.exit(__doc__)
