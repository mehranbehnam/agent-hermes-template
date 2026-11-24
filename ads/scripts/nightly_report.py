#!/usr/bin/env python3
"""Nightly summary for Owner (owner item 4): today's sales + channel/group stats, sent by @your_agent_bot.
Prints nothing on success (so a no-agent Hermes cron stays silent)."""
import subprocess, urllib.request, urllib.parse, sys

S = "/root/.hermes/ads/scripts"
parts = []
for cmd in ([f"{S}/sales_report.py"], ["/usr/bin/python3", f"{S}/chan_stats.py", "report"]):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    parts.append(r.stdout.strip() or ("⚠️ " + r.stderr.strip()[-300:]))
text = "🌙 گزارش شبانه‌ی HERMES VPN\n\n" + "\n\n――――――――――――――――\n\n".join(parts)
tok = [l.split("=", 1)[1].strip().strip("\"'") for l in open("/root/.hermes/.env") if l.startswith("TELEGRAM_BOT_TOKEN=")][0]
for i in range(0, len(text), 3900):
    urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/sendMessage", data=urllib.parse.urlencode(
        {"chat_id": 100000001, "text": text[i:i + 3900]}).encode(), timeout=30).read()
