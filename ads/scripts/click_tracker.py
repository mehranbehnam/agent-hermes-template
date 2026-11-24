"""Click tracker for HERMES VPN ads.

Serves short tracking links that record every hit (who/when/where) and redirect
to the real destination. Reads its port/host from env (TRACK_HOST / TRACK_PORT),
defaults to 0.0.0.0:8090 (nothing else uses that port).

  GET /<code>            -> record hit, redirect to destination
  GET /r/<code>          -> same, alias
  GET /hits?code=...     -> JSON summary (owner only; no auth needed on this box)

Codes are short and stable: vpn1, vpn2, agent1, group1 ...
"""
import json, os, sqlite3, time, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DB = "/root/.hermes/ads/stats/clicks.db"
DEST = {
    # ads -> sales bot / group / channel
    "vpn1": "https://t.me/your_sales_bot",
    "vpn2": "https://t.me/your_sales_bot",
    "vpn3": "https://t.me/your_sales_bot",
    "agent1": "https://t.me/HERMES_AGENT",
    "agent2": "https://t.me/HERMES_AGENT",
    "group1": "https://t.me/your_group",
    "chan1": "https://t.me/your_channel",
}

os.makedirs(os.path.dirname(DB), exist_ok=True)
con = sqlite3.connect(DB, check_same_thread=False)
con.execute("""CREATE TABLE IF NOT EXISTS hits
               (ts REAL, code TEXT, ip TEXT, ua TEXT, ref TEXT, dest TEXT)""")
con.commit()


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="text/plain; charset=utf-8", extra=None):
        b = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        code = u.path.strip("/").replace("r/", "")

        if u.path.startswith("/hits"):
            where, args = "", []
            if q.get("code"):
                where = "WHERE code=?"
                args = [q["code"][0]]
            rows = con.execute(
                f"SELECT code, COUNT(*), MIN(ts), MAX(ts) FROM hits {where} GROUP BY code ORDER BY 2 DESC",
                args).fetchall()
            total = con.execute(f"SELECT COUNT(*) FROM hits {where}", args).fetchone()[0]
            self._send(200, json.dumps({"total": total, "codes": rows}, ensure_ascii=False),
                       "application/json; charset=utf-8")
            return

        if u.path.startswith("/all"):
            rows = con.execute("SELECT ts, code, ip, ref FROM hits ORDER BY ts DESC LIMIT 200").fetchall()
            self._send(200, json.dumps(rows, ensure_ascii=False), "application/json; charset=utf-8")
            return

        if code in DEST:
            ip = self.headers.get("X-Forwarded-For", self.client_address[0])
            ua = self.headers.get("User-Agent", "")[:200]
            ref = self.headers.get("Referer", "")[:200]
            con.execute("INSERT INTO hits VALUES (?,?,?,?,?,?)",
                        (time.time(), code, ip, ua, ref, DEST[code]))
            con.commit()
            self._send(302, "redirecting", extra={"Location": DEST[code]})
            return

        self._send(404, "not found")


if __name__ == "__main__":
    host = os.environ.get("TRACK_HOST", "0.0.0.0")
    port = int(os.environ.get("TRACK_PORT", "8090"))
    print(f"click tracker on {host}:{port}")
    ThreadingHTTPServer((host, port), H).serve_forever()
