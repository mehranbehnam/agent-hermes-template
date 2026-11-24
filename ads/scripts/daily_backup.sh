#!/bin/bash
# Daily encrypted backup of the Agent-Hermes / HermesVPN growth setup (owner item, 2026-10-24).
# tar -> gpg (AES256, passphrase in /root/.hermes-backup-passphrase, root-only) -> Oracle /root/backups/hetzner-hermes/ (14 kept).
# Silent on success; on failure DMs Owner via the agent bot.
set -o pipefail
PASS=/root/.hermes-backup-passphrase
[ -s "$PASS" ] || { umask 077; head -c 48 /dev/urandom | base64 > "$PASS"; }
TS=$(date +%Y%m%d-%H%M)
NAME="hermes-growth-$TS.tar.gz.gpg"
OUT="/root/backups/$NAME"

fail() {
  TOK=$(grep '^TELEGRAM_BOT_TOKEN=' /root/.hermes/.env | cut -d= -f2- | tr -d "\"'")
  curl -s -o /dev/null "https://api.telegram.org/bot$TOK/sendMessage" --data-urlencode chat_id=100000001 \
       --data-urlencode "text=⚠️ بکاپ روزانه‌ی Agent-Hermes ناموفق بود: $1"
  exit 1
}

tar -czf - --ignore-failed-read --exclude='*.session-journal' --exclude='sess_*.session' --exclude='stats_session.session' \
  /root/.hermes/ads /root/.hermes/archive-admin /root/.hermes/plugins/admin-panel /root/.hermes/shared-tools/admin /root/.hermes/shared-tools/docs/docproc.py /root/.hermes/plugins/group-self-filter /root/.hermes/skills/hermes-ads-stickers /root/.hermes/config.yaml \
  /root/.hermes/profiles/adsaccount/SOUL.md /root/.hermes/profiles/adsaccount/memories /root/.hermes/profiles/adsaccount/scripts \
  /root/.hermes/profiles/adsaccount/skills/hermes-ads-stickers /root/.hermes/profiles/adsaccount/skills/hermesvpn-channel-admin \
  /root/.hermes/profiles/adsaccount/cron/jobs.json /root/.hermes/profiles/adsaccount/userbot \
  /root/.hermes/profiles/hermesgroup/SOUL.md /root/.hermes/profiles/hermesgroup/config.yaml \
  /etc/cron.d/hermes-add-members /etc/cron.d/hermes-chan-stats /etc/cron.d/hermes-live-monitor \
  /root/hermesvpn/CLAUDE.md /root/hermesvpn/HANDOFF.md /opt/n8n/privacy-site/join 2>/dev/null \
 | gpg --batch --yes --pinentry-mode loopback --passphrase-file "$PASS" --symmetric --cipher-algo AES256 -o "$OUT" \
 || fail "ساخت فایل"
chmod 600 "$OUT"

REMOTE="mkdir -p /root/backups/hetzner-hermes && cat > /root/backups/hetzner-hermes/$NAME && chmod 600 /root/backups/hetzner-hermes/$NAME && cd /root/backups/hetzner-hermes && ls -1t hermes-growth-*.gpg | tail -n +15 | xargs -r rm --"
ssh -o BatchMode=yes oracle-vpn "sudo bash -c '$REMOTE'" < "$OUT" || fail "ارسال به سرور دوم"

# keep only the 3 newest local copies
ls -1t /root/backups/hermes-growth-*.tar.gz.gpg 2>/dev/null | tail -n +4 | xargs -r rm --
