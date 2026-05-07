import tempfile
import unittest
from pathlib import Path

from runtimes.protocol import (
    RUNTIME_ARTIFACT_PROTOCOL,
    RUNTIME_EVENT_PROTOCOL,
    RUNTIME_TURN_PROTOCOL,
    RuntimeEventStream,
    normalize_runtime_artifact,
)
from turns.store import TurnStore


class RuntimeProtocolTests(unittest.TestCase):
    def test_awaiting_approval_aliases_to_tool_start(self):
        stream = RuntimeEventStream(runtime_id="handmade", trace_id="trace_1", turn_id="turn_1")

        event, payload = stream.normalize(
            "tool_awaiting_approval",
            {
                "id": "step-1",
                "status": "awaiting_approval",
                "tool": "file_write",
                "args": {"path": "demo.txt"},
            },
        )

        self.assertEqual(event, "tool_start")
        self.assertEqual(payload["protocol_version"], RUNTIME_EVENT_PROTOCOL)
        self.assertEqual(payload["event"], "tool_start")
        self.assertEqual(payload["runtime"], "handmade")
        self.assertEqual(payload["trace_id"], "trace_1")
        self.assertEqual(payload["turn_id"], "turn_1")
        self.assertEqual(payload["step_id"], "step-1")
        self.assertEqual(payload["status"], "awaiting_approval")
        self.assertEqual(payload["args"], {"path": "demo.txt"})

    def test_message_done_normalizes_steps_and_artifacts(self):
        stream = RuntimeEventStream(runtime_id="opencode", trace_id="trace_1", turn_id="turn_1")

        event, payload = stream.normalize(
            "message_done",
            {
                "answer": "done",
                "steps": [{"id": "tool_1", "tool": "bash", "status": "success", "args": {"command": "date"}}],
                "artifacts": [{"id": "diff_1", "type": "file_diff", "data": [{"file": "README.md"}]}],
            },
        )

        self.assertEqual(event, "message_done")
        self.assertEqual(payload["steps"][0]["runtime"], "opencode")
        self.assertEqual(payload["steps"][0]["trace_id"], "trace_1")
        self.assertEqual(payload["artifacts"][0]["protocol_version"], RUNTIME_ARTIFACT_PROTOCOL)
        self.assertEqual(payload["artifacts"][0]["runtime"], "opencode")

    def test_artifact_defaults_are_stable(self):
        artifact = normalize_runtime_artifact({"id": "diag_1", "type": "diagnostic", "data": {"message": "x"}})

        self.assertEqual(artifact["protocol_version"], RUNTIME_ARTIFACT_PROTOCOL)
        self.assertEqual(artifact["title"], "Diagnostic")
        self.assertEqual(artifact["status"], "ready")


class TurnProtocolTests(unittest.TestCase):
    def test_turn_store_creates_protocol_v1_turn(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = TurnStore(Path(temp_dir))
            turn = store.create_turn(
                session_id="session_1",
                runtime_id="handmade",
                model_id="model_1",
                user_message_content="hi",
            )

            self.assertEqual(turn["protocol_version"], RUNTIME_TURN_PROTOCOL)
            self.assertEqual(turn["status"], "running")
            self.assertEqual(turn["side_effect_level"], "none")
            self.assertEqual(turn["event_count"], 0)
            self.assertEqual(turn["artifacts"], [])

            updated = store.record_event(turn["turn_id"], "message_start")
            self.assertEqual(updated["event_count"], 1)
            self.assertEqual(updated["last_event"], "message_start")


if __name__ == "__main__":
    unittest.main()
