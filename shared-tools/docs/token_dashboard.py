#!/root/.hermes/shared-tools/docs/venv/bin/python
"""Token usage by AI model — donut chart for the owner's admin panel (owner request 2026-11-14, via oracle).

  token_dashboard.py today|7d|month <out.png>
Sources: every profile's state.db (session_model_usage, metadata only: model, token counts, cost — no content) and the
oracle HermesVPN admin bot's hourly aggregate (separate key). Credit: OpenRouter key 'AGENT HERMES ADMIN' + balance.
Rendered as HTML (Vazirmatn) by headless Chromium, same look as dashboard.py. Prints one JSON line.
"""
import glob, html, json, math, os, re, sqlite3, subprocess, sys, tempfile, time, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dashboard import CHROME, FONTS, fa, jnow, render as gauge_render  # noqa: E402

ORACLE = "https://hook.example.com:2087/dl/ai-usage-EXAMPLE.json"
# USD per 1M tokens (in, out, cache read, cache write) — paid models only; free tiers cost 0
PRICE = {"anthropic/claude-haiku-5.5": (0.10, 0.50, 0.01, 0.125)}
NAMES = [("claude-haiku", "Claude Haiku 5.5 (پولی)"), ("ernie", "ERNIE (رایگان)"), ("gemini", "Gemini Flash (رایگان)"),
         ("longcat", "LongCat (رایگان)"), ("step", "StepFun (رایگان)"), ("minimax", "MiniMax (DAHL)"),
         ("beam", "Beam (رایگان)"), ("nemotron", "Nemotron (رایگان)")]
COLORS = ["#ff3fd8", "#1fd2ff", "#3df58f", "#ffb547", "#8b5cff", "#ff6b6b", "#5ff0ff", "#c4f53d", "#b9c0d0", "#f5d63d"]
ORACLE_LABEL = "ربات مدیریت VPN (Haiku)"


def nice(model):
    m = (model or "").lower()
    return next((n for k, n in NAMES if k in m), model or "?")


def since(period):
    now = time.time()
    t = time.gmtime(now + 12600)
    midnight = now - (t.tm_hour * 3600 + t.tm_min * 60 + t.tm_sec)          # Tehran midnight
    if period == "today":
        return midnight, "امروز"
    if period == "7d":
        return now - 7 * 86400, "۷ روز گذشته"
    g = time.gmtime(now)
    return time.mktime((g.tm_year, g.tm_mon, 1, 0, 0, 0, 0, 0, 0)) - time.timezone, "این ماه (از اول ماه میلادی)"


def local_usage(t0):
    agg = {}
    for db in ["/root/.hermes/state.db"] + glob.glob("/root/.hermes/profiles/*/state.db"):
        try:
            c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            for m, n, i, o, cr, cw, cost in c.execute(
                    "SELECT model, SUM(api_call_count), SUM(input_tokens), SUM(output_tokens), SUM(cache_read_tokens),"
                    " SUM(cache_write_tokens), SUM(COALESCE(actual_cost_usd, estimated_cost_usd, 0)) FROM session_model_usage"
                    " WHERE last_seen > ? GROUP BY model", (t0,)):
                a = agg.setdefault(nice(m), {"calls": 0, "tok": 0, "cache": 0, "cost": 0.0})
                a["calls"] += n or 0
                a["tok"] += (i or 0) + (o or 0)
                a["cache"] += cr or 0
                p = PRICE.get(m)
                if "minimax" in (m or "").lower():
                    a["unknown"] = True                     # DAHL provider: price not known here
                a["cost"] += (((i or 0) * p[0] + (o or 0) * p[1] + (cr or 0) * p[2] + (cw or 0) * p[3]) / 1e6) if p else (cost or 0)
        except Exception as e:
            print(f"skip {db}: {e}", file=sys.stderr)
    return agg


def oracle_usage(t0):
    try:
        d = json.load(urllib.request.urlopen(ORACLE, timeout=20))
    except Exception as e:
        print(f"oracle feed: {e}", file=sys.stderr)
        return None
    day0 = time.strftime("%Y-%m-%d", time.gmtime(t0 + 12600))
    rows = [r for r in d.get("rows", []) if r.get("day", "") >= day0]
    return {"calls": sum(r.get("calls", 0) for r in rows), "tok": sum(r.get("in", 0) + r.get("out", 0) for r in rows),
            "cache": 0, "cost": sum(float(r.get("cost") or 0) for r in rows)}


def credit():
    try:
        env = open("/root/.hermes/.env").read()
        key = re.search(r"^OPENROUTER_API_KEY=(.*)$", env, re.M).group(1).strip().strip('"')
        get = lambda u: json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"Authorization": f"Bearer {key}"}), timeout=20)).get("data", {})
        k, cr = get("https://openrouter.ai/api/v1/key"), get("https://openrouter.ai/api/v1/credits")
        return k.get("limit"), k.get("limit_remaining"), float(cr.get("total_credits") or 0) - float(cr.get("total_usage") or 0)
    except Exception as e:
        print(f"credit: {e}", file=sys.stderr)
        return None, None, None


