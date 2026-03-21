from contextlib import contextmanager

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_FILE = "database/bot_data.db"

engine = create_engine("sqlite:///" + DATABASE_FILE, echo=False)
SessionMaker = sessionmaker(bind=engine, expire_on_commit=False)
BaseModel = declarative_base()


@contextmanager
def db_session_scope():
    session = SessionMaker()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def update_db():
    # Run migrations
    # Migration can be created by running (in /database):
    # alembic revision --autogenerate -m "example message"
    alembic_cfg = Config("database/alembic.ini")
    command.upgrade(alembic_cfg, "head")
