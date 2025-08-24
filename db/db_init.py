import asyncio, aiosqlite

DB_PATH = "database.db"

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            chat_title TEXT,
            user_id INTEGER,
            username TEXT,
            full_name TEXT,
            text TEXT,
            photo_id TEXT,
            date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        await db.commit()

if __name__ == "__main__":
    asyncio.run(init_db())