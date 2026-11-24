import asyncio, json, sys
from telethon import TelegramClient

def main():
    api_id = int(sys.argv[1])
    api_hash = sys.argv[2]
    phone = sys.argv[3]
    session_path = sys.argv[4]

    async def run():
        client = TelegramClient(session_path, api_id, api_hash)
        await client.connect()
        result = await client.send_code_request(phone)
        with open(session_path + ".pending_login.json", "w") as f:
            json.dump({"phone_code_hash": result.phone_code_hash, "phone": phone,
                       "api_id": api_id, "api_hash": api_hash}, f)
        print("Code sent to your Telegram app. Tell the admin/agent the code.")
        await client.disconnect()

    asyncio.run(run())

if __name__ == "__main__":
    main()
