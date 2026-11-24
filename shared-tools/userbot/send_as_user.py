import asyncio, sys, json
from telethon import TelegramClient

def main():
    session_path = sys.argv[1]
    target = sys.argv[2]
    text = sys.argv[3]
    # Public channel/group posts must pass the public text guard (owner, 2026-10-24).
    if target.lstrip("@").lower() in ("your_channel", "your_group") or target.startswith("-100"):
        sys.path.insert(0, "/root/.hermes/ads/scripts")
        from public_text_guard import check
        problems = check(text)
        if problems:
            print("BLOCKED by public text guard (nothing sent): " + "; ".join(problems))
            sys.exit(3)

    async def run():
        with open(session_path + ".creds.json") as f:
            creds = json.load(f)
        client = TelegramClient(session_path, creds["api_id"], creds["api_hash"])
        await client.connect()
        entity = await client.get_entity(target)
        await client.send_message(entity, text)
        print("SENT")
        await client.disconnect()

    asyncio.run(run())

if __name__ == "__main__":
    main()
