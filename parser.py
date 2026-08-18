import logging
from telethon import TelegramClient
from config import config
import database as db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def run_parser() -> int:
    """Запуск сбора последних 20 постов из каждого канала."""
    channels = await db.get_channels()
    if not channels:
        logger.info("Нет каналов в базе для парсинга.")
        return 0

    client = TelegramClient('userbot_session', config.API_ID, config.API_HASH)
    await client.connect()
    
    if not await client.is_user_authorized():
        logger.warning("Сессия юзербота не авторизована! Запуск первой авторизации...")
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
                text = msg.text or msg.caption or ""
                if not text.strip():
                    continue

                # Подсчет реакций со всех эмодзи
                reactions_count = 0
                if msg.reactions and msg.reactions.results:
                    reactions_count = sum(r.count for r in msg.reactions.results)

                # Подсчет комментариев
                comments_count = 0
                if msg.replies and msg.replies.replies:
                    comments_count = msg.replies.replies

                # Просмотры (минимум 1 во избежание ZeroDivisionError)
                views_count = msg.views if (msg.views and msg.views > 0) else 1

                # Расчет ER
                er = ((reactions_count + comments_count) / views_count) * 100.0

                created_at_str = msg.date.strftime("%Y-%m-%d %H:%M:%S") if msg.date else None

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
