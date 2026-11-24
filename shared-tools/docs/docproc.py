#!/root/.hermes/shared-tools/docs/venv/bin/python
"""Agent Hermes document reader + owner archive (no Hermes agent involved; prints JSON).

  docproc.py extract <file> [--no-gemini]          text from photo / PDF / DOCX (local Tesseract fa+eng, pre-processed;
                                                   Gemini vision fallback on low confidence or invalid dates)
  docproc.py analyze <textfile>                    category, title, date, key fields, suggested filename
  docproc.py task <summary|translate|tables|fields> <textfile>
  docproc.py docx <textfile> <out.docx> [title]    Word file
  docproc.py xlsx <textfile> <out.xlsx>            tables -> Excel (LLM turns the text's tables into CSV first)
  docproc.py pdf <image|pdf> <out.pdf>             searchable PDF (Tesseract text layer)
  docproc.py archive-add <file> <metajson>         OWNER archive only: /root/.hermes/archive-admin/<cat>/<YYYY>/<MM>/
  docproc.py archive-search <query> | archive-cats | archive-get <id> | archive-chart <out.png> | archive-recent [n]
"""
import base64, datetime, hashlib, json, os, re, shutil, sqlite3, subprocess, sys, tempfile, time, urllib.request

H = "/root/.hermes"
ARCH = os.environ.get("HERMES_ARCHIVE_DIR") or f"{H}/archive-admin"   # metadata only (archive.db); env = other archive / tests
# Owner decision 2026-11-13: every archived file lives ONLY on Google Drive owner@example.com (rclone remote gdrive1).
REMOTE_ROOT = os.environ.get("HERMES_ARCHIVE_REMOTE") or "gdrive1:Hermes Archive"
TEST = bool(os.environ.get("HERMES_ARCHIVE_TEST"))
if TEST:
    REMOTE_ROOT += "/_test"
DB = f"{ARCH}/archive.db"
FONT = f"{H}/shared-tools/docs/fonts/Vazirmatn-Regular.ttf"
CATS = ["هویتی", "مالی-فاکتور", "قرارداد", "بانکی", "پزشکی", "تحصیلی", "خودرو", "ملک", "نامه", "سایر"]
FA_DIG = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def out(o):
    print(json.dumps(o, ensure_ascii=False))


def env(k, path=f"{H}/.env"):
    m = re.search(rf"^{k}=(.*)$", open(path).read(), re.M)
    return m.group(1).strip().strip('"') if m else ""


# ---------------- LLM (text only) ----------------
def _post(url, body, headers, timeout=120):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", **headers})
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def llm(prompt, max_tokens=2500):
    """ERNIE (OpenRouter free) -> LongCat (Nous) -> Gemini flash. Returns text or raises."""
    errs = []
    msgs = [{"role": "user", "content": prompt}]
    try:
        r = _post("https://openrouter.ai/api/v1/chat/completions",
                  {"model": "baidu/ernie-5.5-flash-preview:free", "messages": msgs, "max_tokens": max_tokens},
                  {"Authorization": "Bearer " + env("OPENROUTER_API_KEY")})
        t = r["choices"][0]["message"].get("content") or ""
        if t.strip():
            return t
    except Exception as e:
        errs.append(f"ernie {e}")
    try:
        tok = json.load(open(f"{H}/auth.json"))["credential_pool"]["nous"][0]["access_token"]
        r = _post("https://inference-api.nousresearch.com/v1/chat/completions",
                  {"model": "meituan/longcat-2.5:free", "messages": msgs, "max_tokens": max_tokens}, {"Authorization": "Bearer " + tok})
        t = r["choices"][0]["message"].get("content") or ""
        if t.strip():
            return t
    except Exception as e:
        errs.append(f"longcat {e}")
    try:
        r = _post("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
                  {"model": "gemini-3.5-flash", "messages": msgs, "max_tokens": max_tokens}, {"Authorization": "Bearer " + env("GEMINI_API_KEY")})
        return r["choices"][0]["message"].get("content") or ""
    except Exception as e:
        errs.append(f"gemini {e}")
    raise RuntimeError("; ".join(errs)[:400])


