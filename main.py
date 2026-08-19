import asyncio
import html
import json
import logging
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode

from config import config
import database as db
import parser
import analyzer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=config.TG_BOT_TOKEN)
dp = Dispatcher()
router = Router()

REWRITE_CACHE = {}

def get_post_keyboard(post_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💼 Эксперт", callback_data=f"rw_{post_id}_expert"),
            InlineKeyboardButton(text="⚡️ TL;DR", callback_data=f"rw_{post_id}_tldr")
        ],
        [
            InlineKeyboardButton(text="🔥 Дерзкий", callback_data=f"rw_{post_id}_provocative"),
            InlineKeyboardButton(text="🧵 Гайд", callback_data=f"rw_{post_id}_guide")
        ],
        [
            InlineKeyboardButton(text="❌ В корзину", callback_data=f"skip_{post_id}")
        ]
    ])

def get_publish_keyboard(post_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📢 Опубликовать в канал", callback_data=f"pub_{post_id}")
        ],
        [
            InlineKeyboardButton(text="🔄 Другой стиль", callback_data=f"back_{post_id}"),
            InlineKeyboardButton(text="⏭ Следующий пост", callback_data=f"next_{post_id}")
        ]
    ])

async def send_next_post_card(chat_id: int) -> None:
    chosen_posts = await db.get_chosen_posts()
    if not chosen_posts:
        await bot.send_message(
            chat_id, 
            "🎉 <b>Все отобранные посты обработаны!</b>", 
            parse_mode=ParseMode.HTML
        )
        return

    post = chosen_posts[0]
    main_idea = "Не указана"
    why = "Не указано"
    if post.get("ai_analysis"):
        try:
            ai_data = json.loads(post["ai_analysis"])
            main_idea = ai_data.get("main_idea", main_idea)
            why = ai_data.get("why", why)
        except Exception:
            pass

    channel_user = post.get("channel_username") or ""
    channel_name = post.get("channel_title") or channel_user or "Канал"
    msg_id = post.get("msg_id")
    post_link = f"https://t.me/{channel_user}/{msg_id}" if channel_user and msg_id else ""
    link_html = f"🔗 <b>Оригинал:</b> <a href='{post_link}'>Открыть пост</a>\n" if post_link else ""

    clean_text = html.escape(post["text"])
    if len(clean_text) > 800:
        clean_text = clean_text[:800] + "...\n<i>(текст сокращен)</i>"

    card_text = (
        f"📌 <b>Пост #{post['id']}</b>\n"
        f"📢 <b>Канал:</b> {html.escape(str(channel_name))} (@{channel_user})\n"
        f"📊 <b>ER:</b> {post['er']:.2f}%\n"
        f"💡 <b>Суть:</b> {html.escape(str(main_idea))}\n"
        f"❓ <b>Почему выбран:</b> {html.escape(str(why))}\n"
        f"{link_html}\n"
        f"📝 <b>Текст поста:</b>\n{clean_text}\n\n"
        f"👇 <b>Выберите стиль рерайта:</b>"
    )

    await bot.send_message(
        chat_id,
        card_text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_post_keyboard(post['id']),
        disable_web_page_preview=False
    )

@router.message(Command("start"))
async def cmd_start(message: Message):
    if not await db.is_user_authorized(message.from_user.id):
        return

    is_owner = (message.from_user.id == config.ADMIN_ID)
    
    welcome_text = (
        "🤖 <b>Панель управления ИИ-Куратором</b>\n\n"
        "<b>Работа с контентом:</b>\n"
        "➕ <code>/add_channel &lt;username&gt;</code> — добавить канал\n"
        "🗑 <code>/del_channel &lt;username&gt;</code> — удалить канал\n"
        "📋 <code>/channels</code> — список каналов\n"
        "📢 <code>/set_channel &lt;@username&gt;</code> — канал для публикаций\n"
        "🚀 <code>/start_parsing</code> — запустить парсинг вручную\n"
    )

    if is_owner:
        welcome_text += (
            "\n👑 <b>Управление доступом (для Владельца):</b>\n"
            "👤 <code>/add_admin &lt;ID&gt;</code> — выдать доступ\n"
            "❌ <code>/del_admin &lt;ID&gt;</code> — забрать доступ\n"
            "👥 <code>/admins</code> — список админов\n"
        )

    await message.answer(welcome_text, parse_mode=ParseMode.HTML)

