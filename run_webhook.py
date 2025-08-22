import asyncio
import uvicorn
from app.config import settings
from app.database import init_models

async def _init():
    await init_models()

if __name__ == "__main__":
    asyncio.run(_init())
    uvicorn.run("web.flask_app:app", host="0.0.0.0", port=settings.PORT, reload=False)
