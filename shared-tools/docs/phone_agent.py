#!/data/data/com.termux/files/usr/bin/python
"""Runs ON Owner's phone (Termux). Gives his Hermes agent access to ALL phone storage without uploading it all:
  index  — walk ~/storage/shared, list every file and OCR the text inside new/changed photos (fa+en), PDFs and
           text files ON THE PHONE; send only that small text index to the server.
  serve  — fetch the agent's file requests from the server and upload just those files.
Server side: /root/.hermes/shared-tools/docs/phone_index.py (owner request 2026-11-19).
"""
import fcntl, json, os, re, shutil, subprocess, sys, time, uuid

HOME = os.environ.get("HOME", "/data/data/com.termux/files/home")
ROOT = HOME + "/storage/shared"
ST = HOME + "/.phonesync"
SRV = "owner-phone@203.0.113.10:"
SSH = "ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=25 -o ServerAliveInterval=20"
SKIP = {"Android", ".thumbnails", ".Trash", ".trash", ".cache", "cache", ".Statuses"}
IMG = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
PDF = (".pdf",)
TXT = (".txt", ".md", ".csv", ".json")
OCR_PER_RUN = 1000
FIRST = ["DCIM", "Pictures", "Download", "Documents"]   # camera photos first


def rs(*args, timeout=3600):
    return subprocess.run(["rsync", "-a", "-e", SSH, *args], capture_output=True, text=True, timeout=timeout)


def lock(name):
    os.makedirs(ST, exist_ok=True)
    f = open(f"{ST}/{name}.lock", "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit(0)              # previous run still busy
    return f


def text_of(p, ext):
    """Returns (text, error). A tool that fails or prints an error counts as an error, so the file is retried."""
    env = dict(os.environ, TESSDATA_PREFIX=ST + "/tools/tessdata")
    if ext in IMG:
        r = subprocess.run(["tesseract", p, "stdout", "-l", "fas+eng"], capture_output=True, text=True, timeout=180, env=env)
    elif ext in PDF:
        r = subprocess.run(["pdftotext", "-l", "30", p, "-"], capture_output=True, text=True, timeout=180)
        if r.returncode == 0 and len((r.stdout or "").strip()) < 20 and shutil.which("pdftoppm"):
            # scanned PDF (only images inside): OCR its first 3 pages
            tmp = ST + "/pdfocr"
            shutil.rmtree(tmp, ignore_errors=True)
            os.makedirs(tmp)
            subprocess.run(["pdftoppm", "-r", "150", "-l", "3", "-png", p, tmp + "/pg"], capture_output=True, timeout=300)
            txt = []
            for f in sorted(os.listdir(tmp)):
                o = subprocess.run(["tesseract", f"{tmp}/{f}", "stdout", "-l", "fas+eng"], capture_output=True, text=True, timeout=180, env=env)
                txt.append(o.stdout)
            shutil.rmtree(tmp, ignore_errors=True)
            return "\n".join(txt), None
    elif ext in TXT:
        return open(p, errors="ignore").read(100_000), None
    else:
        return None, None
    bad = r.returncode != 0 or re.search(r"(?i)error|cannot|failed|not found", r.stderr or "")
    return r.stdout, (f"rc={r.returncode} {(r.stderr or '').strip()[:160]}" if bad else None)


def selftest():
    """python ~/phone_agent.py selftest — OCR one photo and one PDF and show what happens."""
    import glob as g
    for pat, ext in (("DCIM/**/*.jpg", ".jpg"), ("**/*.png", ".png"), ("**/*.pdf", ".pdf")):
        fs = g.glob(os.path.join(ROOT, pat), recursive=True)[:1]
        if fs:
            t, e = text_of(fs[0], ext)
            print(ext, os.path.relpath(fs[0], ROOT), "| chars:", len(t or ""), "| error:", e)
    print("tesseract:", shutil.which("tesseract"), "| pdftotext:", shutil.which("pdftotext"),
          "| tessdata:", os.listdir(ST + "/tools/tessdata") if os.path.isdir(ST + "/tools/tessdata") else "MISSING")


def index():
    lk = lock("index")
    mf_p = ST + "/manifest3.json"       # v2: files whose text could not be read are NOT remembered (retried next run)
    can = {"img": bool(shutil.which("tesseract")), "pdf": bool(shutil.which("pdftotext"))}
    mf = json.load(open(mf_p)) if os.path.exists(mf_p) else {}
    out, seen, ocr, pending = [], set(), 0, 0
    def walk():
        tops = sorted(os.listdir(ROOT), key=lambda d: (FIRST.index(d) if d in FIRST else 99, d))
        for t in tops:
            tp = os.path.join(ROOT, t)
            if os.path.isfile(tp):
                yield ROOT, [], [t]
            elif t not in SKIP and not t.startswith("."):
                yield from os.walk(tp)
    for base, dirs, files in walk():
        dirs[:] = sorted(d for d in dirs if d not in SKIP and not d.startswith("."))
        for n in files:
            if n.startswith("."):
                continue
            p = os.path.join(base, n)
            rel = os.path.relpath(p, ROOT)
            seen.add(rel)
            try:
                st = os.stat(p)
            except OSError:
                continue
            sig = [int(st.st_mtime), st.st_size]
            if mf.get(rel) == sig:
                continue
            ext = os.path.splitext(n)[1].lower()
            needs_text = ext in IMG + PDF + TXT
            if (ext in IMG and not can["img"]) or (ext in PDF and not can["pdf"]):
                out.append({"p": rel, "m": sig[0], "s": sig[1], "t": None, "e": "pending"})
                pending += 1
                continue
            if needs_text and ocr >= OCR_PER_RUN:
                out.append({"p": rel, "m": sig[0], "s": sig[1], "t": None, "e": "pending"})   # listed by name now, text later
                pending += 1
                continue
            t, err = None, None
            if needs_text:
                try:
                    t, err = text_of(p, ext)
                except Exception as e:
                    err = f"{type(e).__name__}: {e}"[:160]
                ocr += 1
            out.append({"p": rel, "m": sig[0], "s": sig[1], "t": t, "e": err})
            if not err:
                mf[rel] = sig
    gone = [r for r in mf if r not in seen]
    for r in gone:
        out.append({"p": r, "del": 1})
        mf.pop(r)
    out.append({"meta": 1, "pending": pending, "at": int(time.time())})      # always: lets the server show progress
    if out:
        os.makedirs(ST + "/out", exist_ok=True)
        fn = f"{ST}/out/index-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}.jsonl"
        with open(fn, "w") as f:
            for o in out:
                f.write(json.dumps(o, ensure_ascii=False) + "\n")
    r = rs("--remove-source-files", ST + "/out/", SRV + "_in/") if os.path.isdir(ST + "/out") else None
    if r is None or r.returncode == 0:
        json.dump(mf, open(mf_p, "w"))     # only remember files once their index reached the server
    print(json.dumps({"tools": can, "pending": pending, "sent": len(out), "ocr": ocr, "removed": len(gone), "rsync": None if r is None else r.returncode,
                      "err": (r.stderr[-300:] if r is not None and r.returncode else "")}))


def sheet(rq, rid):
    """Contact sheet(s): thumbnails of every photo in a folder/date range, labelled with file name + date, 40 per sheet."""
    import datetime as dt
    folder = os.path.join(ROOT, rq.get("folder") or "DCIM")
    f0 = dt.datetime.fromisoformat(rq.get("from") or "2000-01-01").timestamp()
    f1 = dt.datetime.fromisoformat(rq.get("to") or "2100-01-01").timestamp() + 86400
    pics = []
    for b, ds, fs in os.walk(folder):
        ds[:] = [d for d in ds if not d.startswith(".")]
        for f in fs:
            p = os.path.join(b, f)
            if f.lower().endswith(IMG) and f0 <= os.path.getmtime(p) <= f1:
                pics.append(p)
    pics.sort(key=os.path.getmtime)
    tmp = f"{ST}/sheet-{rid}"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    idx = []
    for i in range(0, len(pics), 40):
        part = pics[i:i + 40]
        args = []
        for k, p in enumerate(part, i + 1):
            lab = f"{k}) {time.strftime('%Y-%m-%d', time.localtime(os.path.getmtime(p)))}"
            args += ["-label", lab, p + "[0]"]
            idx.append({"n": k, "path": os.path.relpath(p, ROOT), "date": time.strftime('%Y-%m-%d %H:%M', time.localtime(os.path.getmtime(p)))})
        subprocess.run(["magick", "montage", *args, "-geometry", "260x260+6+6", "-tile", "5x", "-pointsize", "18",
                        "-quality", "70", f"{tmp}/sheet-{i // 40 + 1:02d}.jpg"], capture_output=True, timeout=900)
    json.dump({"count": len(pics), "items": idx}, open(f"{tmp}/index.json", "w"), ensure_ascii=False)
    rs(tmp + "/", f"{SRV}_files/{rid}/", timeout=3600)
    shutil.rmtree(tmp, ignore_errors=True)


def selfupdate():
    """Pull the newest phone_agent.py + tessdata from the server so fixes reach the phone without the owner typing anything."""
    r = rs(SRV + "_tools/", ST + "/tools/", timeout=600)
    new = ST + "/tools/phone_agent.py"
    me = os.path.abspath(__file__)
    if r.returncode == 0 and os.path.exists(new) and open(new, "rb").read() != open(me, "rb").read():
        shutil.copy(new, me)
        print("updated phone_agent.py")


def serve():
    lk = lock("serve")
    try:
        selfupdate()
    except Exception as e:
        print("selfupdate failed:", e)
    req = ST + "/req"
    os.makedirs(req, exist_ok=True)
    r = rs(SRV + "_req/", req + "/", timeout=300)
    if r.returncode:
        return print("pull requests failed:", r.stderr[-300:])
    done_p = ST + "/served.json"
    done = set(json.load(open(done_p))) if os.path.exists(done_p) else set()
    for n in sorted(os.listdir(req)):
        rid = n.rsplit(".", 1)[0]
        if rid in done:
            continue
        try:
            rq = json.load(open(f"{req}/{n}"))
            if rq.get("type") == "sheet":
                sheet(rq, rid)
                done.add(rid)
                os.remove(f"{req}/{n}")
                continue
            rel = rq["path"]
            src = os.path.realpath(os.path.join(ROOT, rel))
            if not src.startswith(os.path.realpath(ROOT) + "/") or not os.path.isfile(src):
                raise FileNotFoundError(rel)
            u = rs(src, f"{SRV}_files/{rid}/", timeout=1800)
            print(rid, "uploaded" if u.returncode == 0 else "failed " + u.stderr[-200:])
            if u.returncode == 0:
                done.add(rid)
        except Exception as e:
            open(f"{ST}/missing-{rid}.txt", "w").write(str(e))
            rs(f"{ST}/missing-{rid}.txt", f"{SRV}_files/{rid}/", timeout=300)
            os.remove(f"{ST}/missing-{rid}.txt")
            done.add(rid)
        os.remove(f"{req}/{n}")
    json.dump(sorted(done)[-500:], open(done_p, "w"))


if __name__ == "__main__":
    {"index": index, "serve": serve, "selftest": selftest}.get((sys.argv[1:] or [""])[0], lambda: sys.exit(__doc__))()
