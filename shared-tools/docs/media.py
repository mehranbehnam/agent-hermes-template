#!/root/.hermes/shared-tools/docs/venv/bin/python
"""OWNER media archive (owner request 2026-11-12 via HermesVPN). Files live ONLY on his Google Drive
("Hermes Archive/Media/<folder>/<YYYY>/<MM>/"); the server keeps one metadata row per item (archive.db, table media)
so search / history / ⬇️ work. The local temp copy is deleted after a successful upload; failed uploads wait in
/tmp/hermes-media-retry and are retried (nightly by drive_mirror.py, or `media.py retry`). Prints JSON.

  media.py add <file> <metajson>        meta: folder, caption, orig_name   (folder "" -> auto by type)
  media.py prompt <textfile> <folder>   a prompt saved as .md (title = first line)
  media.py attach <id> <file>           result (image/video) of a prompt, uploaded next to it
  media.py search <q> | recent [n] | folders | list <folder> | get <id> | chart <out.png> | retry
  media.py fetch <id> <outdir>          download the item from Drive for ⬇️ (caller deletes it after sending)
  media.py bigfetch <outdir> <size> <unix_ts>   >20 MB: fetch the file from the owner's OWN chat with the bot,
                                                through his own Telegram session (Bot API cannot download >20 MB)
"""
import datetime, hashlib, json, mimetypes, os, re, shutil, sqlite3, subprocess, sys, tempfile, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from docproc import ARCH, H, REMOTE_ROOT, TEST, today_jalali, out  # noqa: E402

REMOTE = REMOTE_ROOT + "/Media"            # gdrive1 (owner@example.com); REMOTE_ROOT already has /_test in tests
RETRY = "/tmp/hermes-media-retry"
FOLDERS = ["عکس-تصویر", "ویدیو", "صدا-ویس", "پرامپت", "طراحی-پوستر", "سایر"]
OWNER_SESS = "/root/.hermes/userbot/owner"


def db():
    os.makedirs(ARCH, mode=0o700, exist_ok=True)
    c = sqlite3.connect(f"{ARCH}/archive.db")
    c.execute("CREATE TABLE IF NOT EXISTS media (id INTEGER PRIMARY KEY, ts REAL, date TEXT, folder TEXT, kind TEXT, name TEXT,"
              " remote TEXT, link TEXT, size INTEGER, duration REAL, resolution TEXT, caption TEXT, title TEXT, text TEXT,"
              " outputs TEXT, sha256 TEXT UNIQUE)")
    c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS media_fts USING fts5(title, caption, folder, text, content='media', content_rowid='id')")
    return c


def rclone(*a, timeout=3600):
    r = subprocess.run(["rclone", *a], capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout, re.sub(r"(ya29|1//)[A-Za-z0-9._/-]+", "<redacted>", r.stderr or "")


def kind_of(path, orig=""):
    mt = mimetypes.guess_type(orig or path)[0] or ""
    ext = os.path.splitext(orig or path)[1].lower()
    if ext in (".oga", ".ogg", ".opus") or mt.startswith("audio"):
        return "audio"
    if mt.startswith("video") or ext in (".mp4", ".mov", ".mkv", ".webm"):
        return "video"
    if mt.startswith("image"):
        return "image"
    if ext in (".md", ".txt"):
        return "text"
    return "other"


AUTO_FOLDER = {"image": "عکس-تصویر", "video": "ویدیو", "audio": "صدا-ویس", "text": "پرامپت", "other": "سایر"}


def probe(path):
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
                           capture_output=True, text=True, timeout=60)
        j = json.loads(r.stdout or "{}")
        dur = float((j.get("format") or {}).get("duration") or 0) or None
        vs = [s for s in j.get("streams", []) if s.get("codec_type") == "video" and s.get("width")]
        res = f"{vs[0]['width']}x{vs[0]['height']}" if vs else None
        return dur, res
    except Exception as e:
        print(f"probe failed: {e}", file=sys.stderr)
        return None, None


def safe(s, n=50):
    s = re.sub(r"[\\/:*?\"<>|#\n\r\t]+", " ", s or "").strip()
    return re.sub(r"\s+", "-", s)[:n].strip("-")


def link_of(remote_path):
    rc, o, _ = rclone("lsjson", "--stat", remote_path, timeout=120)
    try:
        fid = json.loads(o).get("ID")
        return f"https://drive.google.com/file/d/{fid}/view" if fid else None
    except Exception:
        return None


def upload(local, remote_path):
    err = ""
    for attempt in range(3):
        rc, _, err = rclone("copyto", local, remote_path, "--retries", "2")
        if rc == 0:
            return True, ""
        time.sleep(10 * (attempt + 1))
    return False, err.strip()[-300:]


