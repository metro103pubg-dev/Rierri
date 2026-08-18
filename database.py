import aiosqlite
from config import config

async def init_db() -> None:
    """Инициализация базы данных и создание необходимых таблиц."""
    async with aiosqlite.connect(config.DB_NAME) as db:
        await db.execute("PRAGMA foreign_keys = ON;")
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                title TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER NOT NULL,
                msg_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                views INTEGER NOT NULL DEFAULT 0,
                reactions INTEGER NOT NULL DEFAULT 0,
                comments INTEGER NOT NULL DEFAULT 0,
                er REAL NOT NULL DEFAULT 0.0,
                status TEXT NOT NULL DEFAULT 'new',
                ai_analysis TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(channel_id, msg_id),
                FOREIGN KEY(channel_id) REFERENCES channels(id) ON DELETE CASCADE
            )
        """)
        await db.commit()

async def add_channel(username: str, title: str = "") -> bool:
    """Добавить новый канал в список мониторинга."""
    clean_username = username.strip().replace("@", "").replace("https://t.me/", "")
    async with aiosqlite.connect(config.DB_NAME) as db:
        try:
            await db.execute(
                "INSERT INTO channels (username, title) VALUES (?, ?)",
                (clean_username, title)
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

async def update_channel_title(channel_id: int, title: str) -> None:
    """Обновить название канала."""
    async with aiosqlite.connect(config.DB_NAME) as db:
        await db.execute(
            "UPDATE channels SET title = ? WHERE id = ?",
            (title, channel_id)
        )
        await db.commit()

async def get_channels() -> list[dict]:
    """Получить список всех каналов."""
    async with aiosqlite.connect(config.DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM channels") as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

async def save_post(
    channel_id: int, 
    msg_id: int, 
    text: str, 
    views: int, 
    reactions: int, 
    comments: int, 
    er: float, 
    created_at: str | None = None
) -> bool:
    """Сохранить спарсенный пост со статусом 'new'."""
    async with aiosqlite.connect(config.DB_NAME) as db:
        try:
            if created_at:
                await db.execute(
                    """
                    INSERT OR IGNORE INTO posts 
                    (channel_id, msg_id, text, views, reactions, comments, er, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'new', ?)
                    """,
                    (channel_id, msg_id, text, views, reactions, comments, er, created_at)
                )
            else:
                await db.execute(
                    """
                    INSERT OR IGNORE INTO posts 
                    (channel_id, msg_id, text, views, reactions, comments, er, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'new')
                    """,
                    (channel_id, msg_id, text, views, reactions, comments, er)
                )
            await db.commit()
            return True
        except Exception as e:
            print(f"Ошибка сохранения поста: {e}")
            return False

async def get_channel_avg_er(channel_id: int) -> float | None:
    """Получить средний ER канала за последние 7 дней."""
    async with aiosqlite.connect(config.DB_NAME) as db:
        async with db.execute(
            """
            SELECT AVG(er) FROM posts 
            WHERE channel_id = ? AND created_at >= datetime('now', '-7 days')
            """,
            (channel_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row and row[0] is not None:
                return float(row[0])
            return None

async def get_unprocessed_posts() -> list[dict]:
    """Получить список постов со статусом 'new'."""
    async with aiosqlite.connect(config.DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM posts WHERE status = 'new'") as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

async def update_post_status(post_id: int, status: str, ai_analysis: str | None = None) -> None:
    """Обновить статус поста (например: 'chosen', 'skipped', 'rewritten')."""
    async with aiosqlite.connect(config.DB_NAME) as db:
        if ai_analysis is not None:
            await db.execute(
                "UPDATE posts SET status = ?, ai_analysis = ? WHERE id = ?",
                (status, ai_analysis, post_id)
            )
        else:
            await db.execute(
                "UPDATE posts SET status = ? WHERE id = ?",
                (status, post_id)
            )
        await db.commit()

async def get_chosen_posts() -> list[dict]:
    """Получить отобранные посты со статусом 'chosen'."""
    async with aiosqlite.connect(config.DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT p.*, c.username as channel_username, c.title as channel_title 
            FROM posts p
            LEFT JOIN channels c ON p.channel_id = c.id
            WHERE p.status = 'chosen'
            ORDER BY p.id ASC
            """
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

async def get_post_by_id(post_id: int) -> dict | None:
    """Получить пост по его ID."""
    async with aiosqlite.connect(config.DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT p.*, c.username as channel_username, c.title as channel_title 
            FROM posts p
            LEFT JOIN channels c ON p.channel_id = c.id
            WHERE p.id = ?
            """,
            (post_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None
