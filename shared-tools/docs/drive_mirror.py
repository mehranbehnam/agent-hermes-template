#!/root/.hermes/shared-tools/docs/venv/bin/python
"""Google Drive side of the owner archive (owner decision 2026-11-13: files live ONLY on owner@example.com's Drive,
remote gdrive1; the server keeps only metadata in archive.db). Users' data never goes here.

  drive_mirror.py sync     # retry pending doc/media uploads, rebuild INDEX.md / INDEX.csv on Drive, refresh status
  drive_mirror.py check    # weekly: every archived item still on Drive? report to the owner
  drive_mirror.py status   # JSON status
Archive + remote come from docproc (HERMES_ARCHIVE_DIR / HERMES_ARCHIVE_REMOTE for another archive, HERMES_ARCHIVE_TEST for tests).
Run detached by docproc after each add/move, and nightly by /etc/cron.d/hermes-drive-mirror.
"""
import csv, fcntl, io, json, os, re, sqlite3, subprocess, sys, time, urllib.parse, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from docproc import ARCH, REMOTE_ROOT, _link, _rclone, _sidecar, db  # noqa: E402

STATUS = f"{ARCH}/.drive_status.json"
LOCK = f"{ARCH}/.drive.lock"
OWNER = "100000001"
IS_OWNER_ARCHIVE = ARCH == "/root/.hermes/archive-admin"


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), f"[{os.path.basename(ARCH)}]", msg, flush=True)


def status(**kw):
    try:
        s = json.load(open(STATUS))
    except Exception:
        s = {}
    s.update(kw)
    json.dump(s, open(STATUS, "w"), ensure_ascii=False, indent=1)
    os.chmod(STATUS, 0o600)
    return s


def report(text):
    if not IS_OWNER_ARCHIVE:
        return
    tok = re.search(r"^TELEGRAM_BOT_TOKEN=(.*)$", open("/root/.hermes/.env").read(), re.M).group(1).strip().strip('"')
    try:
        urllib.request.urlopen(urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage",
                                                      data=urllib.parse.urlencode({"chat_id": OWNER, "text": text}).encode()), timeout=20)
    except Exception as e:
        log(f"report failed: {e}")


def retry_pending(c):
    """Documents whose upload failed wait in <ARCH>/.pending (the only files ever kept on the server)."""
    d = f"{ARCH}/.pending"
    left = 0
    if not os.path.isdir(d):
        return 0
    for j in [x for x in os.listdir(d) if x.endswith(".json")]:
        try:
            p = json.load(open(os.path.join(d, j), encoding="utf-8"))
        except Exception as e:
            log(f"bad pending {j}: {e}")
            continue
        rc, _, err = _rclone("copyto", p["file"], p["remote"], "--retries", "2")
        if rc:
            left += 1
            log(f"pending upload still failing: {err.strip()[-200:]}")
            continue
        c.execute("UPDATE docs SET link=? WHERE id=?", (_link(p["remote"]), p["id"]))
        c.commit()
        _sidecar(p["id"], p["meta"], p["remote"])
        os.remove(p["file"])
        os.remove(os.path.join(d, j))
        log(f"pending doc {p['id']} uploaded")
    return left


def index_files(c):
    cell = lambda s: (s or "").replace("|", "/").replace("\n", " ")
    rel = lambda p: (p or "").replace(REMOTE_ROOT + "/", "")
    rows = c.execute("SELECT id, date, category, title, party, tags, path, link FROM docs ORDER BY date DESC, id DESC").fetchall()
    try:
        mrows = c.execute("SELECT id, date, folder, kind, title, caption, remote, link FROM media ORDER BY date DESC, id DESC").fetchall()
    except sqlite3.OperationalError:
        mrows = []
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "date", "category/folder", "title", "party/caption", "tags/kind", "path", "link"])
    md = ["# Hermes Archive — فهرست", "", f"به‌روزرسانی: {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())} · اسناد: {len(rows)} · مدیا: {len(mrows)}", "",
          "کنار هر سند یک فایل .txt با متن کامل و مشخصات آن هست.", "", "## اسناد", "", "| تاریخ | دسته | عنوان | طرف | مسیر | لینک |", "|---|---|---|---|---|---|"]
    for rid, date, cat, title, party, tags, path, link in rows:
        w.writerow([rid, date, cat, title, party, tags, rel(path), link or ""])
        md.append(f"| {cell(date)} | {cell(cat)} | {cell(title)} | {cell(party)} | {cell(rel(path))} | {link or ''} |")
    if mrows:
        md += ["", "## مدیا", "", "| تاریخ | پوشه | نوع | عنوان | توضیح | لینک |", "|---|---|---|---|---|---|"]
        for rid, date, folder, kind, title, cap, remote, link in mrows:
            w.writerow([f"m{rid}", date, f"Media/{folder}", title, cap, kind, rel(remote), link or ""])
            md.append(f"| {cell(date)} | {cell(folder)} | {kind} | {cell(title)} | {cell(cap)} | {link or ''} |")
    return {"INDEX.csv": "﻿" + buf.getvalue(), "INDEX.md": "\n".join(md) + "\n"}, len(rows), len(mrows)


