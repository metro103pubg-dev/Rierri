import asyncio
import json
import logging
import httpx
from config import config
import database as db

logger = logging.getLogger(__name__)

# Проверенные модели Gemini
MODELS = [
    "gemini-flash-latest",
    "gemini-1.5-flash-latest",
    "gemini-1.5-pro-latest"
]

async def send_gemini_request(payload: dict) -> dict:
    """Отправка запроса с обработкой лимитов 429 и перегрузок 503."""
    headers = {
        "Content-Type": "application/json",
        "X-goog-api-key": config.OPENAI_API_KEY.strip()
    }
    
    last_error = None
    for model_name in MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
        
        for attempt in range(4):
            try:
                async with httpx.AsyncClient(timeout=45.0) as client:
                    resp = await client.post(url, headers=headers, json=payload)
                    
                    if resp.status_code == 200:
                        return resp.json()
                    
                    if resp.status_code == 404:
                        break
                        
                    if resp.status_code in (429, 503, 500):
                        wait_sec = (attempt + 1) * 3
                        logger.warning(f"[{model_name}] Ожидание лимита {wait_sec} сек...")
                        await asyncio.sleep(wait_sec)
                        continue
                        
                    resp.raise_for_status()
            except Exception as e:
                last_error = e
                await asyncio.sleep(2.0)
                
    raise Exception(f"Все серверы Gemini временно заняты: {last_error}")

async def evaluate_posts_batch(posts: list[dict]) -> dict:
    """Отбор постов: отсев рекламы и гарантия отбора минимум 3 постов."""
    system_prompt = (
        "Ты — шеф-редактор Telegram-канала.\n"
        "1. Отсей рекламу, спам и мусор.\n"
        "2. Выбери минимум 3 самых сильных и интересных поста.\n"
        "Верни ответ СТРОГО в формате JSON:\n"
        '{"results": [{"post_id": 123, "verdict": "CHOOSE" или "SKIP", "main_idea": "суть", "why": "почему интересно"}]}'
    )

    posts_text_list = []
    for p in posts:
        clean_text = p["text"][:700].replace("\n", " ")
        posts_text_list.append(f"[ID: {p['id']}] ER: {p['er']:.2f}% | Текст: {clean_text}")

    full_content = f"{system_prompt}\n\nСПИСОК ПОСТОВ:\n" + "\n\n".join(posts_text_list)
    payload = {
        "contents": [{"parts": [{"text": full_content}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2}
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

async def rewrite_post(text: str, style: str = "expert") -> str:
    """Генерация рерайта в выбранном стиле с 3 хуками."""
    style_prompts = {
        "expert": "СТИЛЬ: Экспертный, сжатый, фокус на пользе, цифрах и логике. Без занудства.",
        "tldr": "СТИЛЬ: TL;DR (Выжимка). Сверхкратко: 3-4 ключевых тезиса с эмодзи. Без воды.",
        "provocative": "СТИЛЬ: Дерзкий, хлесткий разговорный интернет-сленг, сарказм и экспрессия. Без цензурной духоты.",
        "guide": "СТИЛЬ: Пошаговый гайд (1-2-3-4). Практический алгоритм действий."
    }

    selected_style = style_prompts.get(style, style_prompts["expert"])

    system_prompt = (
        "Ты — топовый автор Telegram-канала.\n\n"
        f"ТВОЙ СТИЛЬ:\n{selected_style}\n\n"
        "ПРАВИЛА:\n"
        "1. В самом начале предложи 3 варианта заголовка:\n"
        "🪝 <b>3 варианта хука:</b>\n"
        "1️⃣ [Интригующий вопрос]\n"
        "2️⃣ [Фактический / С цифрой]\n"
        "3️⃣ [Провокационный]\n\n"
        "2. Далее через пустую строку напиши готовый текст поста (короткие абзацы по 1-2 предложения).\n"
        "3. ЗАПРЕЩЕНО оставлять любые ссылки и чужие юзернеймы (@username).\n"
        "4. Вырежи рекламу и выдавай ТОЛЬКО готовый текст поста."
    )

    payload = {
        "contents": [{"parts": [{"text": f"{system_prompt}\n\nТЕКСТ ПОСТА:\n{text}"}]}],
        "generationConfig": {"temperature": 0.7 if style == "provocative" else 0.5}
    }

    try:
        data = await send_gemini_request(payload)
        result = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        if result.startswith('\"') and result.endswith('\"'):
            result = result[1:-1].strip()
        return result
    except Exception as e:
        logger.error(f"Ошибка рерайта: {e}")
        return f"Не удалось выполнить рерайт: {e}"

async def process_new_posts() -> int:
    """Анализ новых постов с гарантией отбора не менее 3 штук."""
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
                "main_idea": "Высокая вовлеченность",
                "why": f"Пост в топ-3 по активности (ER: {post['er']:.2f}%)"
            }, ensure_ascii=False)
            await db.update_post_status(post["id"], "chosen", backup_analysis)

    return len(posts)
