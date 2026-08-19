import logging
from telethon import TelegramClient
from telethon.sessions import StringSession
from config import config
import database as db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def run_parser() -> int:
    """Сбор последних 20 постов из отслеживаемых каналов."""
    channels = await db.get_channels()
    if not channels:
        logger.info("Нет каналов в базе для парсинга.")
        return 0

    if config.TELETHON_SESSION:
        client = TelegramClient(StringSession(config.TELETHON_SESSION), config.API_ID, config.API_HASH)
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

                saved = await db.save_post(
                    channel_id=channel['id'],
                    msg_id=msg.id,
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
            logger.error(f"Ошибка при парсинге канала {channel.get('username')}: {e}")

    await client.disconnect()
    return parsed_count
