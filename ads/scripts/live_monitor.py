#!/usr/bin/python3
"""«پایشگر لحظه‌ای» — live watcher for the HermesVPN channel + group. Sends Owner a DM (via @your_agent_bot)
when something happens. It does NOT answer customers itself: group replies are given in real time by the
separate «hermesgroup» bot profile; this watcher tells Owner about everything and flags questions that stayed
unanswered.

  live_monitor.py on | off | status     # turn the watcher on/off (cron calls «tick» every 5 minutes)
  live_monitor.py tick                  # one check (used by cron; does nothing while off)

Alerts:
  ➕/➖ someone joined / left / was added to the channel or the group (name + @username)
  💬 a customer wrote in the group (text) — and whether the support bot answered
  ⚠️ a customer message got NO answer within 4 minutes → Owner can answer it himself
  📈 a channel post is getting unusually many views (≥ 2x the average of the last 10 posts)
"""
import os, sys, json, time, asyncio, datetime, urllib.request, urllib.parse
import glob
_HPY = sorted(glob.glob("/root/.hermes/tools/python*/bin/python3"))[-1]
if os.path.realpath(sys.executable) != os.path.realpath(_HPY):   # run with Hermes' Python before importing chan_stats
    os.execv(_HPY, [_HPY, os.path.abspath(__file__)] + sys.argv[1:])

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import chan_stats as cs                       # same Python re-exec + session-copy helpers
from telethon import functions, types

FLAG = f"{cs.DIR}/live_monitor.on"      # cs.DIR already honors CS_DIR, so IranVPN gets its own flag/state
STATE = f"{cs.DIR}/live_monitor_state.json"
OWNER = 100000001
BOT_ID = 100000002                           # @your_agent_bot (support replies in the group)
OWN_IDS = {100000001, 100000002, 100000001}
NO_ANSWER_AFTER = 240


def notify(text):
    tok = [l.split("=", 1)[1].strip().strip("\"'") for l in open("/root/.hermes/.env") if l.startswith("TELEGRAM_BOT_TOKEN=")][0]
    for i in range(0, len(text), 3900):
        urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/sendMessage", data=urllib.parse.urlencode(
            {"chat_id": OWNER, "text": text[i:i + 3900], "disable_web_page_preview": "true"}).encode(), timeout=20).read()


BRAND = os.environ.get("LM_BRAND", "hermes")
WELCOME = os.environ.get("LM_WELCOME") or ("👋 {name} عزیز، به گروه HERMES VPN خوش اومدی!\n\n"
           "سؤالی درباره‌ی خرید، اتصال یا قیمت‌ها داری همین‌جا بپرس 🙌\n"
           "🧪 تست رایگان ۵۰۰ مگ / ۲۴ ساعت و خرید آنی: @your_sales_bot\n"
           "📢 کانال اخبار و آموزش: @your_channel\n\n"
           "⚠️ لطفاً لینک و تبلیغ نفرست و احترام بقیه رو حفظ کن.")


def welcome(u):
    """Greet a new group member from the support bot (owner item 7)."""
    if u is None or getattr(u, "bot", False):
        return
    name = (getattr(u, "first_name", "") or "دوست").strip()[:30]
    text = WELCOME.format(name=name)
    sys.path.insert(0, "/root/.hermes/ads/scripts")
    from public_text_guard import check
    if check(text.replace(name, "")):
        return
    tok = [l.split("=", 1)[1].strip().strip("\"'") for l in open("/root/.hermes/.env") if l.startswith("TELEGRAM_BOT_TOKEN=")][0]
    urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/sendMessage", data=urllib.parse.urlencode(
        {"chat_id": "@" + cs.GROUP, "text": text}).encode(), timeout=20).read()


def who(u):
    if u is None:
        return "?"
    n = ((getattr(u, "first_name", "") or "") + " " + (getattr(u, "last_name", "") or "")).strip() or str(u.id)
    return n + (f" (@{u.username})" if getattr(u, "username", None) else "")


