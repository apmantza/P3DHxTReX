from __future__ import annotations

from pathlib import Path
import sys

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

from db.engine import get_engine
from db.models import Base


def main() -> None:
    db_path = repo_root / "data" / "processed" / "bbirr.db"
    engine = get_engine(db_path)
    Base.metadata.create_all(engine)
    print(f"DB initialized at {db_path}")


if __name__ == "__main__":
    main()