def sync():
    if not os.path.exists(f"{ARCH}/archive.db"):
        log("no archive yet")
        return 0
    os.makedirs(ARCH, exist_ok=True)
    lk = open(LOCK, "w")
    try:
        fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        open(f"{ARCH}/.drive_again", "w").close()
        log("busy, queued another pass")
        return 0
    while True:
        try:
            os.remove(f"{ARCH}/.drive_again")
        except FileNotFoundError:
            pass
        if IS_OWNER_ARCHIVE:
            try:
                r = subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "media.py"), "retry"],
                                   capture_output=True, text=True, timeout=7200)
                if '"done": 0, "left": 0' not in r.stdout or r.returncode:
                    log(f"media retry: {r.stdout.strip()[-300:]} {r.stderr.strip()[-200:]}")
                if '"failed": [{' in r.stdout:
                    report("⚠️ چند فایل مدیا هنوز به Google Drive نرسیده؛ دوباره تلاش می‌شود.")
            except Exception as e:
                log(f"media retry failed: {e}")
        c = db()                                      # adds new columns on old databases
        left = retry_pending(c)
        files, nd, nm = index_files(c)
        err = ""
        for name, data in files.items():
            rc, _, e = _rclone("rcat", f"{REMOTE_ROOT}/{name}", inp=data, timeout=300)
            err = err or (e.strip()[-300:] if rc else "")
        if err:
            status(last_error=err, last_error_at=time.time())
            log(f"index upload failed: {err}")
        else:
            s = status(last_ok=time.time(), last_error=None, docs=nd, media=nm, pending=left)
            if not s.get("link"):
                parent, name = (REMOTE_ROOT.rsplit("/", 1) if "/" in REMOTE_ROOT.split(":", 1)[1] else (REMOTE_ROOT.split(":")[0] + ":", REMOTE_ROOT.split(":", 1)[1]))
                rc, o, _ = _rclone("lsjson", "--dirs-only", parent, timeout=120)
                try:
                    fid = next(d["ID"] for d in json.loads(o) if d.get("Name") == name)
                    status(link=f"https://drive.google.com/drive/folders/{fid}")
                except Exception as e:
                    log(f"folder link lookup failed: {e}")
            log(f"sync ok ({nd} docs, {nm} media, {left} pending)")
        if not os.path.exists(f"{ARCH}/.drive_again"):
            return 1 if err else 0


def check():
    if not os.path.exists(f"{ARCH}/archive.db"):
        return 0
    rc, o, err = _rclone("lsf", "-R", "--files-only", REMOTE_ROOT, timeout=1800)
    if rc:
        log(f"check: cannot list Drive: {err[-200:]}")
        report("☁️ بررسی هفتگی Google Drive انجام نشد: Drive جواب نداد. اگر تکرار شد خبرم کن.")
        return 1
    have = set(o.split("\n"))
    c = db()                                      # adds new columns on old databases
    want = [p for (p,) in c.execute("SELECT path FROM docs") if p and p.startswith(REMOTE_ROOT)]
    try:
        want += [p for (p,) in c.execute("SELECT remote FROM media") if p and p.startswith(REMOTE_ROOT)]
    except sqlite3.OperationalError:
        pass
    missing = [p for p in want if p.replace(REMOTE_ROOT + "/", "") not in have]
    status(last_check=time.time(), check_ok=not missing, check_missing=len(missing))
    log(f"check: {len(want)} items, {len(missing)} missing")
    report(f"☁️ بررسی هفتگی Google Drive: همه‌ی {len(want)} فایل بایگانی در Drive هست. ✅" if not missing else
           f"⚠️ بررسی هفتگی Google Drive: {len(missing)} فایل از {len(want)} در Drive پیدا نشد (شاید دستی پاک شده). بگو بررسی کنم.")
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "sync":
        sys.exit(sync())
    elif cmd == "check":
        sys.exit(check())
    elif cmd == "status":
        try:
            print(json.dumps(json.load(open(STATUS)), ensure_ascii=False))
        except Exception:
            print("{}")
    else:
        sys.exit(__doc__)
