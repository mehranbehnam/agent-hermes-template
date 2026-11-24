#!/usr/bin/python3
"""Search Owner's OWN phone files (owner request 2026-11-19: «عکس‌های گوشیم رو بگرد»).
The phone (Termux + rsync) pushes photos/screenshots/downloads to /home/owner-phone/upload every 30 min
(restricted SSH user, rrsync-only). This indexes the text INSIDE them (Tesseract OCR fa+en for images,
pdftotext for PDFs, plain text files) so the owner's agent can find "the photo where I wrote X".

  phone_index.py index            # (cron) OCR new/changed files only
  phone_index.py search "<text>" [n]   # matches: path, date, snippet (Persian letter variants normalised)
  phone_index.py status           # files, indexed, last sync, last index
  phone_index.py fetch "<phone path>" [wait_s]   # ask the phone for one file; prints the local path when it arrives
v2 (same day): the phone runs phone_agent.py itself — it OCRs ON the phone and sends only text (_in/*.jsonl);
whole files travel only on request (_req/<id>.json -> _files/<id>/). Paths starting "phone:" live on the phone.
Owner only: the admin-panel blocks this script for every other profile.
"""
import json, os, re, sqlite3, subprocess, sys, time

ROOT = "/home/owner-phone/upload"
DB = "/root/.hermes/phone-index/index.db"
IMG = (".jpg", ".jpeg", ".png", ".webp", ".heic", ".bmp")
TXT = (".txt", ".md", ".csv", ".json")
SPECIAL = {"_in", "_req", "_files", "_tools"}


def norm(s):
    s = (s or "").replace("ي", "ی").replace("ك", "ک").replace("‌", " ").replace("ة", "ه")
    s = re.sub(r"[ً-ْ]", "", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def db():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    c = sqlite3.connect(DB)
    c.execute("CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, mtime REAL, size INT, text TEXT, norm TEXT, indexed REAL, err TEXT)")
    return c


def extract(p):
    ext = os.path.splitext(p)[1].lower()
    if ext in IMG:
        src = p
        if ext == ".heic":                                   # tesseract can't read HEIC: convert first
            src = "/tmp/phone_ocr.png"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", p, src], timeout=60, check=True)
        r = subprocess.run(["tesseract", src, "stdout", "-l", "fas+eng", "--psm", "3"], capture_output=True, text=True, timeout=120)
        return r.stdout
    if ext == ".pdf":
        return subprocess.run(["pdftotext", "-l", "30", p, "-"], capture_output=True, text=True, timeout=120).stdout
    if ext in TXT:
        return open(p, errors="ignore").read(200_000)
    return ""


def index():
    c = db()
    fd = os.path.join(ROOT, "_files")                 # files fetched for the agent: kept 24 h only
    if os.path.isdir(fd):
        import shutil
        for x in os.listdir(fd):
            q = os.path.join(fd, x)
            if time.time() - os.path.getmtime(q) > 86400:
                shutil.rmtree(q, ignore_errors=True)
    known = {r[0]: (r[1], r[2]) for r in c.execute("SELECT path, mtime, size FROM files")}
    seen, done, errs = set(), 0, 0
    ingest(c)
    for base, dirs, names in os.walk(ROOT):
        if base == ROOT:
            dirs[:] = [d for d in dirs if d not in SPECIAL]
        for n in names:
            p = os.path.join(base, n)
            seen.add(p)
            try:
                st = os.stat(p)
            except FileNotFoundError:
                continue
            if known.get(p) == (st.st_mtime, st.st_size):
                continue
            text, err = "", None
            try:
                text = extract(p)
            except Exception as e:
                err = f"{type(e).__name__}: {e}"[:200]
                errs += 1
                print(f"index {p}: {err}", file=sys.stderr)
            c.execute("INSERT OR REPLACE INTO files VALUES(?,?,?,?,?,?,?)", (p, st.st_mtime, st.st_size, text, norm(text), time.time(), err))
            done += 1
            if done % 50 == 0:
                c.commit()
    gone = [p for p in known if p not in seen and not p.startswith("phone:")]                 # deleted on the phone side
    c.executemany("DELETE FROM files WHERE path=?", [(p,) for p in gone])
    c.commit()
    print(json.dumps({"ok": True, "indexed": done, "errors": errs, "removed": len(gone), "at": time.strftime("%F %T")}))


def ingest(c):
    """Text index made ON the phone (phone_agent.py index)."""
    d = os.path.join(ROOT, "_in")
    if not os.path.isdir(d):
        return
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".jsonl"):
            continue
        fp = os.path.join(d, fn)
        for line in open(fp, errors="ignore"):
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if o.get("meta"):
                c.execute("CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT)")
                c.execute("INSERT OR REPLACE INTO meta VALUES('phone', ?)", (json.dumps(o),))
                continue
            key = "phone:" + o["p"]
            if o.get("del"):
                c.execute("DELETE FROM files WHERE path=?", (key,))
                continue
            t = o.get("t") or ""
            # the file NAME is searchable too (e.g. "passport.pdf", "IMG_2026...")
            c.execute("INSERT OR REPLACE INTO files VALUES(?,?,?,?,?,?,?)",
                      (key, o.get("m"), o.get("s"), t, norm(o["p"].replace("/", " ") + " " + t), time.time(), o.get("e")))
        c.commit()
        os.remove(fp)


