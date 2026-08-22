import os
import asyncio
import html
import json
import logging
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, FSInputFile
)
from aiogram.enums import ParseMode

from config import config
import database as db
import parser
import analyzer
import webserver

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=config.TG_BOT_TOKEN)
dp = Dispatcher()
router = Router()

REWRITE_CACHE = {}
CUSTOM_TEXT_CACHE = {}
CUSTOM_PUB_CACHE = {}

PRESET_MEDIA = {
    "vc": {"name": "VC.ru", "url": "https://vc.ru/rss", "cat": "Бизнес & Стартапы"},
    "habr": {"name": "Хабр", "url": "https://habr.com/ru/rss/all/all/", "cat": "IT & Технологии"},
    "rbc": {"name": "РБК", "url": "https://rssexport.rbc.ru/rbcnews/news/30/full.rss", "cat": "Главные новости"},
    "forbes": {"name": "Forbes", "url": "https://www.forbes.ru/rss.xml", "cat": "Бизнес & Финансы"},
    "tproger": {"name": "Tproger", "url": "https://tproger.ru/feed/", "cat": "Разработка & AI"},
    "techcrunch": {"name": "TechCrunch", "url": "https://techcrunch.com/feed/", "cat": "Мировые IT & AI"},
    "kommersant": {"name": "Коммерсантъ", "url": "https://www.kommersant.ru/RSS/news.xml", "cat": "Экономика"},
    "3dnews": {"name": "3DNews", "url": "https://3dnews.ru/news/rss/", "cat": "Гаджеты & Техника"}
}

def get_main_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🚀 Запустить парсинг")],
            [KeyboardButton(text="📱 ТГ-каналы"), KeyboardButton(text="📰 СМИ и Сайты")],
            [KeyboardButton(text="📢 Канал для постинга"), KeyboardButton(text="⚙️ Лимит постов")],
            [KeyboardButton(text="👥 Админы")]
        ],
        resize_keyboard=True
    )

def get_parse_modes_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚡️ Всё вместе (ТГ + СМИ)", callback_data="p_mode_all")],
        [
            InlineKeyboardButton(text="📱 Только ТГ-каналы", callback_data="p_mode_tg"),
            InlineKeyboardButton(text="📰 Только СМИ", callback_data="p_mode_media")
        ]
    ])

def get_media_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚡️ Каталог популярных СМИ", callback_data="media_catalog")],
        [InlineKeyboardButton(text="📋 Мои подключенные СМИ", callback_data="media_my_list")]
    ])

def get_media_catalog_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    row = []
    for key, data in PRESET_MEDIA.items():
        row.append(InlineKeyboardButton(text=f"➕ {data['name']}", callback_data=f"addpreset_{key}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="media_back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_post_keyboard(post_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔥 Дерзкий / Шок", callback_data=f"rw_{post_id}_provocative"),
            InlineKeyboardButton(text="🎭 Юмор / Мем", callback_data=f"rw_{post_id}_humor")
        ],
        [
            InlineKeyboardButton(text="⚡️ TL;DR (Выжимка)", callback_data=f"rw_{post_id}_tldr"),
            InlineKeyboardButton(text="💼 Эксперт", callback_data=f"rw_{post_id}_expert")
        ],
        [
            InlineKeyboardButton(text="❌ В корзину", callback_data=f"skip_{post_id}")
        ]
    ])

def get_publish_keyboard(post_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Опубликовать в канал", callback_data=f"pub_{post_id}")],
        [
            InlineKeyboardButton(text="🔄 Другой стиль", callback_data=f"back_{post_id}"),
            InlineKeyboardButton(text="⏭ Следующий пост", callback_data=f"next_{post_id}")
        ]
    ])

def get_custom_text_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔥 Дерзкий / Шок", callback_data="crw_provocative"),
            InlineKeyboardButton(text="🎭 Юмор / Мем", callback_data="crw_humor")
        ],
        [
            InlineKeyboardButton(text="⚡️ TL;DR (Выжимка)", callback_data="crw_tldr"),
            InlineKeyboardButton(text="💼 Эксперт", callback_data="crw_expert")
        ]
    ])

def get_custom_publish_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Опубликовать в канал", callback_data="cpub_send")],
        [InlineKeyboardButton(text="🔄 Другой стиль", callback_data="cback_styles")]
    ])