def json_from(text):
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0)) if m else {}


# ---------------- extraction ----------------
def preprocess(src, dst):
    from PIL import Image, ImageOps, ImageFilter
    im = ImageOps.exif_transpose(Image.open(src)).convert("L")
    if im.width < 2000:
        im = im.resize((im.width * 2, im.height * 2), Image.LANCZOS)
    im = ImageOps.autocontrast(im, cutoff=1).filter(ImageFilter.SHARPEN)
    im.save(dst)
    try:                                              # deskew/rotation via Tesseract OSD
        o = subprocess.run(["tesseract", dst, "-", "--psm", "0"], capture_output=True, text=True, timeout=60).stdout
        m = re.search(r"Rotate: (\d+)", o)
        if m and int(m.group(1)) in (90, 180, 270):
            Image.open(dst).rotate(-int(m.group(1)), expand=True).save(dst)
    except Exception as e:
        print(f"osd: {e}", file=sys.stderr)
    return dst


def tesseract(img):
    tsv = subprocess.run(["tesseract", img, "-", "-l", "fas+eng", "--oem", "1", "--psm", "3", "tsv"],
                         capture_output=True, text=True, timeout=180).stdout
    words, confs, line_key, lines = [], [], None, []
    for row in tsv.splitlines()[1:]:
        p = row.split("\t")
        if len(p) < 12 or not p[11].strip():
            continue
        key = (p[2], p[3], p[4])
        if key != line_key:
            lines.append([])
            line_key = key
        lines[-1].append(p[11])
        try:
            if float(p[10]) >= 0:
                confs.append(float(p[10]))
        except ValueError:
            pass
    text = "\n".join(" ".join(l) for l in lines)
    return text, (sum(confs) / len(confs) if confs else 0.0)


def dates_valid(text):
    t = text.translate(FA_DIG)
    bad = 0
    for y, m, d in re.findall(r"\b(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})\b", t):
        y, m, d = int(y), int(m), int(d)
        if not ((1300 <= y <= 1500 or 1900 <= y <= 2100) and 1 <= m <= 12 and 1 <= d <= 31):
            bad += 1
    return bad == 0


def gemini_vision(path):
    mime = "application/pdf" if path.lower().endswith(".pdf") else "image/jpeg"
    data = base64.b64encode(open(path, "rb").read()).decode()
    body = {"contents": [{"parts": [
        {"text": "متن کامل این سند را دقیق و بدون توضیح اضافه استخراج کن. ترتیب خطوط و جدول‌ها را نگه دار. اعداد را دقیق بنویس."},
        {"inline_data": {"mime_type": mime, "data": data}}]}]}
    r = _post("https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent", body,
              {"x-goog-api-key": env("GEMINI_API_KEY")}, timeout=180)
    return "".join(p.get("text", "") for p in r["candidates"][0]["content"]["parts"])


