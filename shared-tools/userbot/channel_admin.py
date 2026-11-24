import asyncio, sys, json
from telethon import TelegramClient
from telethon.tl.functions.messages import UpdatePinnedMessageRequest, DeleteMessagesRequest
from telethon.tl.functions.channels import GetFullChannelRequest

def main():
    session_path = sys.argv[1]
    action = sys.argv[2]
    target = sys.argv[3]
    extra = sys.argv[4] if len(sys.argv) > 4 else None

    async def run():
        with open(session_path + ".creds.json") as f:
            creds = json.load(f)
        client = TelegramClient(session_path, creds["api_id"], creds["api_hash"])
        await client.connect()
        entity = await client.get_entity(target)

        if action == "pin":
            await client(UpdatePinnedMessageRequest(peer=entity, id=int(extra)))
            print("PINNED")
        elif action == "unpin":
            await client(UpdatePinnedMessageRequest(peer=entity, id=int(extra), unpin=True))
            print("UNPINNED")
        elif action == "delete":
            await client.delete_messages(entity, [int(extra)])
            print("DELETED")
        elif action == "stats":
            full = await client(GetFullChannelRequest(entity))
            print(f"members: {full.full_chat.participants_count}")
            print(f"title: {entity.title}")
        else:
            print("UNKNOWN_ACTION")
        await client.disconnect()

    asyncio.run(run())

if __name__ == "__main__":
    main()
