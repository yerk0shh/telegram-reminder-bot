import asyncio
import sys
from sqlalchemy.ext.asyncio import create_async_engine

# Фикс для Windows
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

DATABASE_URL = "postgresql+asyncpg://postgres:hjKmdBocOPnjkvJLCZYoMVEXTTtmWVaV@centerbeam.proxy.rlwy.net:49743/railway"

engine = create_async_engine(DATABASE_URL, echo=True)

async def test_connection():
    try:
        async with engine.begin() as conn:
            await conn.run_sync(lambda connection: None)  # просто проверка
        print("✅ Подключение к базе успешно!")
    except Exception as e:
        print("❌ Ошибка подключения:", e)

if __name__ == "__main__":
    asyncio.run(test_connection())
