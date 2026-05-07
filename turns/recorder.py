from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from turns.store import TurnStore


@dataclass
class TurnRecorder:
    turn_store: TurnStore
    workspace_root: Path
    current_turn_id: str | None = None

    def start(self, turn_id: str | None) -> None:
        self.current_turn_id = turn_id

    def clear(self) -> None:
        self.current_turn_id = None

    def record_file_write(self, relative_path: str, before_content: str | None, after_content: str) -> None:
        if not self.current_turn_id:
            return
        operation = "create" if before_content is None else "update"
        self.turn_store.append_file_change(
            self.current_turn_id,
            {
                "path": relative_path,
                "operation": operation,
                "before_content": before_content,
                "after_content": after_content,
                "before_hash": _hash_content(before_content),
                "after_hash": _hash_content(after_content),
                "old_path": None,
                "new_path": None,
                "encoding": "utf-8",
            },
        )

    def record_file_delete(self, relative_path: str, before_content: str) -> None:
        if not self.current_turn_id:
            return
        self.turn_store.append_file_change(
            self.current_turn_id,
            {
                "path": relative_path,
                "operation": "delete",
                "before_content": before_content,
                "after_content": None,
                "before_hash": _hash_content(before_content),
                "after_hash": None,
                "old_path": None,
                "new_path": None,
                "encoding": "utf-8",
            },
        )


def _hash_content(content: str | None) -> str | None:
    if content is None:
        return None
    import hashlib

    return hashlib.sha256(content.encode("utf-8")).hexdigest()
