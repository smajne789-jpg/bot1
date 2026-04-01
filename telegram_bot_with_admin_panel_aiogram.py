# Telegram Bot with Admin Panel (aiogram)
# Works on BotHost.ru

import asyncio
import logging
import sqlite3
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage

import os

API_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))  # your Telegram ID from env

logging.basicConfig(level=logging.INFO)

bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- Database ---
conn = sqlite3.connect("bot.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY,
    text TEXT,
    photo TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS buttons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT,
    url TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY
)
""")

conn.commit()

# default settings
cursor.execute("SELECT * FROM settings WHERE id=1")
if not cursor.fetchone():
    cursor.execute("INSERT INTO settings (id, text, photo) VALUES (1, 'Hello!', '')")
    conn.commit()

# --- FSM States ---
class AdminStates(StatesGroup):
    waiting_text = State()
    waiting_photo = State()
    button_text = State()
    button_url = State()
    broadcast = State()

# --- Keyboards ---

def admin_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Change text", callback_data="set_text")],
        [InlineKeyboardButton(text="🖼 Change image", callback_data="set_photo")],
        [InlineKeyboardButton(text="🔘 Manage buttons", callback_data="buttons")],
        [InlineKeyboardButton(text="📢 Broadcast", callback_data="broadcast")]
    ])


def buttons_kb():
    kb = []
    for row in cursor.execute("SELECT id, text FROM buttons"):
        kb.append([InlineKeyboardButton(text=row[1], callback_data=f"del_{row[0]}")])
    kb.append([InlineKeyboardButton(text="➕ Add button", callback_data="add_btn")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def user_kb():
    kb = []
    for row in cursor.execute("SELECT text, url FROM buttons"):
        kb.append([InlineKeyboardButton(text=row[0], url=row[1])])
    return InlineKeyboardMarkup(inline_keyboard=kb)

# --- Handlers ---

@dp.message(Command("start"))
async def start(message: types.Message):
    cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (message.from_user.id,))
    conn.commit()

    cursor.execute("SELECT text, photo FROM settings WHERE id=1")
    text, photo = cursor.fetchone()

    kb = user_kb()

    if photo:
        await message.answer_photo(photo=photo, caption=text, reply_markup=kb)
    else:
        await message.answer(text, reply_markup=kb)

@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer("Admin panel", reply_markup=admin_kb())

# --- Admin actions ---

@dp.callback_query(F.data == "set_text")
async def set_text(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Send new text:")
    await state.set_state(AdminStates.waiting_text)

@dp.message(AdminStates.waiting_text)
async def save_text(message: types.Message, state: FSMContext):
    cursor.execute("UPDATE settings SET text=? WHERE id=1", (message.text,))
    conn.commit()
    await message.answer("Text updated")
    await state.clear()

@dp.callback_query(F.data == "set_photo")
async def set_photo(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Send new photo:")
    await state.set_state(AdminStates.waiting_photo)

@dp.message(AdminStates.waiting_photo)
async def save_photo(message: types.Message, state: FSMContext):
    photo_id = message.photo[-1].file_id
    cursor.execute("UPDATE settings SET photo=? WHERE id=1", (photo_id,))
    conn.commit()
    await message.answer("Photo updated")
    await state.clear()

# --- Buttons ---

@dp.callback_query(F.data == "buttons")
async def manage_buttons(callback: types.CallbackQuery):
    await callback.message.answer("Manage buttons:", reply_markup=buttons_kb())

@dp.callback_query(F.data == "add_btn")
async def add_button(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Send button text:")
    await state.set_state(AdminStates.button_text)

@dp.message(AdminStates.button_text)
async def get_btn_text(message: types.Message, state: FSMContext):
    await state.update_data(text=message.text)
    await message.answer("Send button URL:")
    await state.set_state(AdminStates.button_url)

@dp.message(AdminStates.button_url)
async def save_btn(message: types.Message, state: FSMContext):
    data = await state.get_data()
    cursor.execute("INSERT INTO buttons (text, url) VALUES (?, ?)", (data['text'], message.text))
    conn.commit()
    await message.answer("Button added")
    await state.clear()

@dp.callback_query(F.data.startswith("del_"))
async def delete_btn(callback: types.CallbackQuery):
    btn_id = callback.data.split("_")[1]
    cursor.execute("DELETE FROM buttons WHERE id=?", (btn_id,))
    conn.commit()
    await callback.message.answer("Deleted")

# --- Broadcast ---

@dp.callback_query(F.data == "broadcast")
async def broadcast_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Send message for broadcast (text/photo):")
    await state.set_state(AdminStates.broadcast)

@dp.message(AdminStates.broadcast)
async def process_broadcast(message: types.Message, state: FSMContext):
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()

    for user in users:
        try:
            if message.photo:
                await bot.send_photo(user[0], photo=message.photo[-1].file_id, caption=message.caption or "")
            else:
                await bot.send_message(user[0], message.text)
        except:
            pass

    await message.answer("Broadcast sent")
    await state.clear()

# --- Run ---

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
