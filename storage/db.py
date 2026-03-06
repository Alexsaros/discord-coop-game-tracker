from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

engine = create_engine("sqlite:///bot_data.db", echo=False)
SessionMaker = sessionmaker(bind=engine)
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
