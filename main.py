from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta
from html import escape

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton,
                           InlineKeyboardMarkup, InlineKeyboardButton, BotCommand)
from dotenv import load_dotenv

from funpay_medik.database import (init_db, upsert_user, save_session, get_user,
                                    set_setting, get_setting)
from funpay_medik.funpay_client import verify_token, get_profile, get_lots

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("funpay-medik")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    raise RuntimeError("Укажи BOT_TOKEN в .env")
if not os.getenv("AUTH_ENCRYPTION_KEY", "").strip():
    raise RuntimeError("Укажи AUTH_ENCRYPTION_KEY в .env")

bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
auth_wait: set[int] = set()
price_wait: set[int] = set()

MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📊 Профиль"), KeyboardButton(text="💸 Товары")],
        [KeyboardButton(text="📈 Статистика"), KeyboardButton(text="⚡ Уведомления")],
    ], resize_keyboard=True, is_persistent=True, input_field_placeholder="Выберите раздел…"
)

def auth_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔐 Войти в FunPay", callback_data="auth_begin")],
        [InlineKeyboardButton(text="Отмена", callback_data="auth_cancel")]
    ])

def settings_kb(price_on: bool, order_on: bool):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📉 Мониторинг цен: {'✅' if price_on else '❌'}", callback_data="toggle_price")],
        [InlineKeyboardButton(text=f"⏰ Напоминание о подтверждении: {'✅' if order_on else '❌'}", callback_data="toggle_order")],
        [InlineKeyboardButton(text="Обновить", callback_data="settings_refresh")]
    ])

async def require_auth(message: Message) -> dict | None:
    user = await get_user(message.from_user.id)
    if not user or not user.get("funpay_token"):
        await message.answer("🔒 Сначала подключите FunPay через /auth. Без авторизации разделы аккаунта недоступны.", reply_markup=auth_kb())
        return None
    return user

@dp.message(CommandStart())
async def start(message: Message):
    await upsert_user(message.from_user.id, message.from_user.full_name or message.from_user.username or "")
    await message.answer(
        "👋 <b>FunPay Medik</b> — помощник для управления магазином FunPay.\n\n"
        "📊 /profile — профиль и баланс\n"
        "💸 /products — ваши товары и слоты\n"
        "📈 /stats — статистика продаж\n"
        "⚡ /notifications — настройки уведомлений\n"
        "🔐 /auth или /login — подключить FunPay\n"
        "📉 /auto-price — мониторинг рыночных цен\n"
        "⏰ /auto-otvet — напоминание покупателю\n"
        "🧾 /auto-expose — мастер подготовки лота\n"
        "❔ /help — все команды и подсказки\n\n"
        "Выберите раздел кнопками внизу. Для начала подключите аккаунт FunPay.",
        reply_markup=MENU
    )

@dp.message(Command("help"))
async def help_cmd(message: Message):
    await message.answer(
        "<b>Команды FunPay Medik</b>\n"
        "/start — запуск и главное меню\n"
        "/auth, /login — безопасное подключение FunPay по golden_key\n"
        "/profile — имя, баланс и данные профиля\n"
        "/products — список ваших лотов (если доступен в версии API)\n"
        "/stats — сводка; неподдерживаемые метрики отмечаются отдельно\n"
        "/notifications — включение и выключение уведомлений\n"
        "/auto-price — выбрать категорию для мониторинга цен\n"
        "/auto-otvet — настройка напоминаний о подтверждении заказа\n"
        "/auto-expose — подготовка заголовка/описания/цены лота\n"
        "/cancel — отменить текущий сценарий\n\n"
        "Авторизация нужна для команд, работающих с вашим аккаунтом."
    )

@dp.message(Command("auth", "login"))
async def auth_cmd(message: Message):
    await upsert_user(message.from_user.id, message.from_user.full_name or "")
    auth_wait.add(message.from_user.id)
    await message.answer(
        "🔐 <b>Подключение FunPay</b>\n\n"
        "Отправьте сюда ваш <code>golden_key</code> отдельным сообщением. "
        "Он будет зашифрован перед сохранением в локальную базу бота. "
        "Не отправляйте ключ в групповые чаты. После проверки сообщение с ключом будет удалено, если Telegram разрешит.",
        reply_markup=auth_kb()
    )

@dp.callback_query(F.data == "auth_begin")
async def auth_begin(call: CallbackQuery):
    auth_wait.add(call.from_user.id)
    await call.message.answer("Пришлите golden_key FunPay одним сообщением. Для отмены: /cancel.")
    await call.answer()

