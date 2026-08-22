import os
import base64
import asyncio
import json
import logging
import httpx
from config import config
import database as db

logger = logging.getLogger(__name__)

MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash",
    "gemini-2.0-flash",
    "gemini-flash-latest"
]

def encode_image_to_base64(image_path: str) -> dict | None:
    """Кодирование изображения в формат Gemini Vision API."""
    if not image_path or not os.path.exists(image_path):
        return None
    try:
        ext = os.path.splitext(image_path)[1].lower().replace(".", "")
        mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"
        with open(image_path, "rb") as image_file:
            encoded_bytes = base64.b64encode(image_file.read()).decode("utf-8")
            return {
                "inline_data": {
                    "mime_type": mime,
                    "data": encoded_bytes
                }
            }
    except Exception as e:
        logger.warning(f"Ошибка кодирования картинки: {e}")
        return None

async def send_gemini_request(payload: dict) -> dict:
    headers = {
        "Content-Type": "application/json",
        "X-goog-api-key": config.OPENAI_API_KEY.strip()
    }
    
    last_error = None
    for model_name in MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(url, headers=headers, json=payload)
                    if resp.status_code == 200:
                        return resp.json()
                    if resp.status_code == 404:
                        break
                    if resp.status_code in (503, 429, 500):
                        await asyncio.sleep(1.0)
                        continue
                    resp.raise_for_status()
            except Exception as e:
                last_error = e
                await asyncio.sleep(1.0)
                
    raise Exception(f"Все серверы Gemini перегружены: {last_error}")

async def evaluate_posts_batch(posts: list[dict]) -> dict:
    """Отбор горячих инфоповодов, шок-новостей и мемов."""
    system_prompt = (
        "Ты — шеф-редактор вирусного новостного Telegram-канала ('Топор', 'Двач', 'КБ', 'Рифмы и Панчи').\n\n"
        "КРИТЕРИИ ОТБОРА:\n"
        "1. Отбирай самый вирусный, обсуждаемый и эмоциональный контент:\n"
        "   — Громкие происшествия, уличные разборки, резонансные события, абсурдный треш;\n"
        "   — Смешные мемы, угарные видео и приколы с высоким откликом аудитории;\n"
        "   — Посты с [📷 ФОТО] и [📹 ВИДЕО] имеют максимальный приоритет.\n"
        "2. ОТСЕИВАЙ скучные отчеты ведомств, нудные декларации, рекламу казино, крипты и курсов.\n"
        "3. Выбери минимум 3 самых обсуждаемых и смешных/резонансных инфоповода.\n\n"
        "Верни ответ СТРОГО в формате JSON:\n"
        '{"results": [{"post_id": 123, "verdict": "CHOOSE" или "SKIP", "main_idea": "суть", "why": "почему завирусится"}]}'
    )

    posts_text_list = []
    for p in posts:
        clean_text = p["text"][:700].replace("\n", " ")
        posts_text_list.append(f"[ID: {p['id']}] ER: {p['er']:.2f}% | {clean_text}")

    full_content = f"{system_prompt}\n\nСПИСОК МАТЕРИАЛОВ:\n" + "\n\n".join(posts_text_list)
    payload = {
        "contents": [{"parts": [{"text": full_content}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.3}
    }

    try:
        data = await send_gemini_request(payload)
        content = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        if content.startswith("```"):
            content = content.replace("```json", "").replace("```", "").strip()
        return json.loads(content)
    except Exception as e:
        logger.error(f"Ошибка вызова Gemini: {e}")
        return {"results": []}

async def rewrite_post(text: str, style: str = "provocative", image_path: str | None = None) -> str:
    """Генерация рерайта с поддержкой зрения (Gemini Vision) по картинке."""
    style_prompts = {
        "humor": "СТИЛЬ: Мемный, смешной, с сарказмом и самоиронией. Остроумная подпись к картинке/видео, панчлайн.",
        "provocative": "СТИЛЬ: Хлёсткий, живой, народный таблоид, эмоциональная подача, интернет-сленг без духоты.",
        "tldr": "СТИЛЬ: TL;DR. Сверхкратко: 2-3 предложения — самая суть произошедшего.",
        "expert": "СТИЛЬ: Фактчекинг, хронология, контекст и последствия."
    }

    selected_style = style_prompts.get(style, style_prompts["provocative"])

    system_prompt = (
        "Ты — автор топового развлекательно-новостного Telegram-канала.\n"
        f"ТОНАЛЬНОСТЬ:\n{selected_style}\n\n"
        "ПРАВИЛА:\n"
        "1. В начале предложи 3 варианта цепляющего заголовка:\n"
        "🪝 <b>3 варианта хука:</b>\n"
        "1️⃣ [Смешной / Мемный]\n"
        "2️⃣ [Шокирующий / Громкий]\n"
        "3️⃣ [Интригующий вопрос]\n\n"
        "2. Далее через пустую строку напиши сам текст поста (короткие абзацы по 1-2 предложения).\n"
        "3. Если передана картинка (Vision) — учти детали с изображения в рерайте!\n"
        "4. ЗАПРЕЩЕНО оставлять любые ссылки и чужие юзернеймы (@username).\n"
        "5. Выдавай ТОЛЬКО готовый текст поста."
    )

    parts = [{"text": f"{system_prompt}\n\nИСХОДНЫЙ МАТЕРИАЛ:\n{text}"}]

    # Если есть фото — передаем его напрямую в Gemini Vision
    image_part = encode_image_to_base64(image_path)
    if image_part:
        parts.append(image_part)

    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {"temperature": 0.7 if style in ("provocative", "humor") else 0.5}
    }

    try:
        data = await send_gemini_request(payload)
        result = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        if result.startswith('\"') and result.endswith('\"'):
            result = result[1:-1].strip()
        return result
    except Exception as e:
        logger.error(f"Ошибка рерайта Vision: {e}")
        return f"Не удалось выполнить рерайт: {e}"

async def process_new_posts() -> int:
    posts = await db.get_unprocessed_posts()
    if not posts:
        return 0

    posts.sort(key=lambda x: x["er"], reverse=True)
    ai_response = await evaluate_posts_batch(posts)
    ai_results = {r["post_id"]: r for r in ai_response.get("results", []) if "post_id" in r}

    chosen_count = 0
    for post in posts:
        post_id = post["id"]
        if post_id in ai_results:
            verdict = str(ai_results[post_id].get("verdict", "SKIP")).upper()
            ai_data_str = json.dumps(ai_results[post_id], ensure_ascii=False)
            if verdict == "CHOOSE":
                await db.update_post_status(post_id, "chosen", ai_data_str)
                chosen_count += 1
            else:
                await db.update_post_status(post_id, "skipped", ai_data_str)
        else:
            await db.update_post_status(post_id, "skipped")

    if chosen_count < 3 and posts:
        for post in posts[:3]:
            backup_analysis = json.dumps({
                "verdict": "CHOOSE",
                "main_idea": "Высокий отклик аудитории",
                "why": f"Топ по активности (ER: {post['er']:.2f}%)"
            }, ensure_ascii=False)
            await db.update_post_status(post["id"], "chosen", backup_analysis)

    return len(posts)