def sidecar_text(row):
    return (f"عنوان: {row['title']}\nتاریخ: {row['date']}\nپوشه: {row['folder']}\nنوع: {row['kind']}\nفایل: {row['name']}\n"
            f"حجم: {row['size']} بایت\nمدت: {row.get('duration') or '-'}\nابعاد: {row.get('resolution') or '-'}\n"
            f"توضیح/برچسب: {row.get('caption') or '-'}\n\n{row.get('text') or ''}\n")


def _queue(path, meta, err):
    os.makedirs(RETRY, mode=0o700, exist_ok=True)
    d = tempfile.mkdtemp(prefix="m", dir=RETRY)
    shutil.move(path, os.path.join(d, os.path.basename(path)))
    meta = {**meta, "_file": os.path.join(d, os.path.basename(path)), "_err": err, "_tries": meta.get("_tries", 0) + 1}
    json.dump(meta, open(os.path.join(d, "meta.json"), "w"), ensure_ascii=False)
    return d


def add(path, meta, cmd="add"):
    """Upload one file to Drive + metadata row. The local file is ALWAYS gone afterwards (uploaded+deleted or queued)."""
    queued = None
    try:
        sha = hashlib.sha256(open(path, "rb").read()).hexdigest()
        c = db()
        row = c.execute("SELECT id, link FROM media WHERE sha256=?", (sha,)).fetchone()
        if row:
            return {"ok": True, "duplicate": True, "id": row[0], "link": row[1]}
        orig = meta.get("orig_name") or os.path.basename(path)
        kind = kind_of(path, orig)
        folder = safe(meta.get("folder") or AUTO_FOLDER[kind], 30) or "سایر"
        date = today_jalali()
        cap = (meta.get("caption") or "").strip()
        text = meta.get("text") or ""
        title = meta.get("title") or (cap.splitlines()[0][:60] if cap else os.path.splitext(orig)[0][:60])
        ext = os.path.splitext(orig)[1].lower() or os.path.splitext(path)[1].lower() or ".bin"
        name = f"{date}_{safe(title) or kind}_{sha[:6]}{ext}"
        rdir = f"{REMOTE}/{folder}/{date[:4]}/{date[5:7]}"
        dur, res = probe(path) if kind in ("video", "audio", "image") else (None, None)
        r = {"title": title, "date": date, "folder": folder, "kind": kind, "name": name, "size": os.path.getsize(path),
             "duration": dur, "resolution": res, "caption": cap, "text": text}
        ok, err = upload(path, f"{rdir}/{name}")
        if not ok:
            queued = _queue(path, meta, err)
            return {"ok": False, "queued": True, "error": err}
        link = link_of(f"{rdir}/{name}")
        side = os.path.splitext(name)[0] + ".txt"
        p = subprocess.run(["rclone", "rcat", f"{rdir}/{side}"], input=sidecar_text(r), text=True, capture_output=True, timeout=120)
        if p.returncode:
            print(f"sidecar upload failed: {p.stderr[-200:]}", file=sys.stderr)
        outputs = []
        if kind == "video":                                   # thumbnail: Drive only
            th = path + ".thumb.jpg"
            try:
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "1", "-i", path, "-frames:v", "1", "-vf", "scale=480:-2", th],
                               timeout=120, check=False)
                if os.path.exists(th) and upload(th, f"{rdir}/{os.path.splitext(name)[0]}_thumb.jpg")[0]:
                    outputs.append(f"{rdir}/{os.path.splitext(name)[0]}_thumb.jpg")
            finally:
                if os.path.exists(th):
                    os.remove(th)
        cur = c.execute("INSERT INTO media (ts, date, folder, kind, name, remote, link, size, duration, resolution, caption, title, text, outputs, sha256)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (time.time(), date, folder, kind, name, f"{rdir}/{name}", link, r["size"], dur, res, cap, title, text,
                         json.dumps(outputs, ensure_ascii=False), sha))
        rid = cur.lastrowid
        c.execute("INSERT INTO media_fts(rowid, title, caption, folder, text) VALUES (?,?,?,?,?)", (rid, title, cap, folder, text))
        c.commit()
        return {"ok": True, "id": rid, "folder": folder, "kind": kind, "name": name, "link": link, "size": r["size"],
                "duration": dur, "resolution": res}
    except Exception as e:                                    # never lose the owner's file on a bug: keep it for retry
        print(f"media add failed: {type(e).__name__}: {e}", file=sys.stderr)
        if os.path.exists(path):
            queued = _queue(path, meta, f"{type(e).__name__}: {e}")
        return {"ok": False, "queued": bool(queued), "error": f"{type(e).__name__}: {e}"}
    finally:
        if not queued and os.path.exists(path):
            os.remove(path)                                   # media never stays on the server


