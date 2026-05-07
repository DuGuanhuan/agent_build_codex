from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from runtimes.protocol import normalize_runtime_artifact, normalize_turn

logger = logging.getLogger('agent.turns')


class TurnStore:
    def __init__(self, workspace_root: Path):
        self.workspace_root = Path(workspace_root)
        self.store_path = self.workspace_root / ".workbuddy" / "turn-store.json"
        self._lock = threading.Lock()
        self.store_path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict[str, Any]:
        if not self.store_path.exists():
            return {"turns": {}}
        try:
            return json.loads(self.store_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in turn store: {e}")
            return {"turns": {}}
        except OSError as e:
            logger.error(f"Failed to read turn store: {e}")
            return {"turns": {}}

    def _save(self, data: dict[str, Any]) -> None:
        self.store_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def create_turn(
        self,
        *,
        session_id: str | None,
        runtime_id: str,
        model_id: str | None,
        user_message_content: str,
        trusted_tools: list[str] | None = None,
        retry_of_turn_id: str | None = None,
    ) -> dict[str, Any]:
        turn_id = f"turn_{uuid.uuid4().hex[:12]}"
        turn = normalize_turn({
            "turn_id": turn_id,
            "session_id": session_id or "",
            "runtime_id": runtime_id,
            "model_id": model_id or "",
            "user_message_content": user_message_content,
            "trusted_tools": list(trusted_tools or []),
            "status": "running",
            "side_effect_level": "none",
            "file_changes": [],
            "assistant_message_id": "",
            "trace_id": "",
            "error": "",
            "created_at": time.time(),
            "completed_at": None,
            "rolled_back_at": None,
            "retry_of_turn_id": retry_of_turn_id,
        })
        with self._lock:
            data = self._load()
            data.setdefault("turns", {})[turn_id] = turn
            self._save(data)
        return turn

    def get_turn(self, turn_id: str) -> dict[str, Any] | None:
        with self._lock:
            data = self._load()
            turn = data.get("turns", {}).get(turn_id)
            return normalize_turn(turn) if isinstance(turn, dict) else None

    def update_turn(self, turn_id: str, **fields: Any) -> dict[str, Any]:
        with self._lock:
            data = self._load()
            turns = data.setdefault("turns", {})
            if turn_id not in turns:
                raise KeyError(f"turn not found: {turn_id}")
            turns[turn_id].update(fields)
            turns[turn_id] = normalize_turn(turns[turn_id])
            self._save(data)
            return dict(turns[turn_id])

    def append_file_change(self, turn_id: str, change: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            data = self._load()
            turns = data.setdefault("turns", {})
            if turn_id not in turns:
                raise KeyError(f"turn not found: {turn_id}")
            turn = turns[turn_id]
            turn.setdefault("file_changes", []).append(change)
            turn["side_effect_level"] = "workspace_reversible"
            turns[turn_id] = normalize_turn(turn)
            self._save(data)
            return dict(turns[turn_id])

    def append_artifact(self, turn_id: str, artifact: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            data = self._load()
            turns = data.setdefault("turns", {})
            if turn_id not in turns:
                raise KeyError(f"turn not found: {turn_id}")
            turn = turns[turn_id]
            artifacts = turn.setdefault("artifacts", [])
            normalized_artifact = normalize_runtime_artifact(
                artifact,
                runtime_id=turn.get("runtime_id") if isinstance(turn, dict) else None,
            )
            existing_index = next(
                (index for index, item in enumerate(artifacts) if isinstance(item, dict) and item.get("id") == normalized_artifact["id"]),
                -1,
            )
            if existing_index >= 0:
                artifacts[existing_index] = normalized_artifact
            else:
                artifacts.append(normalized_artifact)
            turns[turn_id] = normalize_turn(turn)
            self._save(data)
            return dict(turns[turn_id])

    def record_event(self, turn_id: str, event: str) -> dict[str, Any]:
        with self._lock:
            data = self._load()
            turns = data.setdefault("turns", {})
            if turn_id not in turns:
                raise KeyError(f"turn not found: {turn_id}")
            turn = normalize_turn(turns[turn_id])
            turn["event_count"] = int(turn.get("event_count") or 0) + 1
            turn["last_event"] = event
            turn["last_event_at"] = time.time()
            turns[turn_id] = turn
            self._save(data)
            return dict(turn)