@router.message(Command("add_admin"))
async def cmd_add_admin(message: Message, command: CommandObject):
    if message.from_user.id != config.ADMIN_ID:
        return

    if not command.args or not command.args.strip().isdigit():
        await message.answer("⚠️ Пример: <code>/add_admin 123456789</code>", parse_mode=ParseMode.HTML)
        return

    new_admin_id = int(command.args.strip())
    success = await db.add_admin(new_admin_id)
    if success:
        await message.answer(f"✅ Пользователю <code>{new_admin_id}</code> выдан доступ к боту!", parse_mode=ParseMode.HTML)
    else:
        await message.answer("ℹ️ У этого пользователя уже есть доступ.", parse_mode=ParseMode.HTML)

@router.message(Command("del_admin"))
async def cmd_del_admin(message: Message, command: CommandObject):
    if message.from_user.id != config.ADMIN_ID:
        return

    if not command.args or not command.args.strip().isdigit():
        await message.answer("⚠️ Пример: <code>/del_admin 123456789</code>", parse_mode=ParseMode.HTML)
        return

    admin_to_del = int(command.args.strip())
    success = await db.delete_admin(admin_to_del)
    if success:
        await message.answer(f"🗑 Доступ для пользователя <code>{admin_to_del}</code> аннулирован.", parse_mode=ParseMode.HTML)
    else:
        await message.answer("❌ Пользователь не найден в списке админов.", parse_mode=ParseMode.HTML)

@router.message(Command("admins"))
async def cmd_list_admins(message: Message):
    if message.from_user.id != config.ADMIN_ID:
        return

    admins = await db.get_admins()
    text = f"👑 <b>Главный владелец:</b> <code>{config.ADMIN_ID}</code>\n\n"
    if admins:
        text += "👥 <b>Дополнительные админы:</b>\n"
        for idx, adm_id in enumerate(admins, start=1):
            text += f"{idx}. <code>{adm_id}</code>\n"
    else:
        text += "👥 Дополнительных администраторов пока нет."

    await message.answer(text, parse_mode=ParseMode.HTML)

@router.message(Command("set_channel"))
async def cmd_set_channel(message: Message, command: CommandObject):
    if not await db.is_user_authorized(message.from_user.id):
        return

    if not command.args:
        curr = await db.get_setting("target_channel") or config.TARGET_CHANNEL or "не задан"
        await message.answer(f"📢 Канал для публикаций: <b>{curr}</b>\n\nИзменить: <code>/set_channel @my_channel</code>", parse_mode=ParseMode.HTML)
        return

    target = command.args.strip()
    await db.set_setting("target_channel", target)
    await message.answer(f"✅ Канал для публикаций установлен: <b>{html.escape(target)}</b>", parse_mode=ParseMode.HTML)

@router.message(Command("channels"))
async def cmd_list_channels(message: Message):
    if not await db.is_user_authorized(message.from_user.id):
        return

    channels = await db.get_channels()
    if not channels:
        await message.answer("📭 Список каналов пуст. Добавьте: <code>/add_channel username</code>", parse_mode=ParseMode.HTML)
        return

    text = "📋 <b>Отслеживаемые каналы:</b>\n\n"
    for idx, ch in enumerate(channels, start=1):
        title = ch.get("title") or ch.get("username")
        text += f"{idx}. <b>{html.escape(str(title))}</b> — <code>@{html.escape(ch['username'])}</code>\n"
    await message.answer(text, parse_mode=ParseMode.HTML)

@router.message(Command("add_channel"))
async def cmd_add_channel(message: Message, command: CommandObject):
    if not await db.is_user_authorized(message.from_user.id):
        return
    if not command.args:
        await message.answer("⚠️ Пример: <code>/add_channel durov</code>", parse_mode=ParseMode.HTML)
        return

    username = command.args.strip()
    success = await db.add_channel(username)
    if success:
        await message.answer(f"✅ Канал <b>@{html.escape(username)}</b> добавлен!", parse_mode=ParseMode.HTML)
    else:
        await message.answer(f"ℹ️ Канал <b>@{html.escape(username)}</b> уже есть в базе.", parse_mode=ParseMode.HTML)

@router.message(Command("del_channel"))
async def cmd_del_channel(message: Message, command: CommandObject):
    if not await db.is_user_authorized(message.from_user.id):
        return
    if not command.args:
        await message.answer("⚠️ Пример: <code>/del_channel durov</code>", parse_mode=ParseMode.HTML)
        return

    username = command.args.strip()
    success = await db.delete_channel(username)
    if success:
        await message.answer(f"🗑 Канал <b>@{html.escape(username)}</b> удален!", parse_mode=ParseMode.HTML)
    else:
        await message.answer(f"❌ Канал <b>@{html.escape(username)}</b> не найден.", parse_mode=ParseMode.HTML)

