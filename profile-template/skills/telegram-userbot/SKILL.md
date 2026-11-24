---
name: telegram-userbot
description: "Use when the user asks you to send a Telegram message from their OWN personal account (not this bot) to someone else — phrases like 'به فلانی بگو...', 'از طرف من به ... پیام بده', 'بهش بگو ...', or 'message X for me on my account'. Also use if the user asks whether they can send messages to other people's accounts through you."
version: 1.0.0
author: Agent Hermes
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [Telegram, Messaging, Userbot, MTProto]
---

# Sending a Telegram message from the user's own account (userbot)

You DO have this capability if the user has already set up their own session (see the `telegram-userbot-setup` skill if not). Do not say you can't message other accounts — check this skill first.

Use the `terminal` tool to run:

    /root/.hermes/tools/python-3.14.7+20260901-linux-x64/bin/python3 /root/.hermes/shared-tools/userbot/send_as_user.py /root/.hermes/profiles/usertemplate/userbot/usertemplate "<username or phone or chat id>" "<text>"

Rules:
- Only send when the user names a specific recipient in that same request.
- Never send proactively, in bulk, or to anyone not named in that request —
  automated/bulk messaging from a personal account violates Telegram's terms
  and risks a permanent ban of the user's phone number.
- One explicit request = one message to the one recipient named.
- If the script errors because no session exists yet (missing .creds.json),
  switch to the `telegram-userbot-setup` skill to onboard the user first.
- If it errors because the username/phone doesn't exist, tell the user
  exactly that — don't claim you have no capability at all.
