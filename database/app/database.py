from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://parkinguser:parkingpass@localhost:5433/smartparking"
    SYNC_DATABASE_URL: str = "postgresql+psycopg2://parkinguser:parkingpass@localhost:5433/smartparking"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=True,
    pool_size=10,
    max_overflow=20,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


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
