from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from backend.app.config import settings

SQLITE_FALLBACK_URL = "sqlite+aiosqlite:///./jukebox.db"

db_url = settings.DATABASE_URL

# Handle postgres driver string if postgresql:// is provided
if db_url.startswith("postgresql://"):
    db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

# Whether the operator actually configured a real database. Once true, a
# connection failure below should crash the app rather than silently and
# invisibly running on throwaway SQLite -- fine for local dev with no
# DATABASE_URL set, but not once real data (e.g. venue account passwords) is
# expected to live in the configured database: a healthy-looking app quietly
# running on the wrong DB is worse than a container stuck restart-looping.
_is_explicit_db = db_url.startswith("postgresql+asyncpg://") and "${" not in db_url

# If unexpanded Zerops template syntax exists, fallback to SQLite
if "${" in db_url:
    print("[Database] Unexpanded template in DATABASE_URL, falling back to SQLite: jukebox.db")
    db_url = SQLITE_FALLBACK_URL

try:
    engine = create_async_engine(
        db_url,
        echo=False,
        future=True
    )
except Exception as e:
    if _is_explicit_db:
        raise RuntimeError(f"[Database] Failed to create engine for configured DATABASE_URL: {e}") from e
    print(f"[Database] Engine creation error: {e}. Falling back to SQLite.")
    db_url = SQLITE_FALLBACK_URL
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

# Columns added to already-existing tables after their initial release.
# `Base.metadata.create_all` only creates brand-new tables -- it never ALTERs
# an existing one -- so on a live DB these need to be applied explicitly.
# Each entry: (table, column, sqlite DDL type, postgres DDL type).
_LIGHT_MIGRATIONS = [
    ("venues", "premium_style_unlock_fee", "FLOAT NOT NULL DEFAULT 2.0", "FLOAT NOT NULL DEFAULT 2.0"),
    ("venues", "autoplay_enabled", "BOOLEAN NOT NULL DEFAULT 0", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("queue", "style", "VARCHAR(60)", "VARCHAR(60)"),
    ("queue", "is_autofilled", "BOOLEAN NOT NULL DEFAULT 0", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("transactions", "kind", "VARCHAR(20) NOT NULL DEFAULT 'priority_boost'", "VARCHAR(20) NOT NULL DEFAULT 'priority_boost'"),
    ("transactions", "venue_amount", "FLOAT NOT NULL DEFAULT 0.0", "FLOAT NOT NULL DEFAULT 0.0"),
    ("transactions", "app_amount", "FLOAT NOT NULL DEFAULT 0.0", "FLOAT NOT NULL DEFAULT 0.0"),
    ("venues", "favorite_genres", "TEXT NOT NULL DEFAULT ''", "TEXT NOT NULL DEFAULT ''"),
    ("venues", "player_link_token", "VARCHAR(64) NOT NULL DEFAULT ''", "VARCHAR(64) NOT NULL DEFAULT ''"),
    # Clubowna: venue-as-community-hub fields (see models.py's Venue docstring / PLAN.md).
    ("venues", "description", "TEXT", "TEXT"),
    ("venues", "address", "VARCHAR(255)", "VARCHAR(255)"),
    ("venues", "scene_theme", "VARCHAR(30) NOT NULL DEFAULT 'pub'", "VARCHAR(30) NOT NULL DEFAULT 'pub'"),
    # NOTE: SQLAlchemy's Enum type stores the Python enum *member name*
    # ("PUBLIC"), not its .value ("public") -- matches how QueueStatus/
    # TransactionStatus rows are already stored in this DB.
    ("venues", "mode", "VARCHAR(20) NOT NULL DEFAULT 'PUBLIC'", "VARCHAR(20) NOT NULL DEFAULT 'PUBLIC'"),
    ("venues", "available_modules", "TEXT NOT NULL DEFAULT 'jukebox,qr_entry'", "TEXT NOT NULL DEFAULT 'jukebox,qr_entry'"),
]


async def _run_light_migrations(conn):
    """Best-effort ALTER TABLE ADD COLUMN for columns introduced after a
    table already existed in production. Safe to run on every startup --
    each column is only added if missing, and a failure on one column
    (e.g. a brand-new table that doesn't exist yet, already covered by
    create_all) never blocks the others."""
    dialect = conn.dialect.name
    for table, column, sqlite_ddl, pg_ddl in _LIGHT_MIGRATIONS:
        try:
            if dialect == "sqlite":
                result = await conn.exec_driver_sql(f"PRAGMA table_info({table})")
                existing_cols = {row[1] for row in result.fetchall()}
                if column in existing_cols:
                    continue
                await conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {sqlite_ddl}")
            else:
                result = await conn.exec_driver_sql(
                    "SELECT column_name FROM information_schema.columns "
                    f"WHERE table_name = '{table}' AND column_name = '{column}'"
                )
                if result.fetchone():
                    continue
                await conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {pg_ddl}")
            print(f"[Database] Migration: added {table}.{column}")
        except Exception as e:
            print(f"[Database] Migration for {table}.{column} skipped/failed (likely already applied): {e}")


async def init_db():
    global engine, AsyncSessionLocal
    try:
        async with engine.begin() as conn:
            from backend.app import models # noqa: F401
            await conn.run_sync(Base.metadata.create_all)
            await _run_light_migrations(conn)
        print("[Database] Database initialized successfully.")
    except Exception as e:
        if _is_explicit_db:
            raise RuntimeError(
                f"[Database] Configured DATABASE_URL failed to initialize: {e}. "
                "Refusing to silently fall back to SQLite -- fix the connection "
                "instead of running on throwaway data."
            ) from e
        print(f"[Database] Initializing DB failed with {db_url}: {e}. Switching to SQLite fallback...")
        engine = create_async_engine(SQLITE_FALLBACK_URL, echo=False, future=True)
        AsyncSessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
        async with engine.begin() as conn:
            from backend.app import models # noqa: F401
            await conn.run_sync(Base.metadata.create_all)
            await _run_light_migrations(conn)
        print("[Database] SQLite fallback initialized successfully.")
