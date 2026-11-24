#!/root/.hermes/shared-tools/docs/venv/bin/python
"""Owner archive dashboards as a high-quality radial gauge image (owner's design sample, 2026-11-13).

  dashboard.py docs <out.png>    # documents archive + server disk (+ Drive line)
  dashboard.py media <out.png>   # media archive + Google Drive storage
Rendered as HTML (Vazirmatn) and screenshotted by headless Chromium at 1920x1200. Prints one JSON line.
"""
import datetime, html, json, math, os, re, shutil, sqlite3, subprocess, sys, tempfile, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from docproc import ARCH, H, REMOTE_ROOT  # noqa: E402

FONTS = f"{H}/shared-tools/docs/fonts"
CHROME = "/root/.cache/ms-playwright/chromium_headless_shell-1234/chrome-headless-shell-linux64/chrome-headless-shell"
FA = str.maketrans("0123456789.", "۰۱۲۳۴۵۶۷۸۹٫")


def fa(x):
    return str(x).translate(FA)


def gb(b, d=1):
    v = b / 1024 ** 3
    if b < 1024 ** 2:
        return fa(f"{max(1, round(b / 1024)) if b else 0}") + " کیلوبایت"
    if v < 1:
        return fa(f"{b / 1024 ** 2:.0f}") + " مگابایت"
    t = f"{v:.{d}f}"
    if "." in t:
        t = t.rstrip("0").rstrip(".")
    return fa(t) + " گیگابایت"


