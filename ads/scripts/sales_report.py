#!/usr/bin/env python3
"""HermesVPN sales report (READ-ONLY) — for Agent-Hermes («امروز چقدر فروختیم؟»).

  sales_report.py               # today (Tehran)
  sales_report.py --days 7      # last 7 days
Reads the sales bot's orders DB on the Oracle server over ssh in read-only mode; changes nothing.
"""
import json, subprocess, sys, argparse, datetime

TZ = datetime.timezone(datetime.timedelta(hours=3, minutes=30))
REMOTE = r'''
import json, sqlite3, sys
start = int(sys.argv[1])
c = sqlite3.connect("file:/root/.hermes-orders.db?mode=ro", uri=True)
q = lambda s, *a: c.execute(s, a).fetchall()
out = {
 "approved": q("SELECT COUNT(*), COALESCE(SUM(total_price),0), COUNT(DISTINCT tg_id) FROM orders WHERE status='approved' AND COALESCE(decided_at,created_at)>=?", start)[0],
 "by_plan": q("SELECT plan_key, COUNT(*), COALESCE(SUM(total_price),0) FROM orders WHERE status='approved' AND COALESCE(decided_at,created_at)>=? GROUP BY plan_key ORDER BY 2 DESC", start),
 "renewals": q("SELECT COUNT(*) FROM orders WHERE status='approved' AND target_email IS NOT NULL AND target_email!='' AND COALESCE(decided_at,created_at)>=?", start)[0][0],
 "pending_review": q("SELECT COUNT(*) FROM orders WHERE status='pending_review'")[0][0],
 "abandoned": q("SELECT COUNT(*) FROM orders WHERE status='awaiting_receipt' AND created_at>=?", start)[0][0],
 "rejected": q("SELECT COUNT(*) FROM orders WHERE status='rejected' AND created_at>=?", start)[0][0],
 "new_users": q("SELECT COUNT(*) FROM users WHERE created_at>=?", start)[0][0],
 "users_total": q("SELECT COUNT(*) FROM users")[0][0],
 "buyers_total": q("SELECT COUNT(DISTINCT tg_id) FROM orders WHERE status='approved'")[0][0],
 "first_time": q("SELECT COUNT(*) FROM (SELECT tg_id, MIN(COALESCE(decided_at,created_at)) f FROM orders WHERE status='approved' GROUP BY tg_id) WHERE f>=?", start)[0][0],
}
have = {r[0] for r in q("SELECT name FROM sqlite_master WHERE type='table'")}
if "referrals" in have:
    out["ref_joined"] = q("SELECT COUNT(*) FROM referrals WHERE created_at>=?", start)[0][0]
    out["ref_paid"] = q("SELECT COUNT(*) FROM referrals WHERE status='paid' AND paid_at>=?", start)[0][0]
if "nudges" in have:
    out["nudges"] = q("SELECT COUNT(*) FROM nudges WHERE ts>=?", start // 1000)[0][0]
print(json.dumps(out))
'''


def fetch(start_ms):
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", "oracle-vpn", "sudo", "python3", "-", str(start_ms)],
                       input=REMOTE, capture_output=True, text=True, timeout=60)
    if r.returncode:
        raise SystemExit("خطا در خواندن آمار فروش: " + r.stderr[-300:])
    return json.loads(r.stdout)


def render(d, title):
    n, toman, buyers = d["approved"]
    L = [f"💰 گزارش فروش HermesVPN — {title}", "",
         f"✅ فروش تأییدشده: {n} سفارش — {toman:,} تومان — {buyers} خریدار",
         f"   🆕 خریدار جدید (اولین خرید): {d['first_time']} | 🔁 تمدید: {d['renewals']}"]
    if d["by_plan"]:
        L.append("   پلن‌ها: " + "، ".join(f"{p} × {c} ({s:,})" for p, c, s in d["by_plan"]))
    L += [f"⏳ منتظر بررسی رسید: {d['pending_review']} | 🛒 نیمه‌کاره در این بازه: {d['abandoned']} | ❌ رد شده: {d['rejected']}",
          f"👤 کاربر جدید ربات: {d['new_users']} (کل کاربرها: {d['users_total']}، کل خریدارها: {d['buyers_total']})"]
    if "ref_joined" in d:
        L.append(f"🎁 دعوت: {d['ref_joined']} نفر با لینک دعوت آمدند، {d['ref_paid']} نفر خرید کردند")
    if "nudges" in d:
        L.append(f"🔔 یادآوری‌های فرستاده‌شده (تمدید/سفارش نیمه‌کاره): {d['nudges']}")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=1)
    a = ap.parse_args()
    now = datetime.datetime.now(TZ)
    if a.days <= 1:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        title = f"امروز تا ساعت {now:%H:%M}"
    else:
        start = now - datetime.timedelta(days=a.days)
        title = f"{a.days} روز گذشته"
    print(render(fetch(int(start.timestamp() * 1000)), title))


if __name__ == "__main__":
    main()
