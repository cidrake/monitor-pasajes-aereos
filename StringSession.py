import asyncio
from telethon.sessions import StringSession
from telethon import TelegramClient

API_ID = 37460567  # Tu API_ID
API_HASH = "bd5ba9f63a136d8186e88dbfd9d9f9ac"  # Tu API_HASH

async def main():
    async with TelegramClient(StringSession(), API_ID, API_HASH) as client:
        print("\n--- COPIA TU STRING SESSION A CONTINUACIÓN ---")
        print(client.session.save())
        print("---------------------------------------------\n")

asyncio.run(main())