import asyncio
import random
import sqlite3
from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command
from aiogram.types import (
    ChatMemberAdministrator,
    ChatMemberOwner,
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder

# =====================================
# НАСТРОЙКИ ENV
# =====================================
# BotHost.ru -> Переменные окружения
# TOKEN = токен бота
# ADMIN_ID = ваш Telegram ID
# CHANNEL_ID = ID канала
# CHANNEL_USERNAME = username канала без @

import os

TOKEN = os.getenv("TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME")

if not TOKEN:
    raise ValueError("TOKEN не найден в переменных окружения")

# =====================================
# БАЗА ДАННЫХ
# =====================================
conn = sqlite3.connect("ferrari_giveaway.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    balance INTEGER DEFAULT 0,
    ref_balance INTEGER DEFAULT 0,
    invited_by INTEGER DEFAULT 0,
    referrals INTEGER DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS giveaways (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stars INTEGER,
    participants TEXT,
    active INTEGER DEFAULT 1,
    winner_id INTEGER DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS withdraws (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    amount INTEGER,
    status TEXT DEFAULT 'pending'
)
""")

conn.commit()

cursor.execute('''
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
)
''')
conn.commit()

settings_defaults = {
    'ref_reward': '5',
    'refs_enabled': 'on',
    'required_channel': CHANNEL_USERNAME,
    'sponsor_channel': ''
}

for k, v in settings_defaults.items():
    cursor.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
        (k, v)
    )

conn.commit()

# =====================================
# БОТ
# =====================================
bot = Bot(
    token=TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

dp = Dispatcher(storage=MemoryStorage())

# =====================================
# СОСТОЯНИЯ
# =====================================
class GiveawayCreate(StatesGroup):
    waiting_stars = State()
    waiting_confirm = State()


class WithdrawState(StatesGroup):
    waiting_amount = State()


class AddBalanceState(StatesGroup):
    waiting_user = State()
    waiting_amount = State()

# =====================================
# ПРОВЕРКА ПОДПИСКИ
# =====================================
async def check_sub(user_id):
    try:
        member = await bot.get_chat_member(CHANNEL_ID, user_id)

        sponsor = get_setting('sponsor_channel')

        if sponsor:
            sponsor_name = sponsor.replace('https://t.me/', '').replace('@', '')

            sponsor_member = await bot.get_chat_member(f'@{sponsor_name}', user_id)

            sponsor_ok = sponsor_member.status in ["member", "administrator", "creator"]
        else:
            sponsor_ok = True

        return member.status in ["member", "administrator", "creator"] and sponsor_ok
    except:
        return False


# =====================================
# ФУНКЦИИ
# =====================================
def get_user(user_id):
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    return cursor.fetchone()


def create_user(user_id, username):
    if not get_user(user_id):
        cursor.execute(
            "INSERT INTO users (user_id, username) VALUES (?, ?)",
            (user_id, username)
        )
        conn.commit()


def get_balance(user_id):
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    return result[0] if result else 0


def get_setting(key):
    cursor.execute("SELECT value FROM settings WHERE key=?", (key,))
    result = cursor.fetchone()
    return result[0] if result else None


def set_setting(key, value):
    cursor.execute(
        "UPDATE settings SET value=? WHERE key=?",
        (value, key)
    )
    conn.commit()


def add_ref_balance(user_id, amount):
    cursor.execute(
        "UPDATE users SET ref_balance = ref_balance + ? WHERE user_id = ?",
        (amount, user_id)
    )
    conn.commit()


def add_balance(user_id, amount):
    cursor.execute(
        "UPDATE users SET balance = balance + ? WHERE user_id = ?",
        (amount, user_id)
    )
    conn.commit()


def remove_balance(user_id, amount):
    cursor.execute(
        "UPDATE users SET balance = balance - ? WHERE user_id = ?",
        (amount, user_id)
    )
    conn.commit()


# =====================================
# КНОПКИ
# =====================================
def main_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="👤 Профиль", callback_data="profile")
    return kb.as_markup()


def profile_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="💸 Вывод", callback_data="withdraw")
    return kb.as_markup()


def admin_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="🎁 Создать розыгрыш", callback_data="create_giveaway")
    kb.button(text="⭐ Начислить звезды", callback_data="add_stars")
    kb.button(text="👥 Реф система", callback_data="ref_settings")
    kb.button(text="📢 Рассылка", callback_data="mailing")
    kb.button(text="📣 Спонсоры", callback_data="sponsors")
    kb.adjust(1)
    return kb.as_markup()


# =====================================
# START
# =====================================
@dp.message(Command("start"))
async def start(message: Message):
    args = message.text.split()

    ref_id = 0

    if len(args) > 1 and args[1].startswith("ref_"):
        ref_id = int(args[1].split("_")[1])

    create_user(message.from_user.id, message.from_user.username)

    if ref_id and ref_id != message.from_user.id:
        cursor.execute(
            "SELECT invited_by FROM users WHERE user_id=?",
            (message.from_user.id,)
        )

        invited = cursor.fetchone()

        if invited and invited[0] == 0:
            cursor.execute(
                "UPDATE users SET invited_by=? WHERE user_id=?",
                (ref_id, message.from_user.id)
            )

            cursor.execute(
                "UPDATE users SET referrals = referrals + 1 WHERE user_id=?",
                (ref_id,)
            )

            if get_setting('refs_enabled') == 'on':
                reward = int(get_setting('ref_reward'))
                add_ref_balance(ref_id, reward)
            conn.commit()

            try:
                await bot.send_message(
                    ref_id,
                    "🎉 Новый реферал!
⭐ Вам начислено 5 звезд"
                )
            except:
                pass

    args = message.text.split()

    # DEEP LINK JOIN
    if len(args) > 1 and args[1].startswith("join_"):
        giveaway_id = int(args[1].split("_")[1])

        cursor.execute(
            "SELECT participants, active FROM giveaways WHERE id=?",
            (giveaway_id,)
        )

        data = cursor.fetchone()

        if not data:
            return await message.answer("❌ Розыгрыш не найден")

        participants, active = data

        if active == 0:
            return await message.answer("❌ Розыгрыш завершен")

        participants_list = participants.split(",") if participants else []

        if str(message.from_user.id) in participants_list:
            return await message.answer("❌ Вы уже участвуете")

        emojis = ["🍎", "🚗", "⭐", "🐶"]
        correct = random.choice(emojis)

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=e,
                    callback_data=f"captcha_{giveaway_id}_{correct}_{e}"
                ) for e in emojis
            ]
        ])

        return await message.answer(
            f"🤖 Пройдите капчу

"
            f"Нажмите на эмодзи: {correct}",
            reply_markup=kb
        )

    text = (
        "🏎 <b>Добро пожаловать в Ferrari Взлет!</b>

"
        "🎁 Участвуй в розыгрышах звезд
"
        "⭐ Получай награды
"
        "💸 Выводи призы подарком"
    )

    if message.from_user.id == ADMIN_ID:
        await message.answer(text, reply_markup=admin_menu())
    else:
        await message.answer(text, reply_markup=main_menu())


# =====================================
# ПРОФИЛЬ
# =====================================
@dp.callback_query(F.data == "profile")
async def profile(callback: CallbackQuery):
    balance = get_balance(callback.from_user.id)

    cursor.execute(
        "SELECT referrals FROM users WHERE user_id=?",
        (callback.from_user.id,)
    )

    refs = cursor.fetchone()[0]

    await callback.message.edit_text(
        f"👤 <b>Ваш профиль</b>\n\n"
        f"⭐ Баланс: <b>{balance}</b> звезд
"
        f"👥 Рефералов: <b>{refs}</b>",
        reply_markup=profile_menu()
    )


# =====================================
# ВЫВОД
# =====================================
@dp.callback_query(F.data == "withdraw")
async def withdraw(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "💸 Введите сумму вывода\n"
        "<i>(приз будет выдан подарком)</i>"
    )
    await state.set_state(WithdrawState.waiting_amount)


@dp.message(WithdrawState.waiting_amount)
async def process_withdraw(message: Message, state: FSMContext):
    try:
        amount = int(message.text)
    except:
        return await message.answer("❌ Введите число")

    balance = get_balance(message.from_user.id)

    if amount > balance:
        return await message.answer("❌ Недостаточно звезд")

    remove_balance(message.from_user.id, amount)

    cursor.execute(
        "INSERT INTO withdraws (user_id, amount) VALUES (?, ?)",
        (message.from_user.id, amount)
    )
    conn.commit()

    withdraw_id = cursor.lastrowid

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Подтвердить",
                callback_data=f"accept_withdraw_{withdraw_id}"
            ),
            InlineKeyboardButton(
                text="❌ Отклонить",
                callback_data=f"decline_withdraw_{withdraw_id}"
            )
        ]
    ])

    username = message.from_user.username or message.from_user.first_name

    await bot.send_message(
        ADMIN_ID,
        f"💸 <b>Новая заявка на вывод</b>\n\n"
        f"👤 Пользователь: @{username}\n"
        f"⭐ Сумма: {amount}",
        reply_markup=kb
    )

    await message.answer("✅ Заявка отправлена админу")
    await state.clear()


# =====================================
# ОБРАБОТКА ВЫВОДА
# =====================================
@dp.callback_query(F.data.startswith("accept_withdraw_"))
async def accept_withdraw(callback: CallbackQuery):
    withdraw_id = int(callback.data.split("_")[-1])

    cursor.execute(
        "UPDATE withdraws SET status='accepted' WHERE id=?",
        (withdraw_id,)
    )
    conn.commit()

    await callback.message.edit_text("✅ Вывод подтвержден")


@dp.callback_query(F.data.startswith("decline_withdraw_"))
async def decline_withdraw(callback: CallbackQuery):
    withdraw_id = int(callback.data.split("_")[-1])

    cursor.execute(
        "SELECT user_id, amount FROM withdraws WHERE id=?",
        (withdraw_id,)
    )

    data = cursor.fetchone()

    if data:
        user_id, amount = data
        add_balance(user_id, amount)

    cursor.execute(
        "UPDATE withdraws SET status='declined' WHERE id=?",
        (withdraw_id,)
    )
    conn.commit()

    await callback.message.edit_text("❌ Вывод отклонен, звезды возвращены")


# =====================================
# СОЗДАНИЕ РОЗЫГРЫША
# =====================================
@dp.callback_query(F.data == "create_giveaway")
async def create_giveaway(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return

    await callback.message.answer("⭐ Введите сумму выигрыша в звездах")
    await state.set_state(GiveawayCreate.waiting_stars)


@dp.message(GiveawayCreate.waiting_stars)
async def giveaway_stars(message: Message, state: FSMContext):
    try:
        stars = int(message.text)
    except:
        return await message.answer("❌ Введите число")

    await state.update_data(stars=stars)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_giveaway"),
            InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_giveaway")
        ]
    ])

    await message.answer(
        f"🎁 Создать розыгрыш на <b>{stars}</b> звезд?",
        reply_markup=kb
    )


@dp.callback_query(F.data == "cancel_giveaway")
async def cancel_giveaway(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Создание отменено")


@dp.callback_query(F.data == "confirm_giveaway")
async def confirm_giveaway(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    stars = data["stars"]

    cursor.execute(
        "INSERT INTO giveaways (stars, participants) VALUES (?, ?)",
        (stars, "")
    )
    conn.commit()

    giveaway_id = cursor.lastrowid

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🎉 Участвовать",
                url=f"https://t.me/{(await bot.get_me()).username}?start=join_{giveaway_id}"
            )
        ]
    ])

    await bot.send_message(
        CHANNEL_ID,
        f"🎁 <b>НОВЫЙ РОЗЫГРЫШ</b>\n\n"
        f"⭐ Приз: <b>{stars}</b> звезд\n"
        f"👥 Максимум участников: 12\n\n"
        f"Нажми кнопку ниже чтобы участвовать!",
        reply_markup=kb
    )

    await callback.message.edit_text("✅ Розыгрыш создан")
    await state.clear()


# =====================================
# УЧАСТИЕ
# =====================================
@dp.message(Command("start"))
async def join_giveaway(message: Message):
    args = message.text.split()

    if len(args) < 2 or not args[1].startswith("join_"):
        return

    create_user(message.from_user.id, message.from_user.username)

    giveaway_id = int(message.text.split("_")[1])

    cursor.execute(
        "SELECT participants, active FROM giveaways WHERE id=?",
        (giveaway_id,)
    )

    data = cursor.fetchone()

    if not data:
        return await message.answer("❌ Розыгрыш не найден")

    participants, active = data

    if active == 0:
        return await message.answer("❌ Розыгрыш завершен")

    participants_list = participants.split(",") if participants else []

    if str(message.from_user.id) in participants_list:
        return await message.answer("❌ Вы уже участвуете")

    # ПРОВЕРКА ПОДПИСКИ
    sub = await check_sub(callback.from_user.id)

    if not sub:
        kb_sub = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📢 Подписаться",
                    url=CHANNEL_USERNAME
                )
            ],
            [
                InlineKeyboardButton(
                    text="✅ Проверить",
                    callback_data=f"recheck_{giveaway_id}"
                )
            ]
        ])

        return await callback.message.answer(
            "❌ Для участия подпишитесь на канал",
            reply_markup=kb_sub
        )

    # РАНДОМ КАПЧА
    emojis = ["🍎", "🚗", "⭐", "🐶"]
    correct = random.choice(emojis)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=e, callback_data=f"captcha_{giveaway_id}_{correct}_{e}")
            for e in emojis
        ]
    ])

    await message.answer(
        f"🤖 Пройдите капчу\n\n"
        f"Нажмите на эмодзи: {correct}",
        reply_markup=kb
    )


@dp.callback_query(F.data.startswith("captcha_"))
async def captcha_check(callback: CallbackQuery):
    parts = callback.data.split("_")

    giveaway_id = int(parts[1])
    correct = parts[2]
    selected = parts[3]

    if correct != selected:
        return await callback.answer("❌ Неверно", show_alert=True)

    cursor.execute(
        "SELECT participants, stars FROM giveaways WHERE id=?",
        (giveaway_id,)
    )

    participants, stars = cursor.fetchone()

    participants_list = participants.split(",") if participants else []

    if str(callback.from_user.id) in participants_list:
        return await callback.answer("Вы уже участвуете")

    if len(participants_list) >= 12:
        return await callback.answer("❌ Лимит участников")

    participants_list.append(str(callback.from_user.id))

    cursor.execute(
        "UPDATE giveaways SET participants=? WHERE id=?",
        (",".join(participants_list), giveaway_id)
    )
    conn.commit()

    await callback.message.edit_text(
        f"✅ Вы участвуете в розыгрыше!
"
        f"👥 Участников: {len(participants_list)}/12

"
        f"🎟 Ваш номер: <b>{len(participants_list)}</b>"
    )

    # ОПРЕДЕЛЕНИЕ ПОБЕДИТЕЛЯ
    if len(participants_list) >= 12:
        dice1 = await bot.send_dice(CHANNEL_ID, emoji="🎲")
        await asyncio.sleep(4)

        dice2 = await bot.send_dice(CHANNEL_ID, emoji="🎲")
        await asyncio.sleep(4)

        total = dice1.dice.value + dice2.dice.value

        winner_index = total - 1

        if winner_index >= len(participants_list):
            winner_index = random.randint(0, len(participants_list) - 1)

        winner_id = int(participants_list[winner_index])

        add_balance(winner_id, stars)

        cursor.execute(
            "UPDATE giveaways SET active=0, winner_id=? WHERE id=?",
            (winner_id, giveaway_id)
        )
        conn.commit()

        try:
            user = await bot.get_chat(winner_id)
            username = user.username
            mention = f"@{username}" if username else user.first_name
        except:
            mention = str(winner_id)

        await bot.send_message(
            CHANNEL_ID,
            f"🏆 <b>РОЗЫГРЫШ ЗАВЕРШЕН</b>\n\n"
            f"🎲 Сумма кубиков: <b>{total}</b>\n"
            f"👑 Победитель: {mention}\n"
            f"⭐ Выигрыш: <b>{stars}</b> звезд"
        )

        await bot.send_message(
            winner_id,
            f"🎉 Поздравляем!\n\n"
            f"Вы выиграли <b>{stars}</b> звезд!"
        )


# =====================================
# РЕФ ВЫВОД
# =====================================
@dp.callback_query(F.data == "withdraw_ref")
async def withdraw_ref(callback: CallbackQuery):
    cursor.execute(
        "SELECT ref_balance FROM users WHERE user_id=?",
        (callback.from_user.id,)
    )

    ref_balance = cursor.fetchone()[0]

    if ref_balance < 100:
        return await callback.answer(
            "❌ Минимум 100 реф звезд",
            show_alert=True
        )

    cursor.execute(
        "UPDATE users SET ref_balance=0 WHERE user_id=?",
        (callback.from_user.id,)
    )
    conn.commit()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Подтвердить",
                callback_data=f"accept_ref_{callback.from_user.id}_{ref_balance}"
            ),
            InlineKeyboardButton(
                text="❌ Отклонить",
                callback_data=f"decline_ref_{callback.from_user.id}_{ref_balance}"
            )
        ]
    ])

    await bot.send_message(
        ADMIN_ID,
        f"👥 Новый вывод реф баланса

"
        f"👤 ID: {callback.from_user.id}
"
        f"⭐ Сумма: {ref_balance}",
        reply_markup=kb
    )

    await callback.answer("✅ Заявка отправлена")


# =====================================
# РЕФ НАСТРОЙКИ
# =====================================
@dp.callback_query(F.data == "ref_settings")
async def ref_settings(callback: CallbackQuery):
    status = get_setting('refs_enabled')
    reward = get_setting('ref_reward')

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🔄 Вкл/Выкл",
                callback_data="toggle_refs"
            )
        ],
        [
            InlineKeyboardButton(
                text="⭐ Изменить награду",
                callback_data="change_ref_reward"
            )
        ]
    ])

    await callback.message.answer(
        f"👥 Реф система

"
        f"📊 Статус: {status}
"
        f"⭐ Награда: {reward}",
        reply_markup=kb
    )


@dp.callback_query(F.data == "toggle_refs")
async def toggle_refs(callback: CallbackQuery):
    status = get_setting('refs_enabled')

    new_status = 'off' if status == 'on' else 'on'
    set_setting('refs_enabled', new_status)

    await callback.answer(f"Реф система: {new_status}")


# =====================================
# СПОНСОРЫ
# =====================================
@dp.callback_query(F.data == "sponsors")
async def sponsors(callback: CallbackQuery, state: FSMContext):
    sponsor = get_setting('sponsor_channel')

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="➕ Добавить/Изменить",
                callback_data="add_sponsor"
            )
        ],
        [
            InlineKeyboardButton(
                text="❌ Удалить",
                callback_data="remove_sponsor"
            )
        ]
    ])

    await callback.message.answer(
        f"📣 Текущий спонсор:
{sponsor if sponsor else 'Нет'}",
        reply_markup=kb
    )


@dp.callback_query(F.data == "add_sponsor")
async def add_sponsor(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "📣 Отправьте username канала

Пример: @ferrari_news"
    )

    await state.set_state(SponsorState.waiting_channel)


@dp.message(SponsorState.waiting_channel)
async def save_sponsor(message: Message, state: FSMContext):
    channel = message.text.strip()

    set_setting('sponsor_channel', channel)

    await message.answer(
        f"✅ Спонсор установлен:
{channel}"
    )

    await state.clear()


@dp.callback_query(F.data == "remove_sponsor")
async def remove_sponsor(callback: CallbackQuery):
    set_setting('sponsor_channel', '')

    await callback.answer(
        "❌ Спонсор удален",
        show_alert=True
    )


# =====================================
# РАССЫЛКА
# =====================================
class MailingState(StatesGroup):
    waiting_text = State()


class SponsorState(StatesGroup):
    waiting_channel = State()


@dp.callback_query(F.data == "mailing")
async def mailing(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("📢 Введите текст рассылки")
    await state.set_state(MailingState.waiting_text)


@dp.message(MailingState.waiting_text)
async def process_mailing(message: Message, state: FSMContext):
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()

    success = 0

    for user in users:
        try:
            await bot.send_message(user[0], message.text)
            success += 1
            await asyncio.sleep(0.05)
        except:
            pass

    await message.answer(
        f"✅ Рассылка завершена
"
        f"📨 Отправлено: {success}"
    )

    await state.clear()


# =====================================
# НАЧИСЛЕНИЕ ЗВЕЗД
# =====================================
@dp.callback_query(F.data == "add_stars")
async def add_stars(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return

    await callback.message.answer(
        "👤 Отправьте ID пользователя"
    )

    await state.set_state(AddBalanceState.waiting_user)


@dp.message(AddBalanceState.waiting_user)
async def add_balance_user(message: Message, state: FSMContext):
    try:
        user_id = int(message.text)
    except:
        return await message.answer("❌ Неверный ID")

    await state.update_data(user_id=user_id)
    await message.answer("⭐ Введите количество звезд")

    await state.set_state(AddBalanceState.waiting_amount)


@dp.message(AddBalanceState.waiting_amount)
async def add_balance_amount(message: Message, state: FSMContext):
    try:
        amount = int(message.text)
    except:
        return await message.answer("❌ Введите число")

    data = await state.get_data()
    user_id = data["user_id"]

    add_balance(user_id, amount)

    await message.answer("✅ Звезды начислены")

    try:
        await bot.send_message(
            user_id,
            f"⭐ Вам начислено {amount} звезд"
        )
    except:
        pass

    await state.clear()


# =====================================
# ЗАПУСК
# =====================================
async def main():
    print("Bot started...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
