#!/root/.hermes/shared-tools/docs/venv/bin/python
"""HermesVPN cartoon clips (owner request 2026-11-13): make an AI-generated clip Telegram-light, add the HermesVPN logo,
send the result back to the owner in the bot, and archive it ONLY on Drive (Media/کارتون-هرمس).

  cartoon_prep.py <video> [n] [--test]
Output: vertical 540px wide, 24 fps, H.264, no audio, logo bottom-right (60% opacity), usually < 1 MB for 5-10 s.
The input and the output are deleted afterwards (nothing stays on the server).
"""
import json, os, re, subprocess, sys, tempfile, urllib.request

LOGO = "/root/.hermes/ads/brand/hermesvpn-icon.png"
OWNER = "100000001"
D = os.path.dirname(os.path.abspath(__file__))


def send_video(path, caption):
    import uuid
    tok = re.search(r"^TELEGRAM_BOT_TOKEN=(.*)$", open("/root/.hermes/.env").read(), re.M).group(1).strip().strip('"')
    b = uuid.uuid4().hex
    parts = [f'--{b}\r\nContent-Disposition: form-data; name="chat_id"\r\n\r\n{OWNER}\r\n',
             f'--{b}\r\nContent-Disposition: form-data; name="caption"\r\n\r\n{caption}\r\n',
             f'--{b}\r\nContent-Disposition: form-data; name="supports_streaming"\r\n\r\ntrue\r\n',
             f'--{b}\r\nContent-Disposition: form-data; name="video"; filename="{os.path.basename(path)}"\r\nContent-Type: video/mp4\r\n\r\n']
    body = "".join(parts).encode() + open(path, "rb").read() + f"\r\n--{b}--\r\n".encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendVideo", data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={b}"})
    return json.load(urllib.request.urlopen(req, timeout=120)).get("ok")


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    src = sys.argv[1]
    n = next((a for a in sys.argv[2:] if a.isdigit()), "")
    test = "--test" in sys.argv
    tmp = tempfile.mkdtemp(prefix="cartoon")
    out = os.path.join(tmp, f"hermes-cartoon-{n or 'x'}.mp4")
    vf = ("[0:v]scale=540:-2:flags=lanczos,fps=24[v];[1:v]scale=96:-1,format=rgba,colorchannelmixer=aa=0.6[l];"
          "[v][l]overlay=W-w-16:H-h-16")
    for crf in (28, 32, 36):                                  # keep it light for slow connections in Iran
        r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-i", LOGO, "-filter_complex", vf, "-an",
                            "-c:v", "libx264", "-preset", "slow", "-crf", str(crf), "-pix_fmt", "yuv420p", "-movflags", "+faststart", out],
                           capture_output=True, text=True, timeout=300)
        if r.returncode:
            print(json.dumps({"ok": False, "error": r.stderr[-300:]}, ensure_ascii=False))
            return
        if os.path.getsize(out) <= 1_200_000:
            break
    size = os.path.getsize(out)
    try:
        cap = json.load(open("/root/.hermes/ads/cartoons/captions.json")).get(n, "")
    except Exception:
        cap = ""
    preview = (f"👁 پیش‌نمایش کارتون {n} ({size // 1024} کیلوبایت) — هنوز جایی منتشر نشده.\n\n"
               f"متن پیشنهادی پست:\n{cap or '(متن ندارد)'}\n\n"
               f"✅ برای انتشار در کانال و گروه بنویس: «کارتون {n} رو منتشر کن»\n✏️ برای متن دیگر: «متن کارتون {n} رو عوض کن: ...»")
    sent = None if test else send_video(out, preview[:1020])
    env = dict(os.environ, **({"HERMES_ARCHIVE_TEST": "1", "HERMES_ARCHIVE_DIR": tmp + "-arch"} if test else {}))   # tests never touch the live DB
    a = subprocess.run([f"{D}/venv/bin/python", f"{D}/media.py", "add-file", out, "کارتون-هرمس", f"کارتون {n} HermesVPN #کارتون"],
                       capture_output=True, text=True, timeout=1800, env=env)
    try:
        arch = json.loads(a.stdout.strip().splitlines()[-1])
    except Exception:
        arch = {"ok": False, "error": a.stderr[-200:]}
    if arch.get("ok") and not test and os.path.exists(src):
        os.remove(src)
    for f in os.listdir(tmp):
        os.remove(os.path.join(tmp, f))
    os.rmdir(tmp)
    if not test and arch.get("ok"):
        stf = "/root/.hermes/ads/cartoons/state.json"
        try:
            stt = json.load(open(stf))
        except Exception:
            stt = {}
        stt[n or str(arch["id"])] = {"media_id": arch["id"], "link": arch.get("link"), "caption": cap, "status": "preview", "ts": __import__("time").time()}
        json.dump(stt, open(stf, "w"), ensure_ascii=False, indent=1)
    print(json.dumps({"ok": True, "size_kb": size // 1024, "preview_sent_to_owner": sent, "archived": arch.get("ok"), "link": arch.get("link"),
                      "status": "preview — NOT published; publish only after the owner says «کارتون N رو منتشر کن»"}, ensure_ascii=False))


main()