def fetch(rel, wait=420):
    import uuid
    rel = rel[len("phone:"):] if rel.startswith("phone:") else rel
    rid = uuid.uuid4().hex[:12]
    os.makedirs(os.path.join(ROOT, "_req"), exist_ok=True)
    rq = os.path.join(ROOT, "_req", rid + ".json")
    json.dump({"path": rel, "at": time.time()}, open(rq, "w"), ensure_ascii=False)
    os.system(f"chown owner-phone:owner-phone '{rq}'; chmod 640 '{rq}'")
    dst = os.path.join(ROOT, "_files", rid)
    t0 = time.time()
    while time.time() - t0 < wait:
        if os.path.isdir(dst):
            fs = [f for f in os.listdir(dst) if not f.startswith(".")]
            if fs:
                os.remove(rq)
                f = os.path.join(dst, fs[0])
                if fs[0].startswith("missing-"):
                    return print(json.dumps({"ok": False, "error": "not on the phone any more", "path": rel}, ensure_ascii=False))
                return print(json.dumps({"ok": True, "file": f, "phone_path": rel}, ensure_ascii=False))
        time.sleep(5)
    print(json.dumps({"ok": False, "error": f"phone did not answer in {wait}s (phone off / no internet / Termux closed); the request stays queued",
                      "request": rid}, ensure_ascii=False))


def plist(folder, d0, d1):
    """Phone files in a folder (prefix) and date range — works even before their text has been read."""
    import datetime as dt
    t0 = dt.datetime.fromisoformat(d0).timestamp()
    t1 = dt.datetime.fromisoformat(d1).timestamp() + 86400
    rows = db().execute("SELECT path, mtime, err, length(text) FROM files WHERE path LIKE ? AND mtime BETWEEN ? AND ? ORDER BY mtime",
                        (f"phone:{folder}%", t0, t1)).fetchall()
    print(json.dumps({"ok": True, "count": len(rows), "items": [
        {"path": p, "date": time.strftime("%Y-%m-%d %H:%M", time.localtime(m)), "text": "pending" if e == "pending" else (n or 0)}
        for p, m, e, n in rows[:300]]}, ensure_ascii=False))


