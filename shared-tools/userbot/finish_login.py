import asyncio, json, sys, os
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

def main():
    session_path = sys.argv[1]
    code = sys.argv[2]

    async def run():
        with open(session_path + ".pending_login.json") as f:
            pending = json.load(f)
        client = TelegramClient(session_path, pending["api_id"], pending["api_hash"])
        await client.connect()
        try:
            await client.sign_in(pending["phone"], code, phone_code_hash=pending["phone_code_hash"])
        except SessionPasswordNeededError:
            print("NEEDS_2FA_PASSWORD")
            await client.disconnect()
            return
        me = await client.get_me()
        print(f"LOGIN_OK: {me.first_name} ({me.id})")
        with open(session_path + ".creds.json", "w") as f:
            json.dump({"api_id": pending["api_id"], "api_hash": pending["api_hash"]}, f)
        await client.disconnect()
        os.remove(session_path + ".pending_login.json")

    asyncio.run(run())

if __name__ == "__main__":
    main()
