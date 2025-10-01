import asyncio
import logging
import os
import ssl
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, Command
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, Integer, String, BigInteger, select

# === Логирование ===
logging.basicConfig(level=logging.INFO)

# === Загружаем переменные окружения ===
load_dotenv()
API_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = set(map(int, os.getenv("ADMIN_IDS", "").split(",")))

# === Настройки БД ===
DATABASE_URL = os.getenv("DATABASE_URL")  # без ?sslmode=require

# Создаём SSL-контекст для asyncpg
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"ssl": ssl_context}  # передаём SSL
)
SessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# === Настройки бота и планировщика ===
bot = Bot(token=API_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler(timezone="Asia/Almaty")

# === Модели ===
Base = declarative_base()

class Subscriber(Base):
    __tablename__ = "subscribers"
    id = Column(BigInteger, primary_key=True, unique=True, nullable=False)

class Task(Base):
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True)
    time = Column(String, nullable=False)
    message = Column(String, nullable=False)

# === Вспомогательные функции ===
async def send_task(task_message: str):
    async with SessionLocal() as session:
        subs = await session.execute(select(Subscriber))
        for sub in subs.scalars().all():
            try:
                await bot.send_message(sub.id, f"⏰ {task_message}")
            except Exception as e:
                logging.warning(f"Не удалось отправить {sub.id}: {e}")

async def schedule_existing_tasks():
    async with SessionLocal() as session:
        tasks = await session.execute(select(Task))
        for t in tasks.scalars().all():
            hour, minute = map(int, t.time.split(":"))
            scheduler.add_job(send_task, "cron", hour=hour, minute=minute, args=[t.message])

# === Команды ===
@dp.message(CommandStart())
async def start(message: types.Message):
    async with SessionLocal() as session:
        exists = await session.get(Subscriber, message.from_user.id)
        if not exists:
            session.add(Subscriber(id=message.from_user.id))
            await session.commit()
    await message.answer("✅ Ты подписан на напоминания!")

@dp.message(Command("add"))
async def add_task(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ У тебя нет прав для добавления задач.")
        return
    try:
        _, time_str, *task_text = message.text.split(" ")
        hour, minute = map(int, time_str.split(":"))
        task_message = " ".join(task_text)

        async with SessionLocal() as session:
            task = Task(time=time_str, message=task_message)
            session.add(task)
            await session.commit()

        scheduler.add_job(send_task, "cron", hour=hour, minute=minute, args=[task_message])
        await message.answer(f"✅ Задача добавлена: {time_str} → {task_message}")

    except Exception as e:
        logging.error(e)
        await message.answer("⚠️ Ошибка! Формат: `/add 10:00 текст`", parse_mode="Markdown")

@dp.message(Command("list"))
async def list_tasks(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    async with SessionLocal() as session:
        tasks = await session.execute(select(Task))
        tasks = tasks.scalars().all()
        if not tasks:
            await message.answer("📋 Нет активных задач.")
            return
        text = "📅 Список задач:\n"
        for i, t in enumerate(tasks, 1):
            text += f"{i}. {t.time} → {t.message}\n"
        await message.answer(text)

@dp.message(Command("delete"))
async def delete_task(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    try:
        _, index_str = message.text.split(" ")
        index = int(index_str) - 1

        async with SessionLocal() as session:
            tasks = await session.execute(select(Task))
            tasks = tasks.scalars().all()
            if index < 0 or index >= len(tasks):
                raise ValueError("Неверный индекс")
            task = tasks[index]
            await session.delete(task)
            await session.commit()

        await message.answer(f"🗑 Задача удалена: {task.time} → {task.message}")
    except:
        await message.answer("⚠️ Ошибка! Используй: `/delete 1`")

# === Запуск ===
async def main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await schedule_existing_tasks()
    scheduler.start()
    logging.info("✅ Бот запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
