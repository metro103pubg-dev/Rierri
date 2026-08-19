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

def clean_html_tags(raw_html: str) -> str:
    """Удаление HTML-тегов из текста статей СМИ."""
    clean = re.compile('<.*?>')
    text = re.sub(clean, '', raw_html)
    return ' '.join(text.split())

async def parse_tg_channels() -> int:
    """Парсинг постов из Telegram-каналов."""
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

            messages = await client.get_messages(entity, limit=20)
            for msg in messages:
                text = getattr(msg, 'raw_text', '') or getattr(msg, 'message', '') or ""
                if not text.strip():
                    continue

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
                    text=text,
                    views=views_count,
                    reactions=reactions_count,
                    comments=comments_count,
                    er=er,
                    created_at=created_at_str
                )
                if saved:
                    parsed_count += 1
        except Exception as e:
            logger.error(f"Ошибка парсинга ТГ-канала {channel.get('username')}: {e}")

    await client.disconnect()
    return parsed_count

async def parse_media_sites() -> int:
    """Парсинг свежих новостей из сайтов и СМИ через RSS."""
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
                for entry in feed.entries[:10]:
                    title = entry.get('title', '').strip()
                    summary = clean_html_tags(entry.get('summary', '') or entry.get('description', ''))
                    link = entry.get('link', '').strip()

                    full_text = f"📰 <b>{title}</b>\n\n{summary}"
                    if len(full_text) < 50:
                        continue

                    # Для СМИ ставим базовый приоритетный ER
                    saved = await db.save_post(
                        channel_id=None,
                        msg_id=None,
                        source_type="media",
                        source_name=src['name'],
                        post_url=link,
                        text=full_text,
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

async def run_parser(mode: str = "all") -> int:
    """Главная функция запуска парсинга в зависимости от выбранного режима."""
    total = 0
    if mode in ("all", "tg"):
        total += await parse_tg_channels()
    if mode in ("all", "media"):
        total += await parse_media_sites()
    return total