async def send_next_post_card(chat_id: int) -> None:
    chosen_posts = await db.get_chosen_posts()
    if not chosen_posts:
        await bot.send_message(
            chat_id, 
            "🎉 <b>Все отобранные материалы обработаны!</b>", 
            parse_mode=ParseMode.HTML
        )
        return

    post = chosen_posts[0]
    total_left = len(chosen_posts)
    
    main_idea = "Не указана"
    why = "Не указано"
    if post.get("ai_analysis"):
        try:
            ai_data = json.loads(post["ai_analysis"])
            main_idea = ai_data.get("main_idea", main_idea)
            why = ai_data.get("why", why)
        except Exception:
            pass

    source_type = post.get("source_type", "tg")
    source_name = post.get("source_name") or post.get("channel_title") or post.get("channel_username") or "Источник"
    post_url = post.get("post_url") or ""
    media_path = post.get("media_path")
    
    type_badge = "📱 <b>ТГ-Канал:</b>" if source_type == "tg" else "📰 <b>СМИ / Сайт:</b>"
    link_html = f"🔗 <b>Оригинал:</b> <a href='{post_url}'>Перейти к первоисточнику</a>\n" if post_url else ""

    clean_text = html.escape(post["text"])
    if len(clean_text) > 800:
        clean_text = clean_text[:800] + "...\n<i>(текст сокращен)</i>"

    card_text = (
        f"📌 <b>Материал #{post['id']}</b>  <i>(В очереди: {total_left})</i>\n"
        f"{type_badge} {html.escape(str(source_name))}\n"
        f"📊 <b>ER / Резонанс:</b> {post['er']:.2f}%\n"
        f"💡 <b>Суть:</b> {html.escape(str(main_idea))}\n"
        f"❓ <b>Почему взлетит:</b> {html.escape(str(why))}\n"
        f"{link_html}\n"
        f"📝 <b>Исходный текст:</b>\n{clean_text}\n\n"
        f"👇 <b>В каком стиле сделать рерайт?</b>"
    )

    # Если есть скачанное фото — отправляем с красивой картинкой
    if media_path and os.path.exists(media_path):
        photo_file = FSInputFile(media_path)
        if len(card_text) <= 1024:
            await bot.send_photo(chat_id, photo=photo_file, caption=card_text, parse_mode=ParseMode.HTML, reply_markup=get_post_keyboard(post['id']))
        else:
            await bot.send_photo(chat_id, photo=photo_file)
            await bot.send_message(chat_id, card_text, parse_mode=ParseMode.HTML, reply_markup=get_post_keyboard(post['id']), disable_web_page_preview=False)
    else:
        await bot.send_message(chat_id, card_text, parse_mode=ParseMode.HTML, reply_markup=get_post_keyboard(post['id']), disable_web_page_preview=False)

@router.message(Command("start"))
@router.message(F.text == "🔙 Главное меню")
async def cmd_start(message: Message):
    if not await db.is_user_authorized(message.from_user.id):
        return

    is_owner = (message.from_user.id == config.ADMIN_ID)
    welcome_text = (
        "🤖 <b>ИИ-Куратор: Новости, Шок-контент, Мемы и Vision</b>\n\n"
        "Используйте кнопки меню внизу для управления или просто <b>перешлите любой текст/мем</b> для мгновенного рерайта!"
    )
    if is_owner:
        welcome_text += "\n\n👑 <i>Режим Главного владельца активен.</i>"

    await message.answer(welcome_text, parse_mode=ParseMode.HTML, reply_markup=get_main_reply_keyboard())

# --- Лимит постов ---

@router.message(F.text == "⚙️ Лимит постов")
@router.message(Command("limit", "set_limit"))
async def cmd_set_limit(message: Message, command: CommandObject = None):
    if not await db.is_user_authorized(message.from_user.id):
        return

    if command and command.args:
        raw_val = command.args.strip()
        if raw_val.isdigit():
            num = int(raw_val)
            if 1 <= num <= 150:
                await db.set_setting("parse_limit", str(num))
                await message.answer(f"✅ <b>Лимит парсинга установлен:</b> <code>{num}</code> постов с источника (макс. 150).", parse_mode=ParseMode.HTML)
                return
            else:
                await message.answer("⚠️ Число должно быть в диапазоне от <b>1 до 150</b>.", parse_mode=ParseMode.HTML)
                return

    curr_limit = await db.get_setting("parse_limit") or "20"
    await message.answer(
        f"⚙️ <b>Текущий лимит парсинга:</b> <code>{curr_limit}</code> постов с источника.\n\n"
        f"Чтобы изменить, отправьте команду:\n<code>/limit 67</code> или <code>/limit 100</code>\n"
        f"<i>(Диапазон: от 1 до 150 постов)</i>",
        parse_mode=ParseMode.HTML
    )

# --- Режимы парсинга ---

@router.message(F.text == "🚀 Запустить парсинг")
async def menu_parse_modes(message: Message):
    if not await db.is_user_authorized(message.from_user.id):
        return
    curr_limit = await db.get_setting("parse_limit") or "20"
    await message.answer(
        f"🎯 <b>Выберите режим парсинга:</b>\n<i>(Сбор по <b>{curr_limit}</b> постов с источника)</i>", 
        parse_mode=ParseMode.HTML, 
        reply_markup=get_parse_modes_keyboard()
    )

@router.callback_query(F.data.startswith("p_mode_"))
async def handle_parse_mode_selected(callback: CallbackQuery):
    if not await db.is_user_authorized(callback.from_user.id):
        return

    mode = callback.data.replace("p_mode_", "")
    mode_names = {"all": "ТГ-каналов и СМИ", "tg": "ТГ-каналов", "media": "СМИ и сайтов"}
    
    limit_str = await db.get_setting("parse_limit") or "20"
    limit = int(limit_str) if limit_str.isdigit() else 20

    status_msg = await callback.message.answer(f"🔄 <b>Сбор свежих постов и фото (по {limit} шт.) из {mode_names.get(mode)}...</b>", parse_mode=ParseMode.HTML)
    
    await parser.run_parser(mode=mode, limit=limit)
    await status_msg.edit_text("🧠 <b>ИИ с Vision анализирует текст и картинки...</b>", parse_mode=ParseMode.HTML)
    await analyzer.process_new_posts()
    await status_msg.delete()
    
    await send_next_post_card(callback.message.chat.id)

# --- СМИ и сайты ---

@router.message(F.text == "📰 СМИ и Сайты")
async def menu_media(message: Message):
    if not await db.is_user_authorized(message.from_user.id):
        return
    await message.answer("📰 <b>Управление СМИ и сайтами</b>\n\nДобавьте популярные СМИ в 1 клик из каталога или подключите свой RSS:\n<code>/add_site Название https://site.ru/rss</code>", parse_mode=ParseMode.HTML, reply_markup=get_media_menu_keyboard())

@router.callback_query(F.data == "media_catalog")
async def handle_media_catalog(callback: CallbackQuery):
    await callback.message.edit_text("⚡️ <b>Каталог популярных СМИ:</b>", parse_mode=ParseMode.HTML, reply_markup=get_media_catalog_keyboard())

@router.callback_query(F.data.startswith("addpreset_"))
async def handle_add_preset_media(callback: CallbackQuery):
    key = callback.data.replace("addpreset_", "")
    data = PRESET_MEDIA.get(key)
    if not data:
        return
    success = await db.add_media_source(name=data["name"], url=data["url"], category=data["cat"])
    if success:
        await callback.answer(f"✅ {data['name']} добавлен в мониторинг!", show_alert=True)
    else:
        await callback.answer(f"ℹ️ {data['name']} уже есть в вашем списке.", show_alert=True)

@router.callback_query(F.data == "media_my_list")
async def handle_media_my_list(callback: CallbackQuery):
    sources = await db.get_media_sources()
    if not sources:
        await callback.message.edit_text("📭 У вас пока нет подключенных СМИ.\nВыберите из каталога выше!", parse_mode=ParseMode.HTML, reply_markup=get_media_catalog_keyboard())
        return
    text = "📋 <b>Ваши подключенные СМИ:</b>\n\n"
    for idx, s in enumerate(sources, start=1):
        text += f"{idx}. <b>{html.escape(s['name'])}</b>\n🔗 <code>{html.escape(s['url'])}</code>\n\n"
    text += "<i>Чтобы удалить:</i> <code>/del_site URL</code>"
    await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=get_media_menu_keyboard())

@router.callback_query(F.data == "media_back")
async def handle_media_back(callback: CallbackQuery):
    await callback.message.edit_text("📰 <b>Управление СМИ и сайтами:</b>", parse_mode=ParseMode.HTML, reply_markup=get_media_menu_keyboard())

