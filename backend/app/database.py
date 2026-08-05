from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from backend.app.config import settings
import sys

db_url = settings.DATABASE_URL

# Handle postgres driver string if postgresql:// is provided
if db_url.startswith("postgresql://"):
    db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

# If unexpanded Zerops template syntax exists or invalid config, fallback to SQLite
if "${" in db_url:
    print("[Database] Unexpanded template in DATABASE_URL, falling back to SQLite: jukebox.db")
    db_url = "sqlite+aiosqlite:///./jukebox.db"

try:
    engine = create_async_engine(
        db_url,
        echo=False,
        future=True
    )
except Exception as e:
    print(f"[Database] Engine creation error: {e}. Falling back to SQLite.")
    db_url = "sqlite+aiosqlite:///./jukebox.db"
    engine = create_async_engine(db_url, echo=False, future=True)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)

Base = declarative_base()

async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

async def init_db():
    global engine, AsyncSessionLocal
    try:
        async with engine.begin() as conn:
            from backend.app import models # noqa: F401
            await conn.run_sync(Base.metadata.create_all)
        print("[Database] Database initialized successfully.")
    except Exception as e:
        print(f"[Database] Initializing DB failed with {db_url}: {e}. Switching to SQLite fallback...")
        fallback_url = "sqlite+aiosqlite:///./jukebox.db"
        engine = create_async_engine(fallback_url, echo=False, future=True)
        AsyncSessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
        async with engine.begin() as conn:
            from backend.app import models # noqa: F401
            await conn.run_sync(Base.metadata.create_all)
        print("[Database] SQLite fallback initialized successfully.")
