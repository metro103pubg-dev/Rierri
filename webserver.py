import os
import logging
from aiohttp import web

logger = logging.getLogger(__name__)

async def health_check(request):
    return web.Response(text="AI Content Curator Bot is Alive & Running 24/7!")

async def start_webserver():
    """Запуск фонового веб-сервера для поддержания активности на Railway."""
    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Веб-сервер активности запущен на порту {port}")