async def tick():
    st = json.load(open(STATE)) if os.path.exists(STATE) else {}
    first_run = not st
    c = await cs.client()
    alerts = []
    try:
        # joins / leaves / adds
        for chat, label in ((cs.CHANNEL, "کانال"), (cs.GROUP, "گروه")):
            ent = await c.get_entity(chat)
            log = await c(functions.channels.GetAdminLogRequest(
                channel=ent, q="", max_id=0, min_id=st.get(f"ev_{chat}", 0), limit=50,
                events_filter=types.ChannelAdminLogEventsFilter(join=True, leave=True, invite=True)))
            users = {u.id: u for u in log.users}
            for ev in sorted(log.events, key=lambda e: e.id):
                st[f"ev_{chat}"] = max(st.get(f"ev_{chat}", 0), ev.id)
                if first_run:
                    continue
                act = type(ev.action).__name__
                if "Leave" in act:
                    alerts.append(f"➖ {who(users.get(ev.user_id))} از {label} لفت داد")
                elif "Invite" in act and getattr(ev.action, "participant", None) is not None:
                    pid = getattr(ev.action.participant, "user_id", None)
                    alerts.append(f"➕ {who(users.get(pid))} به {label} اضافه شد (توسط {who(users.get(ev.user_id))})")
                    if chat == cs.GROUP:
                        try:
                            welcome(users.get(pid))
                        except Exception as e:
                            alerts.append(f"(خوشامد گروه ارسال نشد: {type(e).__name__})")
                else:
                    alerts.append(f"➕ {who(users.get(ev.user_id))} عضو {label} شد")
                    if chat == cs.GROUP:
                        try:
                            welcome(users.get(ev.user_id))
                        except Exception as e:
                            alerts.append(f"(خوشامد گروه ارسال نشد: {type(e).__name__})")
        # new customer messages in the group + unanswered check
        pending = st.get("pending", {})              # msg_id -> [ts, sender, text]
        last = st.get("last_msg", 0)
        newest = last
        msgs = [m async for m in c.iter_messages(cs.GROUP, min_id=last, limit=50)]
        for m in sorted(msgs, key=lambda x: x.id):
            newest = max(newest, m.id)
            if first_run or m.action or not m.sender_id:
                continue
            if m.sender_id == BOT_ID and m.reply_to and str(m.reply_to.reply_to_msg_id) in pending:
                pending.pop(str(m.reply_to.reply_to_msg_id), None)
                continue
            if m.sender_id == BOT_ID:                  # answered without quoting: clear the oldest open question
                if pending:
                    pending.pop(sorted(pending, key=lambda k: pending[k][0])[0], None)
                continue
            if m.sender_id in OWN_IDS or getattr(m.sender, "bot", False):
                continue
            text = (m.raw_text or "[عکس/فایل/استیکر]").replace("\n", " ")[:300]
            alerts.append(f"💬 {who(m.sender)} در گروه نوشت: «{text}»")
            pending[str(m.id)] = [int(m.date.timestamp()), who(m.sender), text]
        st["last_msg"] = newest
        now = time.time()
        for mid, (ts, sender, text) in list(pending.items()):
            if now - ts > NO_ANSWER_AFTER:
                alerts.append(f"⚠️ بی‌پاسخ ماند — {sender}: «{text[:150]}» (t.me/your_group/{mid})")
                pending.pop(mid)
        st["pending"] = pending
        # owner: hide the group's member list — Telegram allows it only from 100 members, so switch it on then
        if not st.get("members_hidden"):
            gent = await c.get_entity(cs.GROUP)
            gfull = await c(functions.channels.GetFullChannelRequest(gent))
            if getattr(gfull.full_chat, "participants_hidden", False):
                st["members_hidden"] = True
            elif (gfull.full_chat.participants_count or 0) >= 100:
                try:
                    await c(functions.channels.ToggleParticipantsHiddenRequest(channel=gent, enabled=True))
                    st["members_hidden"] = True
                    alerts.append("🙈 گروه به ۱۰۰ عضو رسید — لیست اعضای گروه برای بقیه مخفی شد")
                except Exception as e:
                    alerts.append(f"⚠️ مخفی کردن اعضای گروه نشد: {type(e).__name__}")
        # channel view spike
        posts = [m async for m in c.iter_messages(cs.CHANNEL, limit=12) if not m.sticker and m.views]
        if len(posts) >= 5:
            avg = sum(p.views for p in posts[1:11]) / max(1, len(posts[1:11]))
            top = posts[0]
            if not first_run and top.views >= max(10, 2 * avg) and st.get("spike") != top.id:
                st["spike"] = top.id
                alerts.append(f"📈 پست آخر کانال پربازدید شده: {top.views} بازدید (میانگین {avg:.0f}) — «{(top.raw_text or '').replace(chr(10), ' ')[:60]}»")
    finally:
        await c.disconnect()
    json.dump(st, open(STATE, "w"), ensure_ascii=False)
    # ❤️ heart challenge (flash_sale.py) runs ONLY for the Hermes brand (its sales bot). Other brands
    # skip it cleanly — no exception, no alert. A real failure is reported once per streak, not every
    # tick (it once spammed Owner every 5 min for hours on 2026-10-27 before this dedup).
    if BRAND == "hermes":
        try:
            import subprocess
            r = subprocess.run(["/usr/bin/python3", "/root/.hermes/ads/scripts/flash_sale.py", "check-challenge"],
                               capture_output=True, text=True, timeout=300)
            if "فعال شد" in r.stdout:
                alerts.append("❤️ چالش قلب‌ها به هدف رسید — جشنواره‌ی ۲۴ ساعته‌ی ۲۰٪ فعال و اعلام شد")
            st.pop("heart_err", None)          # recovered -> next failure may alert again
        except Exception as e:
            if not st.get("heart_err"):
                st["heart_err"] = True
                alerts.append(f"(بررسی چالش قلب‌ها نشد: {type(e).__name__})")
        json.dump(st, open(STATE, "w"), ensure_ascii=False)
    if alerts:
        notify("🛰 پایشگر لحظه‌ای\n\n" + "\n".join(alerts))
    return alerts


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "on":
        open(FLAG, "w").write(datetime.datetime.now().isoformat(timespec="minutes"))
        asyncio.run(tick())                      # baseline so old events are not re-sent
        print("✅ پایشگر لحظه‌ای روشن شد — هر ۵ دقیقه چک می‌کند و رویدادها را در همین چت خبر می‌دهد.")
    elif cmd == "off":
        if os.path.exists(FLAG):
            os.remove(FLAG)
        print("⏸ پایشگر لحظه‌ای خاموش شد.")
    elif cmd == "status":
        on = os.path.exists(FLAG)
        st = json.load(open(STATE)) if os.path.exists(STATE) else {}
        print(("✅ روشن" if on else "⏸ خاموش") + f" — سؤال‌های منتظر جواب: {len(st.get('pending', {}))}")
    elif cmd == "tick":
        if os.path.exists(FLAG):
            print(asyncio.run(tick()))
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