def prompt(textfile, folder):
    t = open(textfile, encoding="utf-8").read().strip()
    os.remove(textfile)
    title = re.sub(r"^#+\s*", "", t.splitlines()[0])[:60] if t else "پرامپت"
    tags = " ".join(sorted(set(re.findall(r"#[\w؀-ۿ_]+", t))))
    md = f"# {title}\n\nتاریخ: {today_jalali()}\nبرچسب‌ها: {tags or '-'}\n\n---\n\n{t}\n"
    d = tempfile.mkdtemp(prefix="p", dir="/tmp")
    f = os.path.join(d, safe(title) + ".md")
    open(f, "w", encoding="utf-8").write(md)
    try:
        return add(f, {"folder": folder or "پرامپت", "orig_name": os.path.basename(f), "title": title, "caption": tags, "text": t})
    finally:
        shutil.rmtree(d, ignore_errors=True)


def attach(rid, f):
    c = db()
    r = c.execute("SELECT remote, outputs FROM media WHERE id=?", (rid,)).fetchone()
    if not r:
        os.remove(f)
        return {"ok": False}
    try:
        base = os.path.splitext(r[0])[0]
        dst = f"{base}_نتیجه-{int(time.time()) % 100000}{os.path.splitext(f)[1].lower()}"
        ok, err = upload(f, dst)
        if not ok:
            return {"ok": False, "error": err}
        outs = json.loads(r[1] or "[]") + [dst]
        c.execute("UPDATE media SET outputs=? WHERE id=?", (json.dumps(outs, ensure_ascii=False), rid))
        c.commit()
        return {"ok": True, "remote": dst, "link": link_of(dst)}
    finally:
        if os.path.exists(f):
            os.remove(f)


COLS = ("id", "date", "folder", "kind", "title", "link", "size")


def rows(sql, args=()):
    return [dict(zip(COLS, r)) for r in db().execute(sql, args).fetchall()]


def search(q):
    to_fa = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
    fa2en = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
    for v in dict.fromkeys((q, q.translate(fa2en), q.translate(fa2en).translate(to_fa))):
        q2 = " ".join(f'"{w}"' for w in v.split() if w)
        try:
            r = rows("SELECT m.id, m.date, m.folder, m.kind, m.title, m.link, m.size FROM media_fts f JOIN media m ON m.id=f.rowid "
                     "WHERE media_fts MATCH ? ORDER BY m.ts DESC LIMIT 20", (q2,))
        except sqlite3.OperationalError:
            r = []
        if not r:
            like = f"%{v}%"
            r = rows("SELECT id, date, folder, kind, title, link, size FROM media WHERE title LIKE ? OR caption LIKE ? OR text LIKE ? "
                     "OR folder LIKE ? OR date LIKE ? OR name LIKE ? ORDER BY ts DESC LIMIT 20", (like,) * 6)
        if r:
            return r
    return []


def fetch(rid, outdir):
    r = db().execute("SELECT remote, name, link, size FROM media WHERE id=?", (rid,)).fetchone()
    if not r:
        return {"ok": False}
    if r[3] and r[3] > 49 * 1024 * 1024:                       # bot can send up to 50 MB: give the Drive link instead
        return {"ok": True, "too_big": True, "link": r[2], "name": r[1]}
    os.makedirs(outdir, exist_ok=True)
    dst = os.path.join(outdir, r[1])
    rc, _, err = rclone("copyto", r[0], dst, timeout=1800)
    return {"ok": rc == 0, "path": dst, "link": r[2], "name": r[1], "error": err.strip()[-200:] if rc else None}


