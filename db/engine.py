from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def get_engine(db_path: str | Path) -> "Engine":
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{path}", future=True)


def get_session(db_path: str | Path):
    engine = get_engine(db_path)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