@router.message(Command("start_parsing"))
async def cmd_start_parsing(message: Message):
    if not await db.is_user_authorized(message.from_user.id):
        return

    status_msg = await message.answer("🔄 <b>Поиск новых постов...</b>", parse_mode=ParseMode.HTML)
    await parser.run_parser()
    await status_msg.edit_text("🧠 <b>ИИ-отбор контента...</b>", parse_mode=ParseMode.HTML)
    await analyzer.process_new_posts()
    await status_msg.delete()
    await send_next_post_card(message.chat.id)

@router.callback_query(F.data.startswith("rw_"))
async def handle_rewrite_style(callback: CallbackQuery):
    if not await db.is_user_authorized(callback.from_user.id):
        return

    parts = callback.data.split("_")
    post_id = int(parts[1])
    style = parts[2]

    style_names = {
        "expert": "💼 Экспертный",
        "tldr": "⚡️ TL;DR",
        "provocative": "🔥 Дерзкий",
        "guide": "🧵 Гайд"
    }

    await callback.answer(f"⏳ Генерирую стиль: {style_names.get(style, '')}...")

    post = await db.get_post_by_id(post_id)
    if not post:
        await callback.message.answer("❌ Пост не найден.")
        return

    rewritten_text = await analyzer.rewrite_post(post["text"], style=style)
    REWRITE_CACHE[post_id] = rewritten_text

    result_text = f"✨ <b>Готовый пост ({style_names.get(style, '')}):</b>\n\n{html.escape(rewritten_text)}"

    await callback.message.answer(
        result_text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_publish_keyboard(post_id)
    )

@router.callback_query(F.data.startswith("pub_"))
async def handle_publish(callback: CallbackQuery):
    if not await db.is_user_authorized(callback.from_user.id):
        return

    post_id = int(callback.data.split("_")[1])
    text_to_publish = REWRITE_CACHE.get(post_id)

    target_channel = await db.get_setting("target_channel") or config.TARGET_CHANNEL
    if not target_channel:
        await callback.answer("⚠️ Канал не привязан! Используйте /set_channel @username", show_alert=True)
        return

    if not text_to_publish:
        await callback.answer("❌ Текст устарел. Сделайте рерайт заново.", show_alert=True)
        return

    try:
        await bot.send_message(chat_id=target_channel, text=text_to_publish, parse_mode=ParseMode.HTML)
        await db.update_post_status(post_id, "published")
        await callback.answer("🎉 Опубликовано в канал!", show_alert=True)
        await callback.message.edit_reply_markup(reply_markup=None)
        await send_next_post_card(callback.message.chat.id)
    except Exception as e:
        await callback.answer(f"❌ Ошибка: {e}", show_alert=True)

@router.callback_query(F.data.startswith("back_"))
async def handle_back_to_styles(callback: CallbackQuery):
    post_id = int(callback.data.split("_")[1])
    await callback.message.edit_reply_markup(reply_markup=get_post_keyboard(post_id))

@router.callback_query(F.data.startswith("next_") | F.data.startswith("skip_"))
async def handle_skip_next(callback: CallbackQuery):
    if not await db.is_user_authorized(callback.from_user.id):
        return

    post_id = int(callback.data.split("_")[1])
    await db.update_post_status(post_id, "skipped")
    await callback.answer("Пост пропущен")
    try:
        await callback.message.delete()
    except Exception:
        pass
    await send_next_post_card(callback.message.chat.id)

async def auto_parser_loop():
    """Фоновый автопарсинг каждые 4 часа."""
    while True:
        await asyncio.sleep(4 * 3600)
        try:
            new_parsed = await parser.run_parser()
            if new_parsed > 0:
                await analyzer.process_new_posts()
                chosen = await db.get_chosen_posts()
                if chosen and config.ADMIN_ID:
                    await bot.send_message(
                        config.ADMIN_ID,
                        f"🔔 <b>Автопарсинг:</b> Найдено <b>{len(chosen)}</b> новых постов!\nОтправьте <code>/start_parsing</code> для просмотра.",
                        parse_mode=ParseMode.HTML
                    )
        except Exception as e:
            logger.error(f"Ошибка в автопарсинге: {e}")

