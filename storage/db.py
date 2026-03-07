from contextlib import contextmanager

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

engine = create_engine("sqlite:///bot_data.db", echo=False)
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
    alembic_cfg = Config("storage/alembic.ini")
    command.upgrade(alembic_cfg, "head")
