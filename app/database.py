from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncAttrs
from sqlalchemy.orm import DeclarativeBase
from app.config import settings
from sqlalchemy import text

async_engine = create_async_engine(str(settings.DATABASE_URL), echo=False, pool_pre_ping=True)
async_sessionmaker = async_sessionmaker(async_engine, expire_on_commit=False)

class Base(AsyncAttrs, DeclarativeBase):
    pass

async def init_models():
    from app import models  # noqa: F401
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # pragma: no cover