@router.message(Command("add_site"))
async def cmd_add_site(message: Message, command: CommandObject):
    if not await db.is_user_authorized(message.from_user.id):
        return
    if not command.args or len(command.args.split()) < 2:
        await message.answer("⚠️ Пример: <code>/add_site Хабр https://habr.com/ru/rss/all/all/</code>", parse_mode=ParseMode.HTML)
        return
    parts = command.args.split(maxsplit=1)
    name = parts[0].strip()
    url = parts[1].strip()
    success = await db.add_media_source(name, url, "Свой сайт")
    if success:
        await message.answer(f"✅ Сайт <b>{html.escape(name)}</b> добавлен!", parse_mode=ParseMode.HTML)
    else:
        await message.answer("ℹ️ Этот RSS-поток уже есть в списке.", parse_mode=ParseMode.HTML)

@router.message(Command("del_site"))
async def cmd_del_site(message: Message, command: CommandObject):
    if not await db.is_user_authorized(message.from_user.id):
        return
    if not command.args:
        await message.answer("⚠️ Пример: <code>/del_site https://site.ru/rss</code>", parse_mode=ParseMode.HTML)
        return
    url = command.args.strip()
    success = await db.delete_media_source(url)
    if success:
        await message.answer("🗑 Источник удален!", parse_mode=ParseMode.HTML)
    else:
        await message.answer("❌ Источник не найден.", parse_mode=ParseMode.HTML)

# --- ТГ-каналы ---

@router.message(F.text == "📱 ТГ-каналы")
@router.message(Command("channels"))
async def menu_tg_channels(message: Message):
    if not await db.is_user_authorized(message.from_user.id):
        return
    channels = await db.get_channels()
    if not channels:
        await message.answer("📭 Список каналов пуст.\nДобавьте: <code>/add_channel username</code>", parse_mode=ParseMode.HTML)
        return
    text = "📱 <b>Отслеживаемые Telegram-каналы:</b>\n\n"
    for idx, ch in enumerate(channels, start=1):
        title = ch.get("title") or ch.get("username")
        text += f"{idx}. <b>{html.escape(str(title))}</b> — <code>@{html.escape(ch['username'])}</code>\n"
    text += "\n➕ <code>/add_channel username</code> | 🗑 <code>/del_channel username</code>"
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

# --- Канал для постинга ---

@router.message(F.text == "📢 Канал для постинга")
@router.message(Command("set_channel"))
async def menu_set_channel(message: Message, command: CommandObject = None):
    if not await db.is_user_authorized(message.from_user.id):
        return
    if command and command.args:
        target = command.args.strip()
        await db.set_setting("target_channel", target)
        await message.answer(f"✅ Канал для публикаций установлен: <b>{html.escape(target)}</b>", parse_mode=ParseMode.HTML)
        return
    curr = await db.get_setting("target_channel") or config.TARGET_CHANNEL or "не задан"
    await message.answer(f"📢 <b>Канал для публикаций:</b> <code>{curr}</code>\n\nЧтобы изменить:\n<code>/set_channel @my_channel</code>", parse_mode=ParseMode.HTML)

# --- Админы ---

@router.message(F.text == "👥 Админы")
@router.message(Command("admins"))
async def menu_admins(message: Message):
    if message.from_user.id != config.ADMIN_ID:
        return
    admins = await db.get_admins()
    text = f"👑 <b>Главный владелец:</b> <code>{config.ADMIN_ID}</code>\n\n"
    if admins:
        text += "👥 <b>Дополнительные админы:</b>\n"
        for idx, adm_id in enumerate(admins, start=1):
            text += f"{idx}. <code>{adm_id}</code>\n"
    else:
        text += "👥 Дополнительных админов пока нет.\n"
    text += "\n➕ <code>/add_admin ID</code> | 🗑 <code>/del_admin ID</code>"
    await message.answer(text, parse_mode=ParseMode.HTML)

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
        await message.answer(f"✅ Пользователю <code>{new_admin_id}</code> выдан доступ!", parse_mode=ParseMode.HTML)
    else:
        await message.answer("ℹ️ У пользователя уже есть доступ.", parse_mode=ParseMode.HTML)

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
        await message.answer(f"🗑 Доступ для <code>{admin_to_del}</code> аннулирован.", parse_mode=ParseMode.HTML)
    else:
        await message.answer("❌ Пользователь не найден.", parse_mode=ParseMode.HTML)

