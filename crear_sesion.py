import asyncio
from telethon import TelegramClient

API_ID = 37460567      # Reemplaza por tu API ID
API_HASH = "bd5ba9f63a136d8186e88dbfd9d9f9ac"  # Reemplaza por tu API HASH

client = TelegramClient("session_monitor", API_ID, API_HASH)

async def main():
    await client.start()
    print("¡Sesión iniciada con éxito!")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())