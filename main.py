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