def extract(path, allow_gemini=True):
    ext = path.lower().rsplit(".", 1)[-1]
    tmp = tempfile.mkdtemp(prefix="doc-")
    try:
        if ext in ("docx",):
            import docx
            d = docx.Document(path)
            text = "\n".join(p.text for p in d.paragraphs)
            for t in d.tables:
                for r in t.rows:
                    text += "\n" + " | ".join(c.text for c in r.cells)
            return {"text": text, "conf": 100, "source": "docx", "pages": 1}
        if ext == "pdf":
            import fitz
            doc = fitz.open(path)
            text = "\n".join(p.get_text() for p in doc)
            if len(text.strip()) > 50:
                return {"text": text, "conf": 100, "source": "pdf-text", "pages": doc.page_count}
            parts, confs = [], []
            for i, page in enumerate(doc):
                img = f"{tmp}/p{i}.png"
                page.get_pixmap(dpi=300).save(img)
                t, c = tesseract(preprocess(img, f"{tmp}/p{i}-pre.png"))
                parts.append(t)
                confs.append(c)
            text, conf, pages = "\n\n".join(parts), (sum(confs) / len(confs) if confs else 0), doc.page_count
        else:
            text, conf = tesseract(preprocess(path, f"{tmp}/pre.png"))
            pages = 1
        res = {"text": text, "conf": round(conf, 1), "source": "tesseract", "pages": pages, "dates_ok": dates_valid(text)}
        if allow_gemini and (conf < 65 or not res["dates_ok"] or len(text.strip()) < 20):
            try:
                g = gemini_vision(path)
                if g.strip():
                    res.update({"text": g, "source": "gemini", "fallback_reason": f"conf={round(conf)} dates_ok={res['dates_ok']}"})
            except Exception as e:
                res["gemini_error"] = str(e)[:200]
        return res
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------- analysis / tasks ----------------
def today_jalali():
    g = datetime.date.today()
    gy, gm, gd = g.year, g.month, g.day
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = 355666 + 365 * gy + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400 + gd + g_d_m[gm - 1]
    jy = -1595 + 33 * (days // 12053); days %= 12053
    jy += 4 * (days // 1461); days %= 1461
    if days > 365:
        jy += (days - 1) // 365; days = (days - 1) % 365
    jm = 1 + days // 31 if days < 186 else 7 + (days - 186) // 30
    jd = 1 + (days % 31 if days < 186 else (days - 186) % 30)
    return f"{jy:04d}-{jm:02d}-{jd:02d}"


def analyze(text):
    p = ("این متنِ یک سند است (از OCR). فقط یک JSON بده با کلیدهای: "
         f'"category" (دقیقاً یکی از: {"، ".join(CATS)})، "title" (عنوان کوتاه فارسی، حداکثر ۶ کلمه)، '
         '"date" (تاریخ سند به شمسی YYYY-MM-DD اگر پیدا شد وگرنه خالی)، "party" (نام فروشنده/طرف/سازمان اگر هست)، '
         '"fields" (شیء کلید-مقدار از مهم‌ترین داده‌ها مثل مبلغ، شماره، نام، تاریخ)، "tags" (۳ تا ۵ کلمه‌ی کلیدی فارسی). '
         "هیچ متن دیگری ننویس.\n\n" + text[:6000])
    try:
        a = json_from(llm(p, 1200))
    except Exception as e:
        a = {"error": str(e)[:200]}
    cat = a.get("category") if a.get("category") in CATS else "سایر"
    date = (a.get("date") or "").translate(FA_DIG).replace("/", "-") or today_jalali()
    if not re.fullmatch(r"1[34]\d\d-\d\d-\d\d", date):
        date = today_jalali()
    title = re.sub(r"[\\/:*?\"<>|\n]", " ", (a.get("title") or cat))[:40].strip()
    party = re.sub(r"[\\/:*?\"<>|\n]", " ", (a.get("party") or ""))[:30].strip()
    fname = "_".join(x for x in (date, cat, party or title) if x).replace(" ", "-")
    return {"category": cat, "title": title, "date": date, "party": party, "fields": a.get("fields") or {},
            "tags": a.get("tags") or [], "filename": fname, **({"error": a["error"]} if "error" in a else {})}


def task(kind, text):
    p = {"summary": "این سند را به فارسی در حداکثر ۸ خط خلاصه کن: موضوع، طرفین، مبالغ و تاریخ‌های مهم، تعهدات و کارهایی که باید انجام شود.",
         "translate": "اگر این متن فارسی است آن را به انگلیسی، و اگر غیرفارسی است به فارسی، کامل و دقیق ترجمه کن. فقط ترجمه را بده.",
         "fields": "همه‌ی داده‌های ساختاری این فرم/رسید/فاکتور را به‌صورت فهرست «نام فیلد: مقدار» فارسی بده (مبلغ‌ها، تاریخ‌ها، نام‌ها، شماره‌ها، اقلام). فقط فهرست.",
         "tables": "همه‌ی جدول‌های این متن را به CSV تبدیل کن (جداکننده کاما، ردیف اول عنوان ستون‌ها). اگر چند جدول هست، بینشان یک خط خالی بگذار. فقط CSV."}[kind]
    return llm(p + "\n\n" + text[:12000], 3500)


def make_docx(text, out_path, title=""):
    import docx
    from docx.shared import Pt
    d = docx.Document()
    st = d.styles["Normal"]
    st.font.name = "Vazirmatn"
    st.font.size = Pt(12)
    if title:
        h = d.add_heading(title, level=1)
        h.alignment = 2
    for line in text.splitlines():
        para = d.add_paragraph(line)
        para.alignment = 2
        pPr = para._p.get_or_add_pPr()
        from docx.oxml import OxmlElement
        bidi = OxmlElement("w:bidi")
        pPr.append(bidi)
    d.save(out_path)


def make_xlsx(csv_text, out_path):
    import csv, io, openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.sheet_view.rightToLeft = True
    block = 1
    for chunk in re.split(r"\n\s*\n", csv_text.strip().strip("`").replace("csv\n", "", 1)):
        if block > 1:
            ws = wb.create_sheet(f"جدول {block}")
            ws.sheet_view.rightToLeft = True
        for row in csv.reader(io.StringIO(chunk)):
            ws.append([c.strip() for c in row])
        block += 1
    wb.save(out_path)


def make_pdf(src, out_path):
    tmp = tempfile.mkdtemp(prefix="pdf-")
    try:
        if src.lower().endswith(".pdf"):
            import fitz
            doc = fitz.open(src)
            pages = []
            for i, page in enumerate(doc):
                img = f"{tmp}/p{i}.png"
                page.get_pixmap(dpi=300).save(img)
                pages.append(img)
            lst = f"{tmp}/list.txt"
            open(lst, "w").write("\n".join(pages))
            subprocess.run(["tesseract", lst, f"{tmp}/out", "-l", "fas+eng", "pdf"], capture_output=True, timeout=600)
        else:
            pre = preprocess(src, f"{tmp}/pre.png")
            subprocess.run(["tesseract", pre, f"{tmp}/out", "-l", "fas+eng", "pdf"], capture_output=True, timeout=300)
        shutil.move(f"{tmp}/out.pdf", out_path)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------- owner archive ----------------
def db():
    os.makedirs(ARCH, mode=0o700, exist_ok=True)
    os.chmod(ARCH, 0o700)                         # owner's private metadata: root-only
    c = sqlite3.connect(DB)
    c.execute("CREATE TABLE IF NOT EXISTS docs (id INTEGER PRIMARY KEY, ts REAL, category TEXT, title TEXT, date TEXT, party TEXT,"
              " tags TEXT, orig_name TEXT, path TEXT, outputs TEXT, sha256 TEXT UNIQUE, text TEXT)")
    cols = [r[1] for r in c.execute("PRAGMA table_info(docs)")]
    for col, typ in (("link", "TEXT"), ("size", "INTEGER")):
        if col not in cols:
            c.execute(f"ALTER TABLE docs ADD COLUMN {col} {typ}")
    c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(title, tags, party, text, content='docs', content_rowid='id')")
    return c


def _rclone(*a, inp=None, timeout=1800):
    r = subprocess.run(["rclone", *a], input=inp, capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout, re.sub(r"(ya29|1//)[A-Za-z0-9._/-]+", "<redacted>", r.stderr or "")


def _upload(local, remote):
    err = ""
    for attempt in range(3):
        rc, _, err = _rclone("copyto", local, remote, "--retries", "2")
        if rc == 0:
            return True, ""
        time.sleep(5 * (attempt + 1))
    return False, err.strip()[-300:]


def _link(remote):
    rc, o, _ = _rclone("lsjson", "--stat", remote, timeout=120)
    try:
        fid = json.loads(o).get("ID")
        return f"https://drive.google.com/file/d/{fid}/view" if fid else None
    except Exception:
        return None


def _sidecar(rid, meta, remote_file):
    body = (f"عنوان: {meta.get('title', '')}\nتاریخ: {meta.get('date', '')}\nدسته: {meta.get('category', '')}\nطرف: {meta.get('party', '')}\n"
            f"برچسب‌ها: {' '.join(meta.get('tags') or [])}\nفایل: {os.path.basename(remote_file)}\nشناسه: {rid}\n\n--- متن سند ---\n{meta.get('text', '')}\n")
    rc, _, err = _rclone("rcat", os.path.splitext(remote_file)[0] + ".txt", inp=body, timeout=300)
    if rc:
        print(f"sidecar upload failed: {err[-200:]}", file=sys.stderr)


def _drive_kick():
    """Refresh the Drive INDEX and retry pending uploads in the background (never in tests)."""
    if TEST:
        return
    try:
        logf = open(f"{H}/ads/stats/drive_mirror.log", "a")
        subprocess.Popen([f"{H}/shared-tools/docs/venv/bin/python", f"{H}/shared-tools/docs/drive_mirror.py", "sync"],
                         stdout=logf, stderr=logf, stdin=subprocess.DEVNULL, start_new_session=True, env=os.environ.copy())
    except Exception as e:                       # never break archiving because of the index; but say so
        print(f"drive mirror kick failed: {e}", file=sys.stderr)


def archive_add(path, meta):
    """Upload the document (and its outputs) to Drive; the server keeps only the metadata row.
    If Drive is unreachable the file waits in <ARCH>/.pending and drive_mirror.py uploads it later."""
    data = open(path, "rb").read()
    sha = hashlib.sha256(data).hexdigest()
    c = db()
    row = c.execute("SELECT id, path, link FROM docs WHERE sha256=?", (sha,)).fetchone()
    if row:
        return {"ok": True, "duplicate": True, "id": row[0], "path": row[1], "link": row[2]}
    cat = meta.get("category") if meta.get("category") else "سایر"
    d = meta.get("date") or today_jalali()
    rdir = f"{REMOTE_ROOT}/{cat}/{d[:4]}/{d[5:7]}"
    ext = os.path.splitext(meta.get("orig_name") or path)[1] or os.path.splitext(path)[1]
    remote = f"{rdir}/{meta.get('filename') or 'doc'}_{sha[:6]}{ext}"
    ok, err = _upload(path, remote)
    link, pending = None, None
    if ok:
        link = _link(remote)
    else:
        os.makedirs(f"{ARCH}/.pending", mode=0o700, exist_ok=True)
        pending = f"{ARCH}/.pending/{sha[:16]}{ext}"
        shutil.copy2(path, pending)
        print(f"drive upload failed, queued: {err}", file=sys.stderr)
    outs = []
    for o in meta.get("outputs") or []:
        if os.path.exists(o) and _upload(o, f"{rdir}/{os.path.basename(o)}")[0]:
            outs.append(f"{rdir}/{os.path.basename(o)}")
    cur = c.execute("INSERT INTO docs (ts, category, title, date, party, tags, orig_name, path, outputs, sha256, text, link, size) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (time.time(), cat, meta.get("title", ""), meta.get("date", ""), meta.get("party", ""),
                     " ".join(meta.get("tags") or []), meta.get("orig_name", ""), remote, json.dumps(outs, ensure_ascii=False), sha,
                     meta.get("text", ""), link, len(data)))
    rid = cur.lastrowid
    c.execute("INSERT INTO docs_fts(rowid, title, tags, party, text) VALUES (?,?,?,?,?)",
              (rid, meta.get("title", ""), " ".join(meta.get("tags") or []), meta.get("party", ""), meta.get("text", "")))
    c.commit()
    if pending:
        json.dump({"id": rid, "file": pending, "remote": remote, "meta": {**meta, "category": cat}},
                  open(pending + ".json", "w", encoding="utf-8"), ensure_ascii=False)
    else:
        _sidecar(rid, {**meta, "category": cat}, remote)
    _drive_kick()
    return {"ok": True, "id": rid, "path": remote, "link": link, "category": cat, "queued": bool(pending)}


def archive_attach(rid, f):
    c = db()
    r = c.execute("SELECT path, outputs FROM docs WHERE id=?", (rid,)).fetchone()
    if not r:
        return {"ok": False}
    dst = f"{r[0].rsplit('/', 1)[0]}/{os.path.basename(f)}"
    ok, err = _upload(f, dst)
    if not ok:
        return {"ok": False, "error": err}
    outs = json.loads(r[1] or "[]")
    if dst not in outs:
        outs.append(dst)
    c.execute("UPDATE docs SET outputs=? WHERE id=?", (json.dumps(outs, ensure_ascii=False), rid))
    c.commit()
    return {"ok": True, "path": dst}


def archive_move(rid, cat):
    cat = re.sub(r"[\\/:*?\"<>|\n]", " ", cat).strip()[:30] or "سایر"
    c = db()
    r = c.execute("SELECT path, outputs, date FROM docs WHERE id=?", (rid,)).fetchone()
    if not r:
        return {"ok": False}
    d = (r[2] or today_jalali())
    ndir = f"{REMOTE_ROOT}/{cat}/{d[:4]}/{d[5:7]}"
    newp = f"{ndir}/{r[0].rsplit('/', 1)[1]}"
    if newp == r[0]:
        return {"ok": True, "category": cat, "path": newp}
    rc, _, err = _rclone("moveto", r[0], newp)
    if rc:
        return {"ok": False, "error": err.strip()[-200:]}
    _rclone("moveto", os.path.splitext(r[0])[0] + ".txt", os.path.splitext(newp)[0] + ".txt")
    outs = []
    for o in json.loads(r[1] or "[]"):
        no = f"{ndir}/{o.rsplit('/', 1)[1]}"
        outs.append(no if _rclone("moveto", o, no)[0] == 0 else o)
    c.execute("UPDATE docs SET category=?, path=?, outputs=?, link=? WHERE id=?", (cat, newp, json.dumps(outs, ensure_ascii=False), _link(newp), rid))
    c.commit()
    _drive_kick()
    return {"ok": True, "category": cat, "path": newp}


def archive_fetch(rid, outdir):
    """Download a document (+ its outputs) from Drive into outdir for ⬇️; the caller deletes them after sending."""
    r = db().execute("SELECT path, outputs, title, link FROM docs WHERE id=?", (rid,)).fetchone()
    if not r:
        return {"ok": False}
    os.makedirs(outdir, exist_ok=True)
    files = []
    for rp in [r[0]] + json.loads(r[1] or "[]"):
        if rp.startswith(ARCH):                         # still pending upload
            if os.path.exists(rp):
                files.append(rp)
            continue
        dst = os.path.join(outdir, rp.rsplit("/", 1)[1])
        if _rclone("copyto", rp, dst)[0] == 0:
            files.append(dst)
    return {"ok": bool(files), "files": files, "title": r[2], "link": r[3]}


def archive_search(q):
    # documents keep the digits as written (Persian or Latin); try the query in both forms
    to_fa = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
    for v in dict.fromkeys((q, q.translate(FA_DIG), q.translate(FA_DIG).translate(to_fa))):
        rows = _archive_search(v)
        if rows:
            return rows
    return []


def _archive_search(q):
    c = db()
    q2 = " ".join(f'"{w}"' for w in q.split() if w)
    try:
        rows = c.execute("SELECT d.id, d.category, d.title, d.date, d.party FROM docs_fts f JOIN docs d ON d.id=f.rowid "
                         "WHERE docs_fts MATCH ? ORDER BY d.ts DESC LIMIT 20", (q2,)).fetchall()
    except sqlite3.OperationalError:
        rows = []
    if not rows:
        like = f"%{q}%"
        rows = c.execute("SELECT id, category, title, date, party FROM docs WHERE title LIKE ? OR text LIKE ? OR tags LIKE ? OR category LIKE ? OR date LIKE ? "
                         "ORDER BY ts DESC LIMIT 20", (like, like, like, like, like)).fetchall()
    return [dict(zip(("id", "category", "title", "date", "party"), r)) for r in rows]


def archive_chart(out_path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    import arabic_reshaper
    from bidi.algorithm import get_display
    font_manager.fontManager.addfont(FONT)
    plt.rcParams["font.family"] = font_manager.FontProperties(fname=FONT).get_name()
    import matplotlib as _m
    _ver = tuple(int(x) for x in _m.__version__.split(".")[:2])
    # matplotlib >= 3.10 shapes RTL text itself (libraqm); older versions need reshape + bidi
    fa = (lambda s: s) if _ver >= (3, 10) else (lambda s: get_display(arabic_reshaper.reshape(s)))
    c = db()
    bym = c.execute("SELECT substr(date,1,7), COUNT(*) FROM docs GROUP BY 1 ORDER BY 1").fetchall()[-12:]
    byc = c.execute("SELECT category, COUNT(*) FROM docs GROUP BY 1 ORDER BY 2 DESC").fetchall()
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    axes[0].bar([m.translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")) for m, _ in bym] or ["-"], [n for _, n in bym] or [0], color="#2a9d8f")
    axes[0].set_title(fa("تعداد سندها در هر ماه"))
    axes[0].tick_params(axis="x", rotation=45)
    if byc:
        axes[1].barh([fa(cname) for cname, _ in byc], [n for _, n in byc], color="#e9c46a")
    axes[1].set_title(fa("سندها بر اساس دسته"))
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    total = c.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
    return {"ok": True, "total": total, "by_category": byc, "by_month": bym}


def main():
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    cmd = a[0]
    if cmd == "extract":
        out(extract(a[1], "--no-gemini" not in a))
    elif cmd == "analyze":
        out(analyze(open(a[1], encoding="utf-8").read()))
    elif cmd == "task":
        try:
            out({"ok": True, "result": task(a[1], open(a[2], encoding="utf-8").read())})
        except Exception as e:
            out({"ok": False, "error": str(e)[:300]})
    elif cmd == "docx":
        make_docx(open(a[1], encoding="utf-8").read(), a[2], a[3] if len(a) > 3 else "")
        out({"ok": True, "path": a[2]})
    elif cmd == "xlsx":
        try:
            make_xlsx(task("tables", open(a[1], encoding="utf-8").read()), a[2])
            out({"ok": True, "path": a[2]})
        except Exception as e:
            out({"ok": False, "error": str(e)[:300]})
    elif cmd == "pdf":
        make_pdf(a[1], a[2])
        out({"ok": os.path.exists(a[2]), "path": a[2]})
    elif cmd == "archive-add":
        out(archive_add(a[1], json.load(open(a[2], encoding="utf-8"))))
    elif cmd == "archive-search":
        out(archive_search(" ".join(a[1:])))
    elif cmd == "archive-cats":
        out(db().execute("SELECT category, COUNT(*) FROM docs GROUP BY 1 ORDER BY 2 DESC").fetchall())
    elif cmd == "archive-recent":
        rows = db().execute("SELECT id, category, title, date, party FROM docs ORDER BY ts DESC LIMIT ?", (int(a[1]) if len(a) > 1 else 15,)).fetchall()
        out([dict(zip(("id", "category", "title", "date", "party"), r)) for r in rows])
    elif cmd == "archive-file" and len(a) >= 2:
        # one step for an agent: read + classify + upload to Drive, then DELETE the local file (nothing stays on the server)
        src = a[1]
        ex = extract(src)
        if not (ex.get("text") or "").strip():
            out({"ok": False, "error": "no_text"})
            return
        an = analyze(ex["text"])
        r = archive_add(src, {**an, "orig_name": os.path.basename(src), "text": ex["text"],
                              "tags": (an.get("tags") or []) + (a[2:] if len(a) > 2 else [])})
        if r.get("ok") and not r.get("queued"):
            os.remove(src)
        out({**r, "title": an.get("title"), "date": an.get("date"), "fields": an.get("fields")})
    elif cmd == "archive-fetch":
        out(archive_fetch(int(a[1]), a[2]))
    elif cmd == "archive-get":
        r = db().execute("SELECT id, path, outputs, title, link FROM docs WHERE id=?", (int(a[1]),)).fetchone()
        out({"ok": bool(r), "id": r[0], "path": r[1], "outputs": json.loads(r[2] or "[]"), "title": r[3], "link": r[4]} if r else {"ok": False})
    elif cmd == "archive-attach":
        out(archive_attach(int(a[1]), a[2]))
    elif cmd == "archive-move":
        out(archive_move(int(a[1]), " ".join(a[2:])))
    elif cmd == "archive-list-cat":
        rows = db().execute("SELECT id, category, title, date, party FROM docs WHERE category=? ORDER BY ts DESC LIMIT 20", (a[1],)).fetchall()
        out([dict(zip(("id", "category", "title", "date", "party"), r)) for r in rows])
    elif cmd == "archive-chart":
        out(archive_chart(a[1]))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
