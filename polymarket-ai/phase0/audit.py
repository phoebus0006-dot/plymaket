from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class AuditTrail:
    def __init__(self, log_dir: str | Path) -> None:
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def append(self, entry: dict[str, Any]) -> None:
        entry["_timestamp"] = entry.get("_timestamp", None)
        log_path = self.log_dir / "audit.jsonl"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str, ensure_ascii=False) + "\n")

    def read_all(self) -> list[dict[str, Any]]:
        log_path = self.log_dir / "audit.jsonl"
        if not log_path.exists():
            return []
        entries: list[dict[str, Any]] = []
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        return entries
