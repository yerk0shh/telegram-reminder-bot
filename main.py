import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, Command
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import os
from dotenv import load_dotenv

# Логирование
logging.basicConfig(level=logging.INFO)

# Загружаем токен
load_dotenv()
API_TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(token=API_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler(timezone="Asia/Almaty")

# Подписчики (в будущем заменить на базу)
subscribers = set()

# Список задач (для примера в памяти)
tasks = []

# 🔑 Администраторы (можно расширить список)
ADMINS = {827961067}

# === /start ===
@dp.message(CommandStart())
async def start(message: types.Message):
    subscribers.add(message.from_user.id)
    await message.answer("✅ Ты подписан на напоминания!")

# === /add ===
@dp.message(Command("add"))
async def add_task(message: types.Message):
    if message.from_user.id not in ADMINS:
        await message.answer("⛔ У тебя нет прав для добавления задач.")
        return

    try:
        _, time_str, *task_text = message.text.split(" ")
        hour, minute = map(int, time_str.split(":"))
        task_message = " ".join(task_text)

        # Создаём задачу
        async def task():
            for user_id in subscribers:
                await bot.send_message(user_id, f"⏰ {task_message}")

        job = scheduler.add_job(task, "cron", hour=hour, minute=minute)
        tasks.append({"time": time_str, "message": task_message, "job": job})

        await message.answer(f"✅ Задача добавлена: {time_str} → {task_message}")

    except Exception as e:
        logging.error(e)
        await message.answer("⚠️ Ошибка! Формат: `/add 10:00 текст`", parse_mode="Markdown")

# === /list ===
@dp.message(Command("list"))
async def list_tasks(message: types.Message):
    if message.from_user.id not in ADMINS:
        return
    if not tasks:
        await message.answer("📋 Нет активных задач.")
        return
    text = "📅 Список задач:\n"
    for i, t in enumerate(tasks, 1):
        text += f"{i}. {t['time']} → {t['message']}\n"
    await message.answer(text)

# === /delete ===
@dp.message(Command("delete"))
async def delete_task(message: types.Message):
    if message.from_user.id not in ADMINS:
        return
    try:
        _, index_str = message.text.split(" ")
        index = int(index_str) - 1
        task = tasks.pop(index)
        task["job"].remove()
        await message.answer(f"🗑 Задача удалена: {task['time']} → {task['message']}")
    except:
        await message.answer("⚠️ Ошибка! Используй: `/delete 1`")

# === Запуск ===
async def main():
    scheduler.start()
    logging.info("✅ Бот запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