def tok(n):
    n = float(n)
    if n >= 1e6:
        return fa(f"{n / 1e6:.1f}".rstrip("0").rstrip(".")) + " میلیون"
    if n >= 1e3:
        return fa(f"{n / 1e3:.0f}") + " هزار"
    return fa(int(n))


def usd(x):
    if x is None:
        return "نامعلوم"
    return "رایگان" if x < 0.00005 else "$" + fa(f"{x:.4f}" if x < 0.01 else f"{x:.2f}")


def render(items, period_fa, totals, cred, out):
    total = sum(v["tok"] for _, v in items) or 1
    CX = CY = 400
    R1, R0 = 330, 215
    arcs, a0 = [], -90.0
    for idx, (name, v) in enumerate(items):
        frac = v["tok"] / total
        if frac <= 0:
            continue
        a1 = a0 + frac * 360
        large = 1 if a1 - a0 > 180 else 0
        p = lambda r, a: (CX + r * math.cos(math.radians(a)), CY + r * math.sin(math.radians(a)))
        (x1, y1), (x2, y2), (x3, y3), (x4, y4) = p(R1, a0), p(R1, a1 - 0.01), p(R0, a1 - 0.01), p(R0, a0)
        col = COLORS[idx % len(COLORS)]
        arcs.append(f'<path d="M{x1:.1f},{y1:.1f} A{R1},{R1} 0 {large} 1 {x2:.1f},{y2:.1f} L{x3:.1f},{y3:.1f} '
                    f'A{R0},{R0} 0 {large} 0 {x4:.1f},{y4:.1f} Z" fill="{col}" stroke="#0b1220" stroke-width="5" '
                    f'style="filter:drop-shadow(0 0 10px {col}88)"/>')
        a0 = a1
    rows = "".join(
        f'<div class="row"><span class="dot" style="background:{COLORS[i % len(COLORS)]};box-shadow:0 0 12px {COLORS[i % len(COLORS)]}"></span>'
        f'<span class="lab">{html.escape(n)}</span><span class="val">{tok(v["tok"])}<small> · {fa(round(v["tok"] * 100 / total))}٪</small>'
        f'<em>{usd(None if v.get("unknown") else v["cost"])}</em></span></div>' for i, (n, v) in enumerate(items[:9]))
    lim, left, bal = cred
    foot = []
    if lim is not None and left is not None:
        foot.append(f"کلید AGENT HERMES ADMIN: {usd(float(left))} مانده از سقف ماهانه‌ی {usd(float(lim))}")
    if bal is not None:
        foot.append(f"اعتبار کل حساب OpenRouter: {usd(bal)}")
    foot.append("توکن = ورودی + خروجی (بدون حافظه‌ی موقت) · مدل‌های رایگان هزینه ندارند")
    page = f"""<!doctype html><html><head><meta charset="utf-8"><style>
@font-face{{font-family:V;src:url(file://{FONTS}/Vazirmatn-Regular.ttf);font-weight:400}}
@font-face{{font-family:V;src:url(file://{FONTS}/Vazirmatn-Bold.ttf);font-weight:700}}
html,body{{margin:0;width:1920px;height:1200px;background:#0b0d16;font-family:V,sans-serif}}
.card{{position:absolute;inset:42px;border-radius:64px;border:3px solid #b0336f;
 background:radial-gradient(1200px 800px at 70% 50%,#0f1a28,#0b1220 60%,#0a0f1a);box-shadow:0 0 60px #b0336f55 inset,0 0 40px #b0336f44}}
.left{{position:absolute;left:92px;top:80px;width:760px;direction:rtl;text-align:right;color:#fff}}
h1{{font-size:54px;margin:0 0 6px;font-weight:700}} .sub{{color:#9aa3b5;font-size:26px;margin-bottom:18px}}
.row{{display:flex;align-items:center;gap:18px;background:#141d2d;border:2px solid #24304a;border-radius:22px;padding:10px 24px;margin-bottom:9px}}
.dot{{width:28px;height:28px;border-radius:8px;flex:none}} .lab{{font-size:27px;color:#e8ecf5;flex:1}}
.val{{font-size:27px;font-weight:700;color:#fff;white-space:nowrap}} .val small{{color:#9aa3b5;font-weight:400}} .val em{{font-style:normal;color:#3df58f;margin-right:14px}}
.foot{{color:#9aa3b5;font-size:22px;line-height:1.6;margin-top:12px}}
svg{{position:absolute;right:130px;top:200px;width:800px;height:800px}}
.big{{font:700 96px V;fill:#fff;text-anchor:middle;filter:drop-shadow(0 0 16px rgba(255,255,255,.45))}}
.c2{{font:700 40px V;fill:#5ff0ff;text-anchor:middle}} .c3{{font:400 30px V;fill:#9aa3b5;text-anchor:middle}}
</style></head><body><div class="card"></div>
<div class="left" style="top:70px"><h1>مصرف توکن به تفکیک مدل</h1><div class="sub">{html.escape(period_fa)} · {fa(jnow()[0])}</div>{rows}
<div class="foot">{"<br>".join(html.escape(x) for x in foot)}</div></div>
<svg viewBox="0 0 800 800">{"".join(arcs)}
<text x="400" y="395" class="big" direction="rtl">{tok(totals["tok"])}</text>
<text x="400" y="455" class="c2" direction="rtl">توکن · {fa(totals["calls"])} درخواست</text>
<text x="400" y="510" class="c3" direction="rtl">هزینه: {usd(totals["cost"])}</text></svg></body></html>"""
    d = tempfile.mkdtemp(prefix="tokdash")
    try:
        f = os.path.join(d, "p.html")
        open(f, "w", encoding="utf-8").write(page)
        subprocess.run([CHROME, "--no-sandbox", "--headless", "--hide-scrollbars", "--disable-gpu", "--force-device-scale-factor=1",
                        "--window-size=1920,1200", f"--screenshot={os.path.abspath(out)}", "--virtual-time-budget=3000", f"file://{f}"],
                       capture_output=True, text=True, timeout=90)
        if not os.path.exists(out):
            raise RuntimeError("chrome failed")
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ("today", "7d", "month"):
        sys.exit(__doc__)
    t0, period_fa = since(sys.argv[1])
    agg = local_usage(t0)
    o = oracle_usage(t0)
    if o and o["tok"]:
        agg[ORACLE_LABEL] = o
    items = sorted(agg.items(), key=lambda kv: -kv[1]["tok"])
    totals = {k: sum(v[k] for _, v in items) for k in ("tok", "calls", "cost")}
    cred = credit()
    # same segmented, glowing ring as the archive / Drive dashboards (owner: «مثل همون دایره‌ای قبلی»)
    total = totals["tok"] or 1
    short = lambda n: n.replace(" (رایگان)", "").replace(" (پولی)", "")
    haiku = [(n, v) for n, v in items if "Haiku" in n]
    others = [(n, v) for n, v in items if "Haiku" not in n]
    top = others[:3]
    rest = others[3:]
    hk = {"tok": sum(v["tok"] for _, v in haiku), "cost": sum(v["cost"] for _, v in haiku)}
    rest_v = {"tok": sum(v["tok"] for _, v in rest), "cost": 0}
    pal = [("#ff3fd8", "#b84dff"), ("#1fd2ff", "#3a8bff"), ("#3df58f", "#1fb86a"), ("#ffb547", "#ff7a3d"), ("#7c8396", "#4a5266")]
    slices = top + [("Claude Haiku", hk), ("بقیه", rest_v)]
    lim, left, bal = cred
    num = totals["tok"]
    big, unit = ((fa(f"{num / 1e6:.1f}".rstrip("0").rstrip(".")), "میلیون توکن") if num >= 1e6 else
                 (fa(f"{num / 1e3:.0f}"), "هزار توکن") if num >= 1e3 else (fa(num), "توکن"))
    pct = lambda v: fa(round(v["tok"] * 100 / total)) + "٪"
    rows = [(pal[i][0], short(n), f"{tok(v['tok'])} · {pct(v)}", pal[i][0]) for i, (n, v) in enumerate(top)]
    rows.append((pal[3][0], "Claude Haiku (پولی)", f"{tok(hk['tok'])} · {usd(hk['cost'])}", pal[3][0]))
    spec = {"title": "مصرف توکن هوش مصنوعی", "sub": f"به تفکیک مدل · {period_fa}", "stamp": fa(jnow()[0]),
            "segments": [(v["tok"] / total, pal[i][0], pal[i][1]) for i, (_, v) in enumerate(slices)],
            "marks": [], "center": big, "center2": unit,
            "center3": f"{fa(totals['calls'])} درخواست · هزینه {usd(totals['cost'])}",
            "rows": rows,
            "status": ((f"کلید Haiku: {usd(float(left))} مانده از {usd(float(lim))}", "#3df58f" if float(left) > 1 else "#ffe14a")
                       if left is not None and lim else ("اعتبار کلید نامعلوم", "#ffe14a")),
            "foot": [f"بقیه‌ی مدل‌ها: {tok(rest_v['tok'])} · Haiku = ایجنت شما، کاربر۲ و ربات مدیریت VPN",
                     (f"اعتبار کل OpenRouter: {usd(bal)} · " if bal is not None else "") + "مدل‌های رایگان هزینه ندارند"]}
    gauge_render(spec, sys.argv[2])
    print(json.dumps({"ok": True, "period": sys.argv[1], "total_tokens": totals["tok"], "calls": totals["calls"],
                      "cost_usd": round(totals["cost"], 4), "oracle_included": bool(o),
                      "models": {n: {"tok": v["tok"], "cost": round(v["cost"], 4)} for n, v in items},
                      "key_left": cred[1], "balance": cred[2]}, ensure_ascii=False))


main()
