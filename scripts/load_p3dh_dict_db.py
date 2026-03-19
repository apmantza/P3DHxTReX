"""Load P3DH data dictionary CSV into the DB reference table."""
from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

from db.engine import get_engine
from db.models import Base, P3DHDataDictionary
from sqlalchemy.orm import sessionmaker

DB_PATH = repo_root / "data" / "processed" / "bbirr.db"
CSV_PATH = repo_root / "data" / "processed" / "p3dh_data_dictionary.csv"


def main() -> None:
    engine = get_engine(DB_PATH)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    df = pd.read_csv(CSV_PATH, encoding="utf-8-sig", dtype=str).fillna("")

    with Session() as session:
        session.query(P3DHDataDictionary).delete()
        session.bulk_insert_mappings(
            P3DHDataDictionary,
            df.rename(columns={"dpm_point_id": "dpm_point_id"}).to_dict("records"),
        )
        session.commit()

    print(f"Loaded {len(df):,} P3DH dictionary records into {DB_PATH}")


if __name__ == "__main__":
    main()
