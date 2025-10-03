import asyncio
import logging
import os
import ssl
import sys
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, Command
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, Integer, BigInteger, Boolean, String, Text, select
from dotenv import load_dotenv

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Логирование
logging.basicConfig(level=logging.INFO)
load_dotenv()

API_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(",")))
DATABASE_URL = os.getenv("DATABASE_URL")

bot = Bot(token=API_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler(timezone="Asia/Almaty")

# === Настройка базы ===
Base = declarative_base()

# SSL для Railway
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"ssl": ssl_context}
)
async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

# --- Модели ---
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False)
    is_admin = Column(Boolean, default=False)


class Subscription(Base):
    __tablename__ = "subscriptions"
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False)  # ID пользователя из users
    active = Column(Boolean, default=True)        # статус подписки


class Task(Base):
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True)
    time = Column(String(5), nullable=False)  # HH:MM
    message = Column(Text, nullable=False)


@dp.message(CommandStart())
async def start(message: types.Message):
    async with async_session() as session:
        # Проверка на существование пользователя
        result = await session.execute(select(User).where(User.telegram_id == message.from_user.id))
        user = result.scalars().first()
        if not user:
            user = User(
                telegram_id=message.from_user.id,
                is_admin=(message.from_user.id in ADMIN_IDS)
            )
            session.add(user)
            await session.commit()

        # Проверка на подписку
        result = await session.execute(select(Subscription).where(Subscription.user_id == message.from_user.id))
        sub = result.scalars().first()
        if not sub:
            session.add(Subscription(user_id=message.from_user.id, active=True))
            await session.commit()

    await message.answer("✅ Ты подписан на напоминания!")


# === /add ===
@dp.message(Command("add"))
async def add_task(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ У тебя нет прав.")
        return

    try:
        _, time_str, task_message = message.text.split(" ", 2)
        hour, minute = map(int, time_str.split(":"))

        async with async_session() as session:
            session.add(Task(time=time_str, message=task_message))
            await session.commit()

        # Планировщик
        async def task():
            async with async_session() as session:
                users = await session.execute(select(User.telegram_id))
                for (telegram_id,) in users:
                    await bot.send_message(telegram_id, f"⏰ {task_message}")

        scheduler.add_job(task, "cron", hour=hour, minute=minute)
        await message.answer(f"✅ Задача добавлена: {time_str} → {task_message}")

    except Exception as e:
        logging.error(e)
        await message.answer("⚠️ Ошибка! Формат: `/add 10:00 текст`", parse_mode="Markdown")


@dp.message(Command("unsubscribe"))
async def unsubscribe(message: types.Message):
    async with async_session() as session:
        result = await session.execute(select(Subscription).where(Subscription.user_id == message.from_user.id))
        sub = result.scalars().first()
        if sub:
            sub.active = False
            await session.commit()
            await message.answer("❌ Ты отписался от напоминаний.")
        else:
            await message.answer("⚠️ У тебя нет активной подписки.")


# === /list ===
@dp.message(Command("list"))
async def list_tasks(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    async with async_session() as session:
        result = await session.execute(select(Task))
        tasks = result.scalars().all()
        if not tasks:
            await message.answer("📋 Нет активных задач.")
            return
        text = "📅 Список задач:\n"
        for i, t in enumerate(tasks, 1):
            text += f"{i}. {t.time} → {t.message}\n"
        await message.answer(text)


# === /delete ===
@dp.message(Command("delete"))
async def delete_task(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    try:
        _, index_str = message.text.split(" ")
        index = int(index_str)

        async with async_session() as session:
            result = await session.execute(select(Task))
            tasks = result.scalars().all()
            if index < 1 or index > len(tasks):
                await message.answer("⚠️ Нет такой задачи.")
                return
            task = tasks[index - 1]
            await session.delete(task)
            await session.commit()
            await message.answer(f"🗑 Удалена задача: {task.time} → {task.message}")

    except Exception as e:
        logging.error(e)
        await message.answer("⚠️ Ошибка! Используй: `/delete 1`")


# === Поднять таблицы + загрузить задачи из базы ===
async def load_tasks():
    async with async_session() as session:
        result = await session.execute(select(Task))
        tasks = result.scalars().all()
        for task in tasks:
            hour, minute = map(int, task.time.split(":"))

            async def job(message=task.message):
                users = await session.execute(select(User.telegram_id))
                for (telegram_id,) in users:
                    await bot.send_message(telegram_id, f"⏰ {message}")

            scheduler.add_job(job, "cron", hour=hour, minute=minute)
        logging.info(f"Загружено {len(tasks)} задач из базы")


# === Запуск ===
async def main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await load_tasks()
    scheduler.start()
    logging.info("✅ Бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