# --- Рерайт своего текста ---

@router.message(F.text & ~F.text.startswith("/") & ~F.text.in_({"🚀 Запустить парсинг", "📱 ТГ-каналы", "📰 СМИ и Сайты", "📢 Канал для постинга", "⚙️ Лимит постов", "👥 Админы", "🔙 Главное меню"}))
async def handle_custom_user_text(message: Message):
    if not await db.is_user_authorized(message.from_user.id):
        return
    CUSTOM_TEXT_CACHE[message.from_user.id] = message.text
    preview_len = len(message.text)
    await message.answer(f"📝 <b>Текст/мем принят ({preview_len} симв.)!</b>\n\n👇 Выберите стиль:", parse_mode=ParseMode.HTML, reply_markup=get_custom_text_keyboard())

@router.callback_query(F.data.startswith("crw_"))
async def handle_custom_rewrite(callback: CallbackQuery):
    if not await db.is_user_authorized(callback.from_user.id):
        return
    style = callback.data.split("_")[1]
    style_names = {"provocative": "🔥 Дерзкий / Шок", "humor": "🎭 Юмор / Мем", "tldr": "⚡️ TL;DR", "expert": "💼 Эксперт"}
    text = CUSTOM_TEXT_CACHE.get(callback.from_user.id)
    if not text:
        await callback.answer("❌ Текст устарел, отправьте заново.", show_alert=True)
        return
    await callback.answer(f"⏳ Пишу в стиле: {style_names.get(style, '')}...")
    rewritten_text = await analyzer.rewrite_post(text, style=style)
    CUSTOM_PUB_CACHE[callback.from_user.id] = rewritten_text
    result_text = f"✨ <b>Готовый пост ({style_names.get(style, '')}):</b>\n\n{html.escape(rewritten_text)}"
    await callback.message.answer(result_text, parse_mode=ParseMode.HTML, reply_markup=get_custom_publish_keyboard())

@router.callback_query(F.data == "cpub_send")
async def handle_custom_publish(callback: CallbackQuery):
    if not await db.is_user_authorized(callback.from_user.id):
        return
    text_to_publish = CUSTOM_PUB_CACHE.get(callback.from_user.id)
    target_channel = await db.get_setting("target_channel") or config.TARGET_CHANNEL
    if not target_channel:
        await callback.answer("⚠️ Канал не привязан! /set_channel @channel", show_alert=True)
        return
    if not text_to_publish:
        await callback.answer("❌ Текст устарел.", show_alert=True)
        return
    try:
        await bot.send_message(chat_id=target_channel, text=text_to_publish, parse_mode=ParseMode.HTML)
        await callback.answer("🎉 Пост опубликован в канал!", show_alert=True)
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception as e:
        await callback.answer(f"❌ Ошибка публикации: {e}", show_alert=True)

@router.callback_query(F.data == "cback_styles")
async def handle_custom_back(callback: CallbackQuery):
    await callback.message.edit_reply_markup(reply_markup=get_custom_text_keyboard())

# --- Обработка очереди постов ---

@router.callback_query(F.data.startswith("rw_"))
async def handle_rewrite_style(callback: CallbackQuery):
    if not await db.is_user_authorized(callback.from_user.id):
        return

    parts = callback.data.split("_")
    post_id = int(parts[1])
    style = parts[2]
    style_names = {"provocative": "🔥 Дерзкий / Шок", "humor": "🎭 Юмор / Мем", "tldr": "⚡️ TL;DR", "expert": "💼 Эксперт"}

    await callback.answer(f"⏳ Генерирую с Vision: {style_names.get(style, '')}...")
    post = await db.get_post_by_id(post_id)
    if not post:
        await callback.message.answer("❌ Пост не найден.")
        return

    # Передаем путь к скачанной картинке в Gemini Vision
    media_path = post.get("media_path")
    rewritten_text = await analyzer.rewrite_post(post["text"], style=style, image_path=media_path)
    
    REWRITE_CACHE[post_id] = {
        "text": rewritten_text,
        "media_path": media_path
    }
    await db.update_post_status(post_id, "rewritten")

    result_text = f"✨ <b>Готовый пост ({style_names.get(style, '')}):</b>\n\n{html.escape(rewritten_text)}"
    
    # Отправляем готовый пост вместе с исходным фото (если есть)
    if media_path and os.path.exists(media_path):
        photo_file = FSInputFile(media_path)
        if len(result_text) <= 1024:
            await callback.message.answer_photo(photo=photo_file, caption=result_text, parse_mode=ParseMode.HTML, reply_markup=get_publish_keyboard(post_id))
        else:
            await callback.message.answer_photo(photo=photo_file)
            await callback.message.answer(result_text, parse_mode=ParseMode.HTML, reply_markup=get_publish_keyboard(post_id))
    else:
        await callback.message.answer(result_text, parse_mode=ParseMode.HTML, reply_markup=get_publish_keyboard(post_id))