async def main():
    logger.info("Инициализация базы данных...")
    await db.init_db()

    dp.include_router(router)
    asyncio.create_task(auto_parser_loop())

    logger.info("Запуск Telegram-бота...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())        await bot.send_message(
            chat_id, 
            "🎉 <b>Все отобранные посты обработаны!</b>", 
            parse_mode=ParseMode.HTML
        )
        return

    post = chosen_posts[0]
    
    main_idea = "Не указана"
    why = "Не указано"
    if post.get("ai_analysis"):
        try:
            ai_data = json.loads(post["ai_analysis"])
            main_idea = ai_data.get("main_idea", main_idea)
            why = ai_data.get("why", why)
        except Exception:
            pass

    channel_name = post.get("channel_title") or post.get("channel_username") or "Канал"
    clean_text = html.escape(post["text"])
    if len(clean_text) > 1500:
        clean_text = clean_text[:1500] + "...\n<i>(текст сокращен)</i>"

    card_text = (
        f"📌 <b>Пост #{post['id']}</b>\n"
        f"📢 <b>Канал:</b> {html.escape(str(channel_name))} (@{post.get('channel_username')})\n"
        f"📊 <b>ER:</b> {post['er']:.2f}%\n"
        f"💡 <b>Суть:</b> {html.escape(str(main_idea))}\n"
        f"❓ <b>Почему выбран:</b> {html.escape(str(why))}\n\n"
        f"📝 <b>Оригинальный текст:</b>\n{clean_text}"
    )

    await bot.send_message(
        chat_id,
        card_text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_post_keyboard(post['id'])
    )

@router.message(Command("start"))
async def cmd_start(message: Message):
    if not is_admin(message.from_user.id):
        return

    welcome_text = (
        "🤖 <b>Приветствую, Администратор!</b>\n\n"
        "Я — ИИ-Куратор контента. Помогаю парсить, анализировать и рерайтить лучшие посты.\n\n"
        "<b>Доступные команды:</b>\n"
        "➕ <code>/add_channel &lt;username&gt;</code> — добавить канал для мониторинга\n"
        "🚀 <code>/start_parsing</code> — запустить сбор, фильтрацию и ревью постов"
    )
    await message.answer(welcome_text, parse_mode=ParseMode.HTML)

@router.message(Command("add_channel"))
async def cmd_add_channel(message: Message, command: CommandObject):
    if not is_admin(message.from_user.id):
        return

    if not command.args:
        await message.answer(
            "⚠️ Укажите username канала.\nПример: <code>/add_channel durov</code>",
            parse_mode=ParseMode.HTML
        )
        return

    username = command.args.strip()
    success = await db.add_channel(username)
    if success:
        await message.answer(f"✅ Канал <b>@{html.escape(username)}</b> успешно добавлен!", parse_mode=ParseMode.HTML)
    else:
        await message.answer(f"ℹ️ Канал <b>@{html.escape(username)}</b> уже есть в базе.", parse_mode=ParseMode.HTML)

@router.message(Command("start_parsing"))
async def cmd_start_parsing(message: Message):
    if not is_admin(message.from_user.id):
        return

    status_msg = await message.answer("🔄 <b>Запуск парсера...</b> Сбор свежих постов...", parse_mode=ParseMode.HTML)
    
    # 1. Парсинг постов через Telethon
    parsed_count = await parser.run_parser()
    
    # 2. ИИ-анализ через Gemini
    await status_msg.edit_text("🧠 <b>Парсинг окончен!</b> ИИ-анализ постов...", parse_mode=ParseMode.HTML)
    processed_count = await analyzer.process_new_posts()
    
    await status_msg.edit_text("✅ <b>Анализ завершен!</b> Подготовка карточек...", parse_mode=ParseMode.HTML)
    
    # 3. Отправка первой карточки
    await send_next_post_card(message.chat.id)

@router.callback_query(F.data.startswith("rewrite_"))
async def handle_rewrite(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    post_id = int(callback.data.split("_")[1])
    await callback.answer("⏳ Создаю рерайт через ИИ...")

    post = await db.get_post_by_id(post_id)
    if not post:
        await callback.message.answer("❌ Пост не найден в базе.")
        return

    rewritten_text = await analyzer.rewrite_post(post["text"])
    await db.update_post_status(post_id, "rewritten")

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        f"✨ <b>Готовый рерайт поста #{post_id}:</b>\n\n{html.escape(rewritten_text)}",
        parse_mode=ParseMode.HTML
    )

    await send_next_post_card(callback.message.chat.id)

@router.callback_query(F.data.startswith("skip_"))
async def handle_skip(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    post_id = int(callback.data.split("_")[1])
    await callback.answer("Пост пропущен")

    await db.update_post_status(post_id, "skipped")
    await callback.message.edit_text(f"❌ <b>Пост #{post_id} отправлен в корзину.</b>", parse_mode=ParseMode.HTML)

    await send_next_post_card(callback.message.chat.id)

async def main():
    logger.info("Инициализация базы данных...")
    await db.init_db()

    dp.include_router(router)
    
    logger.info("Запуск Telegram-бота...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