def chart(out_path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    font = f"{H}/shared-tools/docs/fonts/Vazirmatn-Regular.ttf"
    font_manager.fontManager.addfont(font)
    plt.rcParams["font.family"] = font_manager.FontProperties(fname=font).get_name()
    c = db()
    bym = c.execute("SELECT substr(date,1,7), COUNT(*) FROM media GROUP BY 1 ORDER BY 1").fetchall()[-12:]
    byf = c.execute("SELECT folder, COUNT(*), COALESCE(SUM(size),0) FROM media GROUP BY 1 ORDER BY 2 DESC").fetchall()
    fig, ax = plt.subplots(1, 2, figsize=(11, 4.5))
    ax[0].bar([m for m, _ in bym], [n for _, n in bym], color="#4C78A8")
    ax[0].set_title("مدیا در هر ماه")
    ax[1].barh([f for f, _, _ in byf][::-1], [n for _, n, _ in byf][::-1], color="#F58518")
    ax[1].set_title("در هر پوشه")
    fig.tight_layout()
    fig.savefig(out_path, dpi=110)
    return {"ok": True, "total": sum(n for _, n, _ in byf), "by_folder": [[f, n, s] for f, n, s in byf], "by_month": bym}


def retry():
    done, left = 0, []
    if not os.path.isdir(RETRY):
        return {"ok": True, "done": 0, "left": 0}
    for d in sorted(os.listdir(RETRY)):
        p = os.path.join(RETRY, d)
        try:
            meta = json.load(open(os.path.join(p, "meta.json")))
        except Exception as e:
            print(f"bad retry entry {p}: {e}", file=sys.stderr)
            continue
        f = meta.pop("_file")
        tries = meta.pop("_tries", 1)
        meta.pop("_err", None)
        meta["_tries"] = tries
        r = add(f, meta)
        if r.get("ok"):
            done += 1
            shutil.rmtree(p, ignore_errors=True)
        else:
            left.append({"name": meta.get("orig_name"), "tries": tries + 1, "error": r.get("error")})
            shutil.rmtree(p, ignore_errors=True)                # add() re-queued it in a new dir
    return {"ok": True, "done": done, "left": len(left), "failed": left}


async def _bigfetch(outdir, size, ts):
    """The Bot API cannot download >20 MB. The owner's own session sees the same file in his chat with the bot."""
    from telethon import TelegramClient
    tok = re.search(r"^TELEGRAM_BOT_TOKEN=(.*)$", open(f"{H}/.env").read(), re.M).group(1).strip().strip('"')
    bot_id = int(tok.split(":")[0])
    cr = json.load(open(OWNER_SESS + ".creds.json"))
    tmp = tempfile.mkdtemp(prefix="sess", dir="/tmp")
    shutil.copy2(OWNER_SESS + ".session", f"{tmp}/s.session")    # a copy: never lock the live session file
    c = TelegramClient(f"{tmp}/s", cr["api_id"], cr["api_hash"])
    try:
        await c.connect()
        if not await c.is_user_authorized():
            return {"ok": False, "error": "owner session not authorized"}
        best = None
        async for m in c.iter_messages(bot_id, limit=40):
            if m.out and m.file and m.file.size == size:
                d = abs(m.date.timestamp() - ts)
                if d < 600 and (best is None or d < best[0]):
                    best = (d, m)
        if not best:
            return {"ok": False, "error": "not found in the chat with the bot"}
        m = best[1]
        os.makedirs(outdir, exist_ok=True)
        name = m.file.name or f"media{m.file.ext or ''}"
        p = await m.download_media(file=os.path.join(outdir, f"{int(time.time())}_{name}"))
        return {"ok": True, "path": p, "name": name}
    finally:
        await c.disconnect()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    a = sys.argv[1:]
    cmd = a[0] if a else ""
    if cmd == "add":
        out(add(a[1], json.load(open(a[2], encoding="utf-8"))))
        os.path.exists(a[2]) and os.remove(a[2])
    elif cmd == "add-file" and len(a) >= 2:
        # one step for an agent: media.py add-file <file> [folder] [caption...]  (folder "" = auto by type)
        out(add(a[1], {"folder": a[2] if len(a) > 2 else "", "caption": " ".join(a[3:]), "orig_name": os.path.basename(a[1])}))
    elif cmd == "prompt":
        out(prompt(a[1], a[2] if len(a) > 2 else "پرامپت"))
    elif cmd == "attach":
        out(attach(int(a[1]), a[2]))
    elif cmd == "search":
        out(search(" ".join(a[1:])))
    elif cmd == "recent":
        out(rows("SELECT id, date, folder, kind, title, link, size FROM media ORDER BY ts DESC LIMIT ?", (int(a[1]) if len(a) > 1 else 15,)))
    elif cmd == "folders":
        have = dict(db().execute("SELECT folder, COUNT(*) FROM media GROUP BY 1").fetchall())
        out([[f, have.get(f, 0)] for f in FOLDERS] + [[f, n] for f, n in have.items() if f not in FOLDERS])
    elif cmd == "list":
        out(rows("SELECT id, date, folder, kind, title, link, size FROM media WHERE folder=? ORDER BY ts DESC LIMIT 20", (a[1],)))
    elif cmd == "get":
        r = db().execute("SELECT id, title, link, remote, outputs, kind FROM media WHERE id=?", (int(a[1]),)).fetchone()
        out({"ok": bool(r), "id": r[0], "title": r[1], "link": r[2], "remote": r[3], "outputs": json.loads(r[4] or "[]"), "kind": r[5]} if r else {"ok": False})
    elif cmd == "fetch":
        out(fetch(int(a[1]), a[2]))
    elif cmd == "chart":
        out(chart(a[1]))
    elif cmd == "retry":
        out(retry())
    elif cmd == "bigfetch":
        import asyncio
        out(asyncio.run(_bigfetch(a[1], int(a[2]), float(a[3]))))
    else:
        sys.exit(__doc__)
