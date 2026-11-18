from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


@lru_cache
def get_engine() -> Engine:
    # Poca cantidad de conexiones: los Postgres gratuitos permiten pocas simultáneas.
    return create_engine(
        get_settings().sqlalchemy_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        pool_recycle=1800,
    )


def get_session_factory() -> sessionmaker[Session]:
    # expire_on_commit=False: tras guardar se sigue leyendo la entidad (y armando el DTO) sin otra consulta.
    return sessionmaker(bind=get_engine(), expire_on_commit=False, autoflush=True)


def new_session(user_id=None) -> Session:
    session = get_session_factory()()
    session.info["user_id"] = user_id
    return session


def session_scope(user_id=None) -> Iterator[Session]:
    session = new_session(user_id)
    try:
        yield session
    finally:
        session.close()