def psheet(folder, d0, d1, wait=900):
    """Ask the phone for contact sheets (40 thumbnails each, numbered, dated) of every photo in folder/date range."""
    import uuid
    rid = uuid.uuid4().hex[:12]
    os.makedirs(os.path.join(ROOT, "_req"), exist_ok=True)
    rq = os.path.join(ROOT, "_req", rid + ".json")
    json.dump({"type": "sheet", "folder": folder, "from": d0, "to": d1, "at": time.time()}, open(rq, "w"))
    os.system(f"chown owner-phone:owner-phone '{rq}'; chmod 640 '{rq}'")
    dst = os.path.join(ROOT, "_files", rid)
    t0 = time.time()
    while time.time() - t0 < wait:
        ix = os.path.join(dst, "index.json")
        if os.path.exists(ix):
            time.sleep(3)
            os.remove(rq)
            sheets = sorted(os.path.join(dst, f) for f in os.listdir(dst) if f.startswith("sheet-"))
            d = json.load(open(ix))
            return print(json.dumps({"ok": True, "photos": d["count"], "sheets": sheets, "items": d["items"][:400]}, ensure_ascii=False))
        time.sleep(5)
    print(json.dumps({"ok": False, "error": f"phone did not answer in {wait}s (Termux closed / no internet); request stays queued", "request": rid}))


def search(q, n=10):
    c = db()
    words = [w for w in norm(q).split() if len(w) > 1]
    if not words:
        return print(json.dumps({"ok": False, "error": "empty query"}))
    rows = c.execute("SELECT path, mtime, norm, text FROM files WHERE " + " OR ".join(["norm LIKE ?"] * len(words)),
                     [f"%{w}%" for w in words]).fetchall()
    scored = []
    for p, mt, nt, t in rows:
        hits = sum(1 for w in words if w in nt)
        i = min((nt.find(w) for w in words if w in nt), default=0)
        scored.append((hits, mt, p, nt[max(0, i - 60): i + 120]))
    scored.sort(key=lambda x: (-x[0], -x[1]))
    print(json.dumps({"ok": True, "query": q, "total": len(scored),
                      "results": [{"path": p, "date": time.strftime("%Y-%m-%d %H:%M", time.localtime(mt)),
                                   "matched_words": h, "of": len(words), "snippet": s} for h, mt, p, s in scored[:n]]},
                     ensure_ascii=False))


def status():
    c = db()
    tot, last = c.execute("SELECT COUNT(*), MAX(indexed) FROM files").fetchone()
    with_text = c.execute("SELECT COUNT(*) FROM files WHERE length(norm) > 10").fetchone()[0]
    newest = c.execute("SELECT MAX(indexed) FROM files WHERE path LIKE 'phone:%'").fetchone()[0]
    try:
        meta = json.loads(c.execute("SELECT v FROM meta WHERE k='phone'").fetchone()[0])
    except Exception:
        meta = {}
    pend = c.execute("SELECT COUNT(*) FROM files WHERE err='pending'").fetchone()[0]
    print(json.dumps({"text_still_to_read_on_phone": pend, "phone_last_report": time.strftime("%F %T", time.localtime(meta["at"])) if meta.get("at") else None,
                      "files_indexed": tot, "with_text": with_text,
                      "last_index": time.strftime("%F %T", time.localtime(last)) if last else None,
                      "newest_file_from_phone": time.strftime("%F %T", time.localtime(newest)) if newest else None,
                      "phone_synced_ever": bool(newest)}, ensure_ascii=False))


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["index"]:
        index()
    elif a[:1] == ["search"] and len(a) >= 2:
        search(a[1], int(a[2]) if len(a) > 2 else 10)
    elif a[:1] == ["fetch"] and len(a) >= 2:
        fetch(a[1], int(a[2]) if len(a) > 2 else 420)
    elif a[:1] == ["list"] and len(a) >= 2:
        plist(a[1], a[2] if len(a) > 2 else "2000-01-01", a[3] if len(a) > 3 else "2100-01-01")
    elif a[:1] == ["sheet"] and len(a) >= 2:
        psheet(a[1], a[2] if len(a) > 2 else "2000-01-01", a[3] if len(a) > 3 else "2100-01-01")
    elif a[:1] == ["status"]:
        status()
    else:
        sys.exit(__doc__)
