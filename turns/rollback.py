from __future__ import annotations

from pathlib import Path
from typing import Any

from turns.store import TurnStore


class RollbackConflictError(RuntimeError):
    pass


class TurnRollbackService:
    def __init__(self, workspace_root: Path, turn_store: TurnStore):
        self.workspace_root = Path(workspace_root)
        self.turn_store = turn_store

    def can_rollback(self, turn_id: str) -> tuple[bool, str | None]:
        turn = self.turn_store.get_turn(turn_id)
        if not turn:
            return False, "Turn 不存在"
        if turn.get("runtime_id") != "handmade":
            return False, "当前仅支持 handmade runtime 回滚"
        if turn.get("status") != "done":
            return False, "仅已完成 Turn 支持回滚"
        if not turn.get("file_changes"):
            return False, "本轮没有可回滚的文件修改"
        try:
            self._assert_no_conflicts(turn)
        except RollbackConflictError as exc:
            return False, str(exc)
        return True, None

    def rollback_turn(self, turn_id: str) -> dict[str, Any]:
        turn = self.turn_store.get_turn(turn_id)
        if not turn:
            raise ValueError("Turn 不存在")
        self._assert_no_conflicts(turn)

        for change in reversed(turn.get("file_changes", [])):
            self._rollback_change(change)

        return self.turn_store.update_turn(turn_id, status="rolled_back", rolled_back_at=__import__("time").time())

    def _assert_no_conflicts(self, turn: dict[str, Any]) -> None:
        conflicts: list[str] = []
        for change in turn.get("file_changes", []):
            path = self.workspace_root / change["path"]
            operation = change.get("operation")
            if operation == "create":
                if not path.exists():
                    conflicts.append(change["path"])
                    continue
                current = path.read_text(encoding="utf-8")
                if _hash_content(current) != change.get("after_hash"):
                    conflicts.append(change["path"])
            elif operation == "update":
                if not path.exists():
                    conflicts.append(change["path"])
                    continue
                current = path.read_text(encoding="utf-8")
                if _hash_content(current) != change.get("after_hash"):
                    conflicts.append(change["path"])
            elif operation == "delete":
                if path.exists():
                    conflicts.append(change["path"])
        if conflicts:
            raise RollbackConflictError(f"检测到文件冲突，无法安全回滚：{', '.join(conflicts)}")

    def _rollback_change(self, change: dict[str, Any]) -> None:
        path = self.workspace_root / change["path"]
        operation = change.get("operation")
        if operation == "create":
            if path.exists():
                path.unlink()
            return
        if operation == "update":
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(change.get("before_content") or "", encoding="utf-8")
            return
        if operation == "delete":
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(change.get("before_content") or "", encoding="utf-8")
            return
        raise ValueError(f"不支持的回滚操作: {operation}")


def _hash_content(content: str | None) -> str | None:
    if content is None:
        return None
    import hashlib

    return hashlib.sha256(content.encode("utf-8")).hexdigest()