@dp.callback_query(F.data == "auth_cancel")
async def auth_cancel(call: CallbackQuery):
    auth_wait.discard(call.from_user.id)
    await call.message.edit_text("Авторизация отменена.")
    await call.answer()

@dp.message(Command("cancel"))
async def cancel(message: Message):
    auth_wait.discard(message.from_user.id)
    price_wait.discard(message.from_user.id)
    await message.answer("Текущий сценарий отменён.", reply_markup=MENU)

@dp.message(lambda m: m.from_user and m.from_user.id in auth_wait)
async def auth_token(message: Message):
    token = (message.text or "").strip()
    if not token or len(token) < 20:
        await message.answer("Похоже, это не golden_key. Отправьте ключ текстом или /cancel.")
        return
    auth_wait.discard(message.from_user.id)
    try:
        ok, username, uid = await verify_token(token)
        if not ok:
            await message.answer("❌ FunPay не подтвердил сессию. Проверьте golden_key и попробуйте /auth ещё раз.")
            return
        await upsert_user(message.from_user.id, message.from_user.full_name or "")
        await save_session(message.from_user.id, token, username, uid)
        await message.answer(f"✅ FunPay подключён: <b>{escape(username)}</b>\nКлюч сохранён в зашифрованном виде.", reply_markup=MENU)
    finally:
        try:
            await message.delete()
        except Exception:
            pass

@dp.message(Command("profile"))
@dp.message(F.text == "📊 Профиль")
async def profile(message: Message):
    user = await require_auth(message)
    if not user: return
    try:
        p = await get_profile(user["funpay_token"])
        link = f'<a href="{escape(p.profile_url)}">{escape(p.username)}</a>' if p.profile_url else escape(p.username)
        await message.answer(
            "📊 <b>Ваш профиль</b>\n"
            f"👤 Telegram: {escape(user.get('telegram_name') or 'не найдено')}\n"
            f"🎮 FunPay: {link}\n"
            f"💰 Баланс: <b>{escape(p.balance)}</b>\n"
            f"🛒 Продаж: <b>{p.sales}</b>\n"
            f"📦 Активных слотов: <b>{p.active_lots if p.active_lots else 'не удалось получить'}</b>\n"
            f"💎 Тариф: <b>{escape(user.get('plan') or 'Обычный')}</b>"
        )
    except Exception:
        await message.answer("⚠️ Не удалось получить профиль. Попробуйте переподключить FunPay через /auth.")

@dp.message(Command("products"))
@dp.message(F.text == "💸 Товары")
async def products(message: Message):
    user = await require_auth(message)
    if not user: return
    try:
        lots = await get_lots(user["funpay_token"])
        if not lots:
            await message.answer("📦 Не удалось получить список лотов через установленную версию FunPayAPI или активных лотов нет.")
            return
        lines = ["💸 <b>Ваши товары</b>"]
        for lot in lots[:30]:
            title = escape(str(getattr(lot, "title", None) or getattr(lot, "description", None) or "Лот"))
            price = getattr(lot, "price", None)
            lines.append(f"• {title} — {escape(str(price)) + ' ₽' if price is not None else 'цена не найдена'}")
        await message.answer("\n".join(lines))
    except Exception:
        await message.answer("⚠️ Не получилось загрузить лоты. Проверьте сессию FunPay.")

@dp.message(Command("stats"))
@dp.message(F.text == "📈 Статистика")
async def stats(message: Message):
    user = await require_auth(message)
    if not user: return
    await message.answer(
        "📈 <b>Статистика</b>\n"
        "Периоды: день / неделя / месяц.\n"
        "Пока FunPayAPI не предоставил боту подтверждённую историю транзакций для вашего аккаунта, "
        "суммы заработка, отзывы и топ товаров не рассчитываются — вместо этого показывать выдуманные числа было бы неправильно.\n"
        "График будет строиться после подключения проверенного источника истории продаж."
    )

@dp.message(Command("notifications"))
@dp.message(F.text == "⚡ Уведомления")
async def notifications(message: Message):
    user = await require_auth(message)
    if not user: return
    price = await get_setting(message.from_user.id, "price_notifications")
    order = await get_setting(message.from_user.id, "order_reminders")
    await message.answer("⚡ <b>Настройки уведомлений</b>\nВключайте только нужные функции:", reply_markup=settings_kb(price == "1", order == "1"))