@router.callback_query(F.data.startswith("pub_"))
async def handle_publish(callback: CallbackQuery):
    if not await db.is_user_authorized(callback.from_user.id):
        return

    post_id = int(callback.data.split("_")[1])
    pub_data = REWRITE_CACHE.get(post_id)
    target_channel = await db.get_setting("target_channel") or config.TARGET_CHANNEL

    if not target_channel:
        await callback.answer("⚠️ Канал не привязан! /set_channel @channel", show_alert=True)
        return
    if not pub_data:
        await callback.answer("❌ Текст устарел.", show_alert=True)
        return

    text_to_publish = pub_data.get("text", "")
    media_path = pub_data.get("media_path")

    try:
        if media_path and os.path.exists(media_path):
            photo_file = FSInputFile(media_path)
            if len(text_to_publish) <= 1024:
                await bot.send_photo(chat_id=target_channel, photo=photo_file, caption=text_to_publish, parse_mode=ParseMode.HTML)
            else:
                await bot.send_photo(chat_id=target_channel, photo=photo_file)
                await bot.send_message(chat_id=target_channel, text=text_to_publish, parse_mode=ParseMode.HTML)
        else:
            await bot.send_message(chat_id=target_channel, text=text_to_publish, parse_mode=ParseMode.HTML)

        await db.update_post_status(post_id, "published")
        await callback.answer("🎉 Опубликовано в канал вместе с фото!", show_alert=True)
        await callback.message.edit_reply_markup(reply_markup=None)
        await send_next_post_card(callback.message.chat.id)
    except Exception as e:
        await callback.answer(f"❌ Ошибка: {e}", show_alert=True)

@router.callback_query(F.data.startswith("back_"))
async def handle_back_to_styles(callback: CallbackQuery):
    post_id = int(callback.data.split("_")[1])
    await db.update_post_status(post_id, "chosen")
    await callback.message.edit_reply_markup(reply_markup=get_post_keyboard(post_id))

@router.callback_query(F.data.startswith("next_") | F.data.startswith("skip_"))
async def handle_skip_next(callback: CallbackQuery):
    if not await db.is_user_authorized(callback.from_user.id):
        return

    post_id = int(callback.data.split("_")[1])
    await db.update_post_status(post_id, "skipped")
    await callback.answer("Пост пропущен, следующий...")
    try:
        await callback.message.delete()
    except Exception:
        pass
    await send_next_post_card(callback.message.chat.id)

# --- Фоновый автопарсинг ---

async def auto_parser_loop():
    while True:
        await asyncio.sleep(4 * 3600)
        try:
            limit_str = await db.get_setting("parse_limit") or "20"
            limit = int(limit_str) if limit_str.isdigit() else 20
            new_parsed = await parser.run_parser(mode="all", limit=limit)
            if new_parsed > 0:
                await analyzer.process_new_posts()
                chosen = await db.get_chosen_posts()
                if chosen and config.ADMIN_ID:
                    await bot.send_message(
                        config.ADMIN_ID,
                        f"🔔 <b>Автопарсинг:</b> Найдено <b>{len(chosen)}</b> новых материалов (ТГ + СМИ + Мемы + Vision)!\nНажмите «🚀 Запустить парсинг» для просмотра.",
                        parse_mode=ParseMode.HTML
                    )
        except Exception as e:
            logger.error(f"Ошибка автопарсинга: {e}")

async def main():
    logger.info("Инициализация базы данных...")
    await db.init_db()

    dp.include_router(router)
    asyncio.create_task(auto_parser_loop())
    
    try:
        await webserver.start_webserver()
        logger.info("Веб-сервер запущен!")
    except Exception as e:
        logger.warning(f"Ошибка веб-сервера: {e}")

    logger.info("Запуск Telegram-бота...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
