import asyncio, json, sys, os
from telethon import TelegramClient

def main():
    session_path = sys.argv[1]
    password = sys.argv[2]

    async def run():
        with open(session_path + ".pending_login.json") as f:
            pending = json.load(f)
        client = TelegramClient(session_path, pending["api_id"], pending["api_hash"])
        await client.connect()
        await client.sign_in(password=password)
        me = await client.get_me()
        print(f"LOGIN_OK: {me.first_name} ({me.id})")
        with open(session_path + ".creds.json", "w") as f:
            json.dump({"api_id": pending["api_id"], "api_hash": pending["api_hash"]}, f)
        await client.disconnect()
        os.remove(session_path + ".pending_login.json")

    asyncio.run(run())

if __name__ == "__main__":
    main()
