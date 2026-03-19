from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class IngestionResult:
    name: str
    path: Path
    rows: int
    columns: int


def require_paths(paths: Iterable[Path]) -> None:
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing required files: {', '.join(missing)}")


def as_path(path: str | Path) -> Path:
    return path if isinstance(path, Path) else Path(path)
