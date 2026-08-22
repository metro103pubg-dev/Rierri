import os
import re
import logging
import httpx
import feedparser
from telethon import TelegramClient
from telethon.sessions import StringSession
from config import config
import database as db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Папка для загрузки фото для Vision
os.makedirs("downloads", exist_ok=True)

def clean_html_tags(raw_html: str) -> str:
    clean = re.compile('<.*?>')
    text = re.sub(clean, '', raw_html)
    return ' '.join(text.split())

async def parse_tg_channels(limit: int = 20) -> int:
    """Парсинг постов с автоматическим скачиванием фото для Gemini Vision."""
    channels = await db.get_channels()
    if not channels:
        return 0

    session_str = config.TELETHON_SESSION.strip()
    if session_str:
        client = TelegramClient(StringSession(session_str), config.API_ID, config.API_HASH)
    else:
        client = TelegramClient('userbot_session', config.API_ID, config.API_HASH)

    await client.connect()
    if not await client.is_user_authorized():
        await client.start()

    parsed_count = 0
    for channel in channels:
        try:
            username = channel['username']
            entity = await client.get_entity(username)
            channel_title = getattr(entity, 'title', username)
            await db.update_channel_title(channel['id'], channel_title)

            messages = await client.get_messages(entity, limit=limit)
            for msg in messages:
                raw_text = getattr(msg, 'raw_text', '') or getattr(msg, 'message', '') or ""
                
                media_tag = ""
                media_path = None

                # Скачиваем фото для передачи в Gemini Vision
                if getattr(msg, 'photo', None):
                    media_tag = "[📷 ФОТО] "
                    try:
                        media_path = await msg.download_media(file="downloads/")
                    except Exception as e:
                        logger.warning(f"Не удалось скачать фото: {e}")
                elif getattr(msg, 'video', None):
                    duration = getattr(msg.video, 'duration', 0)
                    media_tag = f"[📹 ВИДЕО {duration}с] " if duration else "[📹 ВИДЕО] "
                elif getattr(msg, 'gif', None) or getattr(msg, 'document', None):
                    media_tag = "[📁 МЕДИА] "

                if not raw_text.strip() and not media_tag:
                    continue

                full_text = f"{media_tag}{raw_text}".strip()

                reactions_count = sum(r.count for r in msg.reactions.results) if (getattr(msg, 'reactions', None) and msg.reactions.results) else 0
                comments_count = msg.replies.replies if (getattr(msg, 'replies', None) and msg.replies.replies) else 0
                views_count = msg.views if (getattr(msg, 'views', None) and msg.views > 0) else 1
                er = ((reactions_count + comments_count) / views_count) * 100.0
                created_at_str = msg.date.strftime("%Y-%m-%d %H:%M:%S") if getattr(msg, 'date', None) else None
                post_url = f"https://t.me/{username}/{msg.id}"

                saved = await db.save_post(
                    channel_id=channel['id'],
                    msg_id=msg.id,
                    source_type="tg",
                    source_name=channel_title,
                    post_url=post_url,
                    text=full_text,
                    media_path=media_path,
                    views=views_count,
                    reactions=reactions_count,
                    comments=comments_count,
                    er=er,
                    created_at=created_at_str
                )
                if saved:
                    parsed_count += 1
        except Exception as e:
            logger.error(f"Ошибка парсинга ТГ {channel.get('username')}: {e}")

    await client.disconnect()
    return parsed_count

async def parse_media_sites(limit: int = 20) -> int:
    """Парсинг статей из СМИ через RSS."""
    sources = await db.get_media_sources()
    if not sources:
        return 0

    parsed_count = 0
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

    async with httpx.AsyncClient(headers=headers, timeout=20.0, follow_redirects=True) as http_client:
        for src in sources:
            try:
                resp = await http_client.get(src['url'])
                if resp.status_code != 200:
                    continue

                feed = feedparser.parse(resp.text)
                for entry in feed.entries[:limit]:
                    title = entry.get('title', '').strip()
                    summary = clean_html_tags(entry.get('summary', '') or entry.get('description', ''))
                    link = entry.get('link', '').strip()

                    full_text = f"📰 <b>{title}</b>\n\n{summary}"
                    if len(full_text) < 50:
                        continue

                    saved = await db.save_post(
                        channel_id=None,
                        msg_id=None,
                        source_type="media",
                        source_name=src['name'],
                        post_url=link,
                        text=full_text,
                        media_path=None,
                        views=1000,
                        reactions=50,
                        comments=10,
                        er=6.0
                    )
                    if saved:
                        parsed_count += 1
            except Exception as e:
                logger.error(f"Ошибка парсинга СМИ {src.get('name')}: {e}")

    return parsed_count

async def run_parser(mode: str = "all", limit: int = 20) -> int:
    """Главная функция сбора."""
    safe_limit = min(max(1, limit), 150)
    total = 0
    if mode in ("all", "tg"):
        total += await parse_tg_channels(limit=safe_limit)
    if mode in ("all", "media"):
        total += await parse_media_sites(limit=safe_limit)
    return total
