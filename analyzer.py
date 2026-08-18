import json
import logging
from openai import AsyncOpenAI
from config import config
import database as db

logger = logging.getLogger(__name__)

ai_client = AsyncOpenAI(
    api_key=config.OPENAI_API_KEY,
    base_url=config.OPENAI_BASE_URL
)

async def evaluate_post_with_ai(text: str) -> dict:
    """Оценка поста через Gemini API."""
    system_prompt = (
        "Ты — маркетолог. Прочитай пост и определи, есть ли в нем польза, кейс или вирусный триггер "
        "для инфобизнеса. Отсей рекламу и мусор. "
        'Верни ответ строго в формате JSON: {"verdict": "CHOOSE" или "SKIP", "main_idea": "суть", "why": "почему"}'
    )
    
    try:
        response = await ai_client.chat.completions.create(
            model=config.GEMINI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text}
            ],
            temperature=0.3,
            response_format={"type": "json_object"}
        )
        content = response.choices[0].message.content.strip()
        
        if content.startswith("```"):
            content = content.replace("```json", "").replace("```", "").strip()

        return json.loads(content)
    except Exception as e:
        logger.error(f"Ошибка вызова Gemini: {e}")
        return {
            "verdict": "SKIP", 
            "main_idea": "Ошибка ИИ", 
            "why": f"Исключение: {e}"
        }

async def rewrite_post(text: str) -> str:
    """Генерация рерайта поста."""
    system_prompt = (
        "Перепиши этот инфобизнесовый пост. Сделай его уникальным, живым, разбей на абзацы, "
        "добавь сильный заголовок-хук и добавь в конец призыв подписаться на наш канал. Сохрани пользу и цифры."
    )
    
    try:
        response = await ai_client.chat.completions.create(
            model=config.GEMINI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text}
            ],
            temperature=0.7
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Ошибка рерайта: {e}")
        return f"Не удалось выполнить рерайт. Ошибка: {e}"

async def process_new_posts() -> int:
    """Фильтрация постов по ER и отбор с помощью ИИ."""
    posts = await db.get_unprocessed_posts()
    processed_count = 0

    for post in posts:
        avg_er = await db.get_channel_avg_er(post["channel_id"])
        
        # Если данных о среднем ER нет, либо ER поста >= avg_er * 1.2
        if avg_er is None or avg_er == 0 or post["er"] >= (avg_er * 1.2):
            ai_res = await evaluate_post_with_ai(post["text"])
            verdict = str(ai_res.get("verdict", "SKIP")).upper()
            ai_analysis_str = json.dumps(ai_res, ensure_ascii=False)
            
            if verdict == "CHOOSE":
                await db.update_post_status(post["id"], "chosen", ai_analysis_str)
            else:
                await db.update_post_status(post["id"], "skipped", ai_analysis_str)
        else:
            skip_reason = json.dumps({"verdict": "SKIP", "why": "ER ниже порога 1.2x"}, ensure_ascii=False)
            await db.update_post_status(post["id"], "skipped", skip_reason)
            
        processed_count += 1

    return processed_count
