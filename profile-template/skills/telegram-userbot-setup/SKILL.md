---
name: telegram-userbot-setup
description: "Use when the user asks whether you can access their own Telegram account — Saved Messages (پیام‌های ذخیره شده), chats, contacts, groups, channels — or wants to connect / set up / disconnect their Telegram account, or asks what is needed for that."
version: 2.0.0
author: Agent Hermes
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [Telegram, Userbot, Saved Messages, Setup]
---

# The user's own Telegram account (connect + read Saved Messages)

You CAN access the user's own Telegram account (Saved Messages, chats, contacts) once it is connected. Never say you have no access before checking.

1. Check: `/root/.hermes/tools/python-3.14.7+20260901-linux-x64/bin/python3 /root/.hermes/shared-tools/userbot/account_read.py /root/.hermes/profiles/usertemplate/userbot/usertemplate status`
2. If it prints NOT_LOGGED_IN: tell the user in one or two short sentences to open «📇 حساب تلگرام من» and tap «🔗 وصل کردن اکانت تلگرام» (premium). It needs only their phone number and the login code, takes a minute, and nothing from their chats is stored.
   - NEVER ask for api_id / api_hash, the login code or the 2FA password in this chat, and never run login scripts yourself. The button does the login securely.
3. If connected, read on demand (read-only; nothing is stored):
   - Saved Messages, newest: `... account_read.py /root/.hermes/profiles/usertemplate/userbot/usertemplate saved [n]`
   - Search Saved Messages: `... saved-search "<text>" [n]`
   - One Saved Message in full: `... saved-get <id>`
   - **Search ALL of Telegram** (public channels, groups, bots — «تو تلگرام سرچ کن / کانال‌های فلان رو پیدا کن»): `... tgsearch "<keyword>" 50`. Telegram returns ~20 per keyword, so run 3-5 different keywords (Persian AND English, e.g. github, گیت هاب, open source, repo) and merge; reply with clickable links + member counts. Never say this is impossible.
   - Recent chats: `dialogs [n]` · one chat: `history "<chat>" [n]` · contacts: `contacts [query]` · search all chats: `search "<text>" [n]`
   (`...` = the same python + account_read.py + session path as in step 1.)
4. Disconnect: tell them to tap «🔌 قطع اتصال اکانت» in «📇 حساب تلگرام من».

Never delete anything, and never send to anyone without the user's explicit request (see the `telegram-userbot` skill for sending). This session belongs only to this user — never use another profile's session path.
