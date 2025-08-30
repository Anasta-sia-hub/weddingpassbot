import os
import sqlite3
import qrcode
from aiogram import Bot, Dispatcher, executor, types
from aiogram.types import LabeledPrice, PreCheckoutQuery, ContentType, ReplyKeyboardMarkup, KeyboardButton
from datetime import datetime

# ====================
# 🔑 Настройки
# ====================
BOT_TOKEN = os.getenv("BOT_TOKEN")  # Токен бота в переменных окружения
PROVIDER_TOKEN = os.getenv("PROVIDER_TOKEN")  # Токен для оплат (ЮKassa)
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))  # Твой ID (можно вынести в переменные)
COMMISSION = 0.1  # 10% комиссия

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

# ====================
# 💾 База данных
# ====================
conn = sqlite3.connect("weddings.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS weddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    seller_id INTEGER,
    description TEXT,
    price INTEGER,
    status TEXT
)
""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wedding_id INTEGER,
    buyer_id INTEGER,
    amount INTEGER,
    commission INTEGER,
    status TEXT
)
""")
cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    agreed INTEGER DEFAULT 0,
    agreement_date TEXT
)
''')
conn.commit()

# ====================
# 📜 Оферта
# ====================
offer_text = (
    "📄 Публичная оферта\n\n"
    "Используя этого бота, вы соглашаетесь с условиями:\n\n"
    "1️⃣ Я (Агент) предоставляю сервис для продажи билетов.\n"
    "2️⃣ Комиссия сервиса — 10% от стоимости билета.\n"
    "3️⃣ Продавец получает 90% суммы.\n"
    "4️⃣ Ответственность за проведение мероприятия полностью несёт Продавец.\n"
    "5️⃣ Агент не является организатором мероприятий и не несёт ответственности за отмену.\n"
    "6️⃣ Нажатие кнопки «✅ Принять условия» означает согласие с этой офертой.\n\n"
    "👉 Полный текст доступен по ссылке: https://example.com/oferta.pdf"
)

agree_kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
agree_kb.add(types.KeyboardButton("✅ Принять условия"))

# ====================
# /start
# ====================
@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    cursor.execute("SELECT agreed FROM users WHERE user_id=?", (message.from_user.id,))
    user = cursor.fetchone()
    if user and user[0]:
        await message.answer(
            "💍 Добро пожаловать обратно!\n\nТеперь вы можете продавать (/sell) и покупать (/buylist) билеты."
        )
    else:
        await message.answer(offer_text, reply_markup=agree_kb)

# ====================
# Подтверждение оферты
# ====================
@dp.message_handler(lambda m: m.text == "✅ Принять условия")
async def agreed(message: types.Message):
    cursor.execute(
        "INSERT OR REPLACE INTO users (user_id, agreed, agreement_date) VALUES (?, ?, ?)",
        (message.from_user.id, 1, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    )
    conn.commit()
    await message.answer(
        f"✅ Спасибо! Вы приняли условия оферты {datetime.now().strftime('%d.%m.%Y %H:%M')}.\n"
        "Теперь вы можете пользоваться ботом.",
        reply_markup=types.ReplyKeyboardRemove()
    )

# ====================
# Проверка согласия
# ====================
async def check_agreement(user_id: int) -> bool:
    cursor.execute("SELECT agreed FROM users WHERE user_id=?", (user_id,))
    user = cursor.fetchone()
    return user and user[0] == 1

# ====================
# 👰 Продавец: подача заявки
# ====================
@dp.message_handler(commands=['sell'])
async def sell(message: types.Message):
    if not await check_agreement(message.from_user.id):
        await message.answer("❌ Сначала согласитесь с правилами через /start.")
        return
    await message.answer("Опиши свою свадьбу (дата, место, сколько гостей, цена за место в рублях):")

    @dp.message_handler(lambda msg: msg.chat.id == message.chat.id)
    async def get_desc(msg: types.Message):
        try:
            parts = msg.text.rsplit(" ", 1)
            description = parts[0]
            price = int(parts[1])
        except:
            await msg.answer("❌ Неправильный формат. В конце укажи цену цифрой.")
            return

        cursor.execute(
            "INSERT INTO weddings (seller_id, description, price, status) VALUES (?, ?, ?, ?)",
            (msg.from_user.id, description, price, "pending")
        )
        conn.commit()
        await msg.answer("📩 Заявка отправлена на модерацию!")
        await bot.send_message(
            ADMIN_ID,
            f"👀 Новая заявка:\n\n{description}\nЦена: {price}₽\n\n"
            f"Одобрить: /approve_{cursor.lastrowid}\nОтклонить: /reject_{cursor.lastrowid}"
        )
        dp.message_handlers.unregister(get_desc)

# ====================
# 🔎 Админ: модерация
# ====================
@dp.message_handler(lambda m: m.text and m.text.startswith("/approve_"))
async def approve(message: types.Message):
    wid = int(message.text.split("_")[1])
    cursor.execute("UPDATE weddings SET status=? WHERE id=?", ("approved", wid))
    conn.commit()
    await message.answer(f"✅ Заявка {wid} одобрена!")

@dp.message_handler(lambda m: m.text and m.text.startswith("/reject_"))
async def reject(message: types.Message):
    wid = int(message.text.split("_")[1])
    cursor.execute("UPDATE weddings SET status=? WHERE id=?", ("rejected", wid))
    conn.commit()
    await message.answer(f"❌ Заявка {wid} отклонена!")

# ====================
# 🎟 Покупатель: список
# ====================
@dp.message_handler(commands=['buylist'])
async def buylist(message: types.Message):
    if not await check_agreement(message.from_user.id):
        await message.answer("❌ Сначала согласитесь с правилами через /start.")
        return
    cursor.execute("SELECT id, description, price FROM weddings WHERE status='approved'")
    rows = cursor.fetchall()
    if not rows:
        await message.answer("😔 Пока нет доступных мероприятий.")
        return
    for row in rows:
        wid, desc, price = row
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(f"Купить за {price}₽", callback_data=f"buy_{wid}"))
        await message.answer(f"💍 Свадьба #{wid}\n\n{desc}", reply_markup=kb)

# ====================
# 💳 Оплата с эскроу
# ====================
@dp.callback_query_handler(lambda c: c.data.startswith("buy_"))
async def process_buy(call: types.CallbackQuery):
    if not await check_agreement(call.from_user.id):
        await call.message.answer("❌ Сначала согласитесь с правилами через /start.")
        return

    wid = int(call.data.split("_")[1])
    cursor.execute("SELECT description, price, seller_id FROM weddings WHERE id=?", (wid,))
    wedding = cursor.fetchone()
    if not wedding:
        await call.message.answer("Эта свадьба уже недоступна.")
        return

    desc, price, seller_id = wedding
    PRICE = [LabeledPrice(label=f"Билет на свадьбу #{wid}", amount=price * 100)]
    await bot.send_invoice(
        chat_id=call.from_user.id,
        title=f"Билет на свадьбу #{wid}",
        description=desc,
        provider_token=PROVIDER_TOKEN,
        currency="RUB",
        prices=PRICE,
        start_parameter=f"wedding-ticket-{wid}",
        payload=f"ticket-{wid}"
    )

@dp.pre_checkout_query_handler(lambda q: True)
async def checkout(pre_checkout_query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@dp.message_handler(content_types=ContentType.SUCCESSFUL_PAYMENT)
async def got_payment(message: types.Message):
    payload = message.successful_payment.invoice_payload
    wid = int(payload.split("-")[1])
    amount = message.successful_payment.total_amount // 100
    commission_amount = int(amount * COMMISSION)
    buyer_id = message.from_user.id

    cursor.execute(
        "INSERT INTO payments (wedding_id, buyer_id, amount, commission, status) VALUES (?, ?, ?, ?, ?)",
        (wid, buyer_id, amount, commission_amount, "pending")
    )
    conn.commit()

    img = qrcode.make(f"Ticket#{wid}-User{buyer_id}")
    filename = f"ticket_{wid}_{buyer_id}.png"
    img.save(filename)
    await message.answer(f"💳 Оплата принята, деньги удержаны на эскроу. Комиссия бота: {commission_amount}₽")
    await message.answer_photo(open(filename, "rb"))

    seller_amount = amount - commission_amount
    # TODO: Отправляем комиссию себе
    # TODO: Остальное отправляем продавцу через ЮKassa Payout API

# ====================
# 🔑 Админ: эскроу управление
# ====================
@dp.message_handler(lambda m: m.text.startswith("/release_"))
async def release_payment(message: types.Message):
    pid = int(message.text.split("_")[1])
    cursor.execute("SELECT wedding_id, buyer_id, amount, commission FROM payments WHERE id=? AND status='pending'", (pid,))
    payment = cursor.fetchone()
    if not payment:
        await message.answer("❌ Платёж не найден или уже обработан.")
        return
    wedding_id, buyer_id, amount, commission = payment
    cursor.execute("UPDATE payments SET status=? WHERE id=?", ("released", pid))
    conn.commit()
    await message.answer(f"💰 Платёж #{pid} переведён продавцу ({amount - commission}₽).")
    await bot.send_message(buyer_id, f"✅ Платёж #{pid} подтверждён, свадьба состоялась!")

@dp.message_handler(lambda m: m.text.startswith("/refund_"))
async def refund_payment(message: types.Message):
    pid = int(message.text.split("_")[1])
    cursor.execute("SELECT buyer_id FROM payments WHERE id=? AND status='pending'", (pid,))
    payment = cursor.fetchone()
    if not payment:
        await message.answer("❌ Платёж не найден или уже обработан.")
        return
    buyer_id = payment[0]
    cursor.execute("UPDATE payments SET status=? WHERE id=?", ("refunded", pid))
    conn.commit()
    await message.answer(f"💸 Платёж #{pid} возвращён покупателю.")
    await bot.send_message(buyer_id, f"⚠️ Платёж #{pid} возвращён, свадьба не состоялась.")

# ====================
# 🚀 Запуск
# ====================
if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
