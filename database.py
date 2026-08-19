import aiosqlite
from config import config

async def init_db() -> None:
    async with aiosqlite.connect(config.DB_NAME) as db:
        await db.execute("PRAGMA foreign_keys = ON;")
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                title TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS media_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                url TEXT UNIQUE NOT NULL,
                category TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER,
                msg_id INTEGER,
                source_type TEXT DEFAULT 'tg',
                source_name TEXT,
                post_url TEXT,
                text TEXT NOT NULL,
                views INTEGER NOT NULL DEFAULT 0,
                reactions INTEGER NOT NULL DEFAULT 0,
                comments INTEGER NOT NULL DEFAULT 0,
                er REAL NOT NULL DEFAULT 0.0,
                status TEXT NOT NULL DEFAULT 'new',
                ai_analysis TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(source_type, post_url)
            )
        """)
        
        # Миграция существующих таблиц
        try:
            await db.execute("ALTER TABLE posts ADD COLUMN source_type TEXT DEFAULT 'tg';")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE posts ADD COLUMN source_name TEXT;")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE posts ADD COLUMN post_url TEXT;")
        except Exception:
            pass

        await db.commit()

# --- Управление СМИ источниками ---

async def add_media_source(name: str, url: str, category: str = "") -> bool:
    async with aiosqlite.connect(config.DB_NAME) as db:
        try:
            await db.execute(
                "INSERT INTO media_sources (name, url, category) VALUES (?, ?, ?)",
                (name.strip(), url.strip(), category)
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

async def delete_media_source(url: str) -> bool:
    async with aiosqlite.connect(config.DB_NAME) as db:
        cursor = await db.execute("DELETE FROM media_sources WHERE url = ?", (url.strip(),))
        await db.commit()
        return cursor.rowcount > 0

async def get_media_sources() -> list[dict]:
    async with aiosqlite.connect(config.DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM media_sources ORDER BY id ASC") as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

# --- Управление ТГ-каналами ---

async def add_channel(username: str, title: str = "") -> bool:
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

async def delete_channel(username: str) -> bool:
    clean_username = username.strip().replace("@", "").replace("https://t.me/", "")
    async with aiosqlite.connect(config.DB_NAME) as db:
        cursor = await db.execute("DELETE FROM channels WHERE username = ?", (clean_username,))
        await db.commit()
        return cursor.rowcount > 0

async def update_channel_title(channel_id: int, title: str) -> None:
    async with aiosqlite.connect(config.DB_NAME) as db:
        await db.execute("UPDATE channels SET title = ? WHERE id = ?", (title, channel_id))
        await db.commit()

async def get_channels() -> list[dict]:
    async with aiosqlite.connect(config.DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM channels") as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

# --- Сохранение постов ---

async def save_post(
    channel_id: int | None, 
    msg_id: int | None, 
    text: str, 
    views: int = 0, 
    reactions: int = 0, 
    comments: int = 0, 
    er: float = 0.0, 
    source_type: str = "tg",
    source_name: str = "",
    post_url: str = "",
    created_at: str | None = None
) -> bool:
    async with aiosqlite.connect(config.DB_NAME) as db:
        try:
            await db.execute(
                """
                INSERT OR IGNORE INTO posts 
                (channel_id, msg_id, source_type, source_name, post_url, text, views, reactions, comments, er, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', COALESCE(?, CURRENT_TIMESTAMP))
                """,
                (channel_id, msg_id, source_type, source_name, post_url, text, views, reactions, comments, er, created_at)
            )
            await db.commit()
            return True
        except Exception:
            return False

async def get_unprocessed_posts() -> list[dict]:
    async with aiosqlite.connect(config.DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM posts WHERE status = 'new'") as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

async def update_post_status(post_id: int, status: str, ai_analysis: str | None = None) -> None:
    async with aiosqlite.connect(config.DB_NAME) as db:
        if ai_analysis is not None:
            await db.execute("UPDATE posts SET status = ?, ai_analysis = ? WHERE id = ?", (status, ai_analysis, post_id))
        else:
            await db.execute("UPDATE posts SET status = ? WHERE id = ?", (status, post_id))
        await db.commit()

async def get_chosen_posts() -> list[dict]:
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

# --- Настройки и Админы ---

async def add_admin(user_id: int) -> bool:
    async with aiosqlite.connect(config.DB_NAME) as db:
        try:
            await db.execute("INSERT INTO admins (user_id) VALUES (?)", (user_id,))
            await db.commit()
            return True
        except Exception:
            return False

async def delete_admin(user_id: int) -> bool:
    async with aiosqlite.connect(config.DB_NAME) as db:
        cursor = await db.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
        await db.commit()
        return cursor.rowcount > 0

async def get_admins() -> list[int]:
    async with aiosqlite.connect(config.DB_NAME) as db:
        async with db.execute("SELECT user_id FROM admins") as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

async def is_user_authorized(user_id: int) -> bool:
    if user_id == config.ADMIN_ID:
        return True
    admins = await get_admins()
    return user_id in admins

async def set_setting(key: str, value: str) -> None:
    async with aiosqlite.connect(config.DB_NAME) as db:
        await db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value)
        )
        await db.commit()

async def get_setting(key: str) -> str | None:
    async with aiosqlite.connect(config.DB_NAME) as db:
        async with db.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None