@dp.callback_query(F.data.in_({"toggle_price","toggle_order","settings_refresh"}))
async def settings_callback(call: CallbackQuery):
    user = await get_user(call.from_user.id)
    if not user or not user.get("funpay_token"):
        await call.answer("Сначала подключите FunPay через /auth", show_alert=True); return
    if call.data == "toggle_price":
        old = await get_setting(call.from_user.id,"price_notifications")
        await set_setting(call.from_user.id,"price_notifications","0" if old == "1" else "1")
    elif call.data == "toggle_order":
        old = await get_setting(call.from_user.id,"order_reminders")
        await set_setting(call.from_user.id,"order_reminders","0" if old == "1" else "1")
    price = await get_setting(call.from_user.id,"price_notifications")
    order = await get_setting(call.from_user.id,"order_reminders")
    await call.message.edit_reply_markup(reply_markup=settings_kb(price=="1",order=="1"))
    await call.answer("Настройки сохранены")

@dp.message(Command("auto-price"))
async def auto_price(message: Message):
    user = await require_auth(message)
    if not user: return
    price_wait.add(message.from_user.id)
    await message.answer(
        "📉 <b>Мониторинг цен</b>\n"
        "Напишите название категории или товара FunPay (например: Roblox, Steam, Telegram, PUBG).\n"
        "После выбора можно будет задать нижнюю и верхнюю границы цены. "
        "Проверка каждые 15 минут включится только после подтверждения.\n\n"
        "Важно: сбор средних/минимальных/максимальных цен и автоизменение лота пока отключены, "
        "пока не подключён проверенный источник рыночных предложений.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Отмена",callback_data="price_cancel")]])
    )

@dp.callback_query(F.data == "price_cancel")
async def price_cancel(call: CallbackQuery):
    price_wait.discard(call.from_user.id)
    await call.message.edit_text("Мониторинг цен не изменён.")
    await call.answer()

@dp.message(lambda m: m.from_user and m.from_user.id in price_wait)
async def price_category(message: Message):
    category=(message.text or "").strip()
    if not category: return
    price_wait.discard(message.from_user.id)
    await message.answer(
        f"Категория для отслеживания: <b>{escape(category)}</b>.\n"
        "Для запуска мониторинга нужен адаптер рыночных предложений FunPay для этой категории. "
        "Сейчас он не подключён, поэтому бот не будет присылать фиктивные цены или менять ваш лот."
    )

@dp.message(Command("auto-otvet"))
async def auto_reply(message: Message):
    user=await require_auth(message)
    if not user: return
    old=await get_setting(message.from_user.id,"order_reminders")
    new="0" if old=="1" else "1"
    await set_setting(message.from_user.id,"order_reminders",new)
    await message.answer(
        "⏰ Напоминания покупателям: <b>"+("включены" if new=="1" else "выключены")+"</b>.\n"
        "Интервал по задумке — через 1 час после оплаты. Для отправки напоминания требуется надёжное получение событий и статусов заказов; "
        "в текущей сборке переключатель сохраняется, но отправка ещё не активирована."
    )

@dp.message(Command("auto-expose"))
async def auto_expose(message: Message):
    user=await require_auth(message)
    if not user: return
    await message.answer(
        "🧾 <b>Мастер подготовки лота</b>\n"
        "Автопубликация нескольких слотов пока не включена: перед публикацией необходимо проверить актуальные методы создания лотов FunPayAPI.\n"
        "Могу подготовить черновик заголовка, описания и цены, но бот не будет публиковать лоты без подтверждённого API и вашего подтверждения."
    )

@dp.message(F.text)
async def menu_fallback(message: Message):
    if message.text in {"📊 Профиль","💸 Товары","📈 Статистика","⚡ Уведомления"}:
        return
    await message.answer("Не понял команду. Нажмите /help, чтобы посмотреть список команд.")

async def main():
    await init_db()
    await bot.set_my_commands([
        BotCommand(command="start",description="Запустить бота и открыть меню"),
        BotCommand(command="help",description="Список команд и подсказки"),
        BotCommand(command="auth",description="Подключить аккаунт FunPay"),
        BotCommand(command="profile",description="Профиль и баланс FunPay"),
        BotCommand(command="products",description="Ваши выставленные товары"),
        BotCommand(command="stats",description="Статистика магазина"),
        BotCommand(command="notifications",description="Настройки уведомлений"),
        BotCommand(command="auto-price",description="Настроить мониторинг цен"),
        BotCommand(command="auto-otvet",description="Напоминания о подтверждении заказа"),
        BotCommand(command="auto-expose",description="Подготовить новый лот"),
        BotCommand(command="cancel",description="Отменить текущий сценарий"),
    ])
    log.info("FunPay Medik started")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
