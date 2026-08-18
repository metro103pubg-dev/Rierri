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

def is_admin(user_id: int) -> bool:
    return user_id == config.ADMIN_ID

def get_post_keyboard(post_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔄 Рерайт", callback_data=f"rewrite_{post_id}"),
            InlineKeyboardButton(text="❌ В корзину", callback_data=f"skip_{post_id}")
        ]
    ])

async def send_next_post_card(chat_id: int) -> None:
    """Отправка карточки следующего отобранного поста."""
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