def jnow():
    t = time.gmtime(time.time() + 12600)
    gy, gm, gd = t.tm_year, t.tm_mon, t.tm_mday
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = 355666 + 365 * gy + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400 + gd + g_d_m[gm - 1]
    jy = -1595 + 33 * (days // 12053); days %= 12053
    jy += 4 * (days // 1461); days %= 1461
    if days > 365:
        jy += (days - 1) // 365; days = (days - 1) % 365
    jm = 1 + days // 31 if days < 186 else 7 + (days - 186) // 30
    jd = 1 + (days % 31 if days < 186 else (days - 186) % 30)
    return f"{jy}/{jm:02d}/{jd:02d} · {t.tm_hour:02d}:{t.tm_min:02d}", f"{jy}-{jm:02d}"


def drive_about():
    """Drive quota; rclone about is sometimes slow, so a 10-minute cache (and the last good value as fallback)."""
    cache = f"{ARCH}/.drive_about.json"
    try:
        c = json.load(open(cache))
        if time.time() - c["_ts"] < 600:
            return c
    except Exception:
        c = None
    try:
        r = subprocess.run(["rclone", "about", REMOTE_ROOT.split(":")[0] + ":", "--json"], capture_output=True, text=True, timeout=90)
        if r.returncode == 0:
            d = json.loads(r.stdout)
            d["_ts"] = time.time()
            json.dump(d, open(cache, "w"))
            os.chmod(cache, 0o600)
            return d
        print(f"drive about rc={r.returncode}: {r.stderr[-200:]}", file=sys.stderr)
    except Exception as e:
        print(f"drive about failed: {e}", file=sys.stderr)
    return c


def status_of(pct):
    if pct < 70:
        return "وضعیت عالی", "#3df58f"
    if pct < 80:
        return "وضعیت خوب", "#8ef53d"
    if pct < 90:
        return "هشدار: فضا رو به پر شدن است", "#ffe14a"
    return "بحرانی: فضا تقریباً پر است", "#ff4d5e"


def render(spec, out):
    N, R0, R1, CX, CY = 52, 300, 360, 400, 400
    segs, plan = [], []                              # plan[i] = (color1, color2, t) for each filled segment
    for frac, c1, c2 in spec["segments"]:
        k = int(round(frac * N))
        if frac > 0 and k == 0:
            k = 1                                       # anything non-zero is visible as one segment
        plan += [(c1, c2, (j / max(1, k - 1)) if k > 1 else 0) for j in range(k)]
    plan = plan[:N]
    gap = 360 / N * 0.28
    for i in range(N):
        a0 = -90 + i * 360 / N + gap / 2
        a1 = -90 + (i + 1) * 360 / N - gap / 2
        if i < len(plan):
            c1, c2, t = plan[i]
            col, glow = f"color-mix(in oklab, {c1} {100 - int(t * 100)}%, {c2})", True
        else:
            col, glow = "#123a2c", False
        p = []
        for r, a in ((R1, a0), (R1, a1), (R0, a1), (R0, a0)):
            p.append(f"{CX + r * math.cos(math.radians(a)):.1f},{CY + r * math.sin(math.radians(a)):.1f}")
        segs.append(f'<polygon points="{" ".join(p)}" style="fill:{col}" class="{"g" if glow else ""}"/>')
    marks = []
    for frac, color, label in spec.get("marks", []):
        a = math.radians(-90 + frac * 360)
        x0, y0 = CX + (R0 - 25) * math.cos(a), CY + (R0 - 25) * math.sin(a)
        x1, y1 = CX + (R1 + 25) * math.cos(a), CY + (R1 + 25) * math.sin(a)
        lx, ly = CX + (R1 + 62) * math.cos(a), CY + (R1 + 62) * math.sin(a)
        marks.append(f'<line x1="{x0:.1f}" y1="{y0:.1f}" x2="{x1:.1f}" y2="{y1:.1f}" stroke="{color}" stroke-width="9" stroke-linecap="round" class="m"/>'
                     f'<text x="{lx:.1f}" y="{ly:.1f}" fill="{color}" class="ml">{html.escape(label)}</text>')
    rows = "".join(
        f'<div class="row"><span class="dot" style="background:{c};box-shadow:0 0 14px {c}"></span>'
        f'<span class="lab">{html.escape(l)}</span><span class="val" style="color:{vc}">{html.escape(v)}</span></div>'
        for c, l, v, vc in spec["rows"])
    st_t, st_c = spec["status"]
    foot = "<br>".join(html.escape(x) for x in spec.get("foot", []))
    page = f"""<!doctype html><html><head><meta charset="utf-8"><style>
@font-face{{font-family:V;src:url(file://{FONTS}/Vazirmatn-Regular.ttf);font-weight:400}}
@font-face{{font-family:V;src:url(file://{FONTS}/Vazirmatn-Bold.ttf);font-weight:700}}
html,body{{margin:0;width:1200px;height:1840px;background:#0b0d16;font-family:V,sans-serif}}
.card{{position:absolute;inset:28px;border-radius:60px;border:3px solid #b0336f;
 background:radial-gradient(900px 900px at 50% 32%,#0f1a28,#0b1220 60%,#0a0f1a);box-shadow:0 0 60px #b0336f55 inset,0 0 40px #b0336f44}}
.head{{position:absolute;left:70px;right:70px;top:70px;direction:rtl;text-align:center;color:#fff}}
h1{{font-size:66px;line-height:1.2;margin:0 0 10px;font-weight:700}}
.sub{{color:#a7b0c2;font-size:32px;line-height:1.5}} .stamp{{direction:ltr;unicode-bidi:isolate;display:inline-block}}
.left{{position:absolute;left:70px;right:70px;top:1075px;direction:rtl;text-align:right;color:#fff}}
.row{{display:flex;align-items:center;gap:24px;background:#141d2d;border:2px solid #24304a;border-radius:30px;padding:22px 32px;margin-bottom:16px}}
.dot{{width:40px;height:40px;border-radius:12px;flex:none}}
.lab{{font-size:40px;color:#eef1f8;flex:1}}
.val{{font-size:42px;font-weight:700;white-space:nowrap}}
.status{{font-size:40px;font-weight:700;margin:22px 0 10px;text-align:center}}
.foot{{color:#a0a8ba;font-size:28px;line-height:1.55;text-align:center}}
svg{{position:absolute;left:195px;top:225px;width:810px;height:810px;overflow:visible}}
.g{{filter:drop-shadow(0 0 10px currentColor)}} polygon.g{{filter:drop-shadow(0 0 9px rgba(120,200,255,.55))}}
.m{{filter:drop-shadow(0 0 8px currentColor)}} .ml{{font:700 46px V;text-anchor:middle;dominant-baseline:middle}}
.big{{font:700 170px V;fill:#fff;text-anchor:middle;filter:drop-shadow(0 0 18px rgba(255,255,255,.55))}}
.c2{{font:700 60px V;fill:#5ff0ff;text-anchor:middle}} .c3{{font:400 36px V;fill:#a7b0c2;text-anchor:middle}}
</style></head><body><div class="card"></div>
<div class="head"><h1>{html.escape(spec["title"])}</h1><div class="sub">{html.escape(spec["sub"])} · <span class="stamp">{html.escape(spec.get("stamp", ""))}</span></div></div>
<div class="left">{rows}
<div class="status" style="color:{st_c}">● {html.escape(st_t)}</div><div class="foot">{foot}</div></div>
<svg viewBox="0 0 800 800">{"".join(segs)}{"".join(marks)}
<text x="400" y="410" class="big" direction="rtl">{html.escape(spec["center"])}</text>
<text x="400" y="500" class="c2" direction="rtl">{html.escape(spec["center2"])}</text>
<text x="400" y="570" class="c3" direction="rtl">{html.escape(spec["center3"])}</text></svg></body></html>"""
    d = tempfile.mkdtemp(prefix="dash")
    try:
        f = os.path.join(d, "p.html")
        open(f, "w", encoding="utf-8").write(page)
        r = subprocess.run([CHROME, "--no-sandbox", "--headless", "--hide-scrollbars", "--disable-gpu", "--force-device-scale-factor=1.39",
                            "--window-size=1200,1840", f"--screenshot={os.path.abspath(out)}", "--virtual-time-budget=3000", f"file://{f}"],
                           capture_output=True, text=True, timeout=90)
        if not os.path.exists(out):
            raise RuntimeError(f"chrome failed: {r.stderr[-300:]}")
    finally:
        shutil.rmtree(d, ignore_errors=True)


def du(path):
    t = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                t += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return t


def docs(out):
    stamp, ym = jnow()
    c = sqlite3.connect(f"{ARCH}/archive.db") if os.path.exists(f"{ARCH}/archive.db") else None
    n = this_m = 0
    cats, last = [], None
    if c:
        try:
            n = c.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
            this_m = c.execute("SELECT COUNT(*) FROM docs WHERE substr(date,1,7)=?", (ym,)).fetchone()[0]
            cats = c.execute("SELECT category, COUNT(*) FROM docs GROUP BY 1 ORDER BY 2 DESC LIMIT 3").fetchall()
            last = c.execute("SELECT date FROM docs ORDER BY ts DESC LIMIT 1").fetchone()
        except sqlite3.OperationalError:
            pass
    disk = shutil.disk_usage("/")
    arch = 0                                         # documents live only on Drive now: their size, from the metadata
    if c:
        try:
            arch = c.execute("SELECT COALESCE(SUM(size),0) FROM docs").fetchone()[0] or 0
        except sqlite3.OperationalError:
            pass
    pct = disk.used * 100 / disk.total
    dv = drive_about()
    drive_txt = (f"{gb(dv['total'] - dv.get('free', 0))} از {fa(round(dv['total'] / 1024 ** 3))}" if dv else "نامعلوم")
    spec = {"title": "بایگانی اسناد و فضای سرور", "sub": "اسناد شما فقط در Google Drive (owner", "stamp": fa(stamp),
            "segments": [(disk.used / disk.total, "#8b5cff", "#ff3fd8")],
            "marks": [(0.8, "#ffe14a", fa("۸۰٪")), (0.9, "#ff4d5e", fa("۹۰٪"))],
            "center": fa(f"{pct:.0f}") + "٪", "center2": f"{fa(n)} سند", "center3": f"دیسک سرور: {gb(disk.used, 0)} از {fa(round(disk.total / 1024 ** 3))}",
            "rows": [("#ff3fd8", "اسناد بایگانی‌شده", f"{fa(n)} سند · این ماه {fa(this_m)}", "#ff7be8"),
                     ("#1fd2ff", "حجم اسناد در Drive", gb(arch), "#5ff0ff"),
                     ("#3df58f", "فضای آزاد سرور", gb(disk.free), "#3df58f"),
                     ("#ffb547", "Google Drive", drive_txt, "#ffc46b")],
            "status": status_of(pct),
            "foot": [(("پرتکرارترین پوشه‌ها: " + " · ".join(f"{k} {fa(v)}" for k, v in cats)) if cats else "بایگانی هنوز خالی است.")
                     + (f" · آخرین سند: {fa(last[0])}" if last and last[0] else ""),
                     "خط زرد = ۸۰٪ (هشدار) · خط قرمز = ۹۰٪ (بحرانی)"]}
    render(spec, out)
    return {"ok": True, "docs": n, "this_month": this_m, "disk_pct": round(pct, 1), "archive_bytes": arch}


def media(out):
    stamp, ym = jnow()
    c = sqlite3.connect(f"{ARCH}/archive.db") if os.path.exists(f"{ARCH}/archive.db") else None
    n = msize = this_m = 0
    kinds = {}
    if c:
        try:
            n, msize = c.execute("SELECT COUNT(*), COALESCE(SUM(size),0) FROM media").fetchone()
            this_m = c.execute("SELECT COUNT(*) FROM media WHERE substr(date,1,7)=?", (ym,)).fetchone()[0]
            kinds = dict(c.execute("SELECT kind, COUNT(*) FROM media GROUP BY 1").fetchall())
        except sqlite3.OperationalError:
            pass
    dv = drive_about()
    if not dv:
        return {"ok": False, "error": "drive_unreachable"}
    total, free, other, trash = dv["total"], dv.get("free", 0), dv.get("other", 0), dv.get("trashed", 0)
    drive_used = dv.get("used", 0)
    pct = (total - free) * 100 / total
    docs_on_drive = max(0, drive_used - msize)
    spec = {"title": "مدیا و Google Drive", "sub": "عکس، ویدیو، صدا و پرامپت — فقط در Drive (owner", "stamp": fa(stamp),
            "segments": [(msize / total, "#ff3fd8", "#b84dff"), (docs_on_drive / total, "#1fd2ff", "#3a8bff"),
                         (other / total, "#7c8396", "#4a5266")],
            "marks": [(0.8, "#ffe14a", fa("۸۰٪")), (0.9, "#ff4d5e", fa("۹۰٪"))],
            "center": fa(f"{pct:.0f}") + "٪", "center2": f"{gb(total - free)}", "center3": f"از {fa(round(total / 1024 ** 3))} گیگابایت Drive",
            "rows": [("#ff3fd8", "مدیا", f"{fa(n)} فایل · {gb(msize)}", "#ff7be8"),
                     ("#1fd2ff", "اسناد و بقیه‌ی فایل‌ها", gb(docs_on_drive), "#5ff0ff"),
                     ("#7c8396", "Gmail و Photos", gb(other), "#b9c0d0"),
                     ("#3df58f", "فضای آزاد Drive", gb(free), "#3df58f")],
            "status": status_of(pct),
            "foot": ["این ماه: " + fa(this_m) + " فایل · " + " · ".join(f"{l} {fa(kinds.get(k, 0))}" for k, l in
                                                                       (("video", "ویدیو"), ("image", "تصویر"), ("audio", "صدا"), ("text", "پرامپت"))),
                     "خط زرد = ۸۰٪ (هشدار) · خط قرمز = ۹۰٪ (بحرانی)" + (f" · سطل زباله: {gb(trash)}" if trash > 50 * 1024 ** 2 else "")]}
    render(spec, out)
    return {"ok": True, "media": n, "media_bytes": msize, "drive_pct": round(pct, 1), "drive_free": free}


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("docs", "media"):
        sys.exit(__doc__)
    try:
        print(json.dumps((docs if sys.argv[1] == "docs" else media)(sys.argv[2]), ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"[:300]}, ensure_ascii=False))
