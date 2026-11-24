#!/root/.hermes/shared-tools/docs/venv/bin/python
"""Token quota of ONE test account as the owner's favourite segmented ring (dashboard.render).
  trial_gauge.py <code> <out.png>
"""
import json, subprocess, sys, time, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dashboard import fa, jnow, render  # noqa: E402

code, out = sys.argv[1], sys.argv[2]
U = "/root/.hermes/shared-tools/admin/users_admin.py"
u = json.loads(subprocess.run(["python3", U, "trial-usage", code], capture_output=True, text=True).stdout.strip().splitlines()[-1])
t = json.load(open("/root/.hermes/shared-tools/admin/trials.json")).get(code, {})
who = t.get("label") or "تست‌کننده"
used, quota, base, bonus = u["used"], u["quota"], u["base"], u["bonus"]
pct = used / quota if quota else 0
left = max(0, quota - used)
num = lambda n: (fa(f"{n / 1e6:.2f}".rstrip("0").rstrip(".")) + " میلیون") if n >= 1e6 else (fa(f"{n / 1e3:.0f}") + " هزار") if n >= 1e3 else fa(n)
until = None
try:
    name = t["used"][0]["name"]
    until = json.load(open("/root/.hermes/shared-tools/admin/tiers.json")).get(name, {}).get("until")
except Exception:
    pass
hours = f"{fa(max(0, int((until - time.time()) // 3600)))} ساعت" if until else "—"
st = ("سهمیه تمام شده — دیگر جواب نمی‌گیرد", "#ff4d5e") if pct >= 1 else ("رو به اتمام", "#ffe14a") if pct >= 0.8 else ("وضعیت خوب", "#3df58f")
spec = {"title": f"سهمیه‌ی توکن {who}", "sub": "تست ۲۴ ساعته‌ی ایجنت هرمس", "stamp": fa(jnow()[0]),
        "segments": [(min(pct, 1), "#1fd2ff", "#ff3fd8")],
        "marks": [(0.8, "#ffe14a", fa("۸۰٪")), (0.9, "#ff4d5e", fa("۹۰٪"))],
        "center": fa(f"{min(pct, 9.99) * 100:.0f}") + "٪", "center2": f"{num(used)} توکن", "center3": f"از {num(quota)} سهمیه",
        "rows": [("#1fd2ff", "مصرف‌شده", num(used), "#5ff0ff"), ("#3df58f", "باقی‌مانده", num(left), "#3df58f"),
                 ("#ffb547", "سهمیه‌ی اضافه (۱۰٪ها)", num(bonus) if bonus else "—", "#ffc46b"), ("#8b5cff", "زمان باقی‌مانده‌ی تست", hours, "#b9a3ff")],
        "status": st,
        "foot": [f"سهمیه‌ی پایه {num(base)} · هر «➕ ۱۰٪» = {num(int(base * 0.1))} توکن", "توکن = ورودی + خروجی مدل‌ها"]}
render(spec, out)
print(json.dumps({"ok": True, **u}, ensure_ascii=False))
