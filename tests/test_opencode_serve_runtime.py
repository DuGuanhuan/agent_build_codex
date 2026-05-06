import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtimes.base import RuntimeRequest
from runtimes.opencode_serve import OpenCodeServeRuntime


class FakeSseResponse:
    def __init__(self, events):
        frames = []
        for event in events:
            frames.append(f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode("utf-8"))
        self.lines = []
        for frame in frames:
            self.lines.extend(frame.splitlines(keepends=True))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def readline(self):
        if not self.lines:
            return b""
        return self.lines.pop(0)


class FakeOpenCodeServeRuntime(OpenCodeServeRuntime):
    def __init__(self, events, workspace=None):
        super().__init__(Path(workspace or Path.cwd()))
        self.events = events
        self.sent_prompt = None
        self.diff_payload = None
        self.todo_payload = None
        self.aborted_session_id = None

    def _ensure_server(self):
        return True

    def _session_for(self, local_session_id, title):
        self.local_session_id = local_session_id
        self.title = title
        self._session_map[local_session_id] = "ses_test"
        return "ses_test"

    def _send_prompt(self, session_id, prompt, model):
        self.sent_prompt = {
            "session_id": session_id,
            "prompt": prompt,
            "model": model,
        }

    def _open_event_stream(self):
        return FakeSseResponse(self.events)

    def _session_diff(self, runtime_session_id):
        return self.diff_payload

    def _session_todo(self, runtime_session_id):
        return self.todo_payload

    def _abort(self, session_id):
        self.aborted_session_id = session_id


def event(event_type, properties):
    return {"type": event_type, "properties": properties}


class OpenCodeServeRuntimeTests(unittest.TestCase):
    def test_model_mapping(self):
        runtime = FakeOpenCodeServeRuntime([])

        self.assertEqual(
            runtime._model("deepseek-v4-pro"),
            {"providerID": "deepseek", "modelID": "deepseek-v4-pro"},
        )
        self.assertEqual(
            runtime._model("deepseek-v4-pro-thinking"),
            {"providerID": "deepseek", "modelID": "deepseek-reasoner"},
        )

    def test_env_model_overrides_model_mapping(self):
        runtime = FakeOpenCodeServeRuntime([])

        with patch.dict("os.environ", {"OPENCODE_MODEL": "deepseek/deepseek-v4-flash"}):
            self.assertEqual(
                runtime._model("deepseek-v4-pro"),
                {"providerID": "deepseek", "modelID": "deepseek-v4-flash"},
            )

    def test_run_translates_text_and_tool_events(self):
        events = [
            event(
                "message.part.updated",
                {
                    "part": {
                        "id": "prt_tool",
                        "sessionID": "ses_test",
                        "messageID": "msg_assistant",
                        "type": "tool",
                        "callID": "call_date",
                        "tool": "bash",
                        "state": {
                            "status": "running",
                            "input": {"command": "date"},
                            "time": {"start": 1000},
                        },
                    }
                },
            ),
            event(
                "message.part.updated",
                {
                    "part": {
                        "id": "prt_tool",
                        "sessionID": "ses_test",
                        "messageID": "msg_assistant",
                        "type": "tool",
                        "callID": "call_date",
                        "tool": "bash",
                        "state": {
                            "status": "completed",
                            "input": {"command": "date"},
                            "output": "Wed May 6 00:28:22 CST 2026\n",
                            "metadata": {"exit": 0},
                            "time": {"start": 1000, "end": 1025},
                        },
                    }
                },
            ),
            event(
                "message.part.updated",
                {
                    "part": {
                        "id": "prt_text",
                        "sessionID": "ses_test",
                        "messageID": "msg_assistant",
                        "type": "text",
                        "text": "现在是",
                    },
                    "delta": "现在是",
                },
            ),
            event(
                "message.part.updated",
                {
                    "part": {
                        "id": "prt_text",
                        "sessionID": "ses_test",
                        "messageID": "msg_assistant",
                        "type": "text",
                        "text": "现在是 00:28",
                    },
                    "delta": " 00:28",
                },
            ),
            event("session.idle", {"sessionID": "ses_test"}),
        ]
        runtime = FakeOpenCodeServeRuntime(events)
        emitted = []

        result = runtime.run(
            RuntimeRequest(
                messages=[{"role": "user", "content": "现在几点了？"}],
                model_id="deepseek-v4-pro",
                session_id="local_session",
            ),
            event_sink=lambda name, payload: emitted.append((name, payload)),
        )

        self.assertEqual(runtime.sent_prompt["prompt"], "现在几点了？")
        self.assertEqual(runtime.sent_prompt["model"], {"providerID": "deepseek", "modelID": "deepseek-v4-pro"})
        self.assertEqual(result.answer, "现在是 00:28")
        self.assertEqual(result.runtime, "opencode")
        self.assertEqual(result.steps[0]["tool"], "bash")
        self.assertEqual(result.steps[0]["status"], "success")
        self.assertEqual(result.steps[0]["duration_ms"], 25)

        event_names = [name for name, _ in emitted]
        self.assertEqual(event_names[0], "message_start")
        self.assertEqual(emitted[0][1]["session_ref"]["runtime_session_id"], "ses_test")
        self.assertIn("session_status", event_names)
        self.assertIn("tool_start", event_names)
        self.assertIn("tool_result", event_names)
        self.assertIn("text_delta", event_names)
        self.assertEqual(event_names[-1], "message_done")

    def test_ignores_events_from_other_sessions(self):
        events = [
            event(
                "message.part.updated",
                {
                    "part": {
                        "id": "prt_text",
                        "sessionID": "ses_other",
                        "messageID": "msg_assistant",
                        "type": "text",
                        "text": "不应该出现",
                    },
                    "delta": "不应该出现",
                },
            ),
            event(
                "message.part.updated",
                {
                    "part": {
                        "id": "prt_text",
                        "sessionID": "ses_test",
                        "messageID": "msg_assistant",
                        "type": "text",
                        "text": "正确",
                    },
                    "delta": "正确",
                },
            ),
            event("session.idle", {"sessionID": "ses_test"}),
        ]
        runtime = FakeOpenCodeServeRuntime(events)

        result = runtime.run(RuntimeRequest(messages=[{"role": "user", "content": "hi"}]))

        self.assertEqual(result.answer, "正确")

    def test_run_emits_artifacts_from_diff_and_todo(self):
        runtime = FakeOpenCodeServeRuntime([event("session.idle", {"sessionID": "ses_test"})])
        runtime.diff_payload = {"files": [{"path": "README.md", "patch": "@@ changed"}]}
        runtime.todo_payload = [{"title": "实现 Diff panel", "status": "done"}]
        emitted = []

        result = runtime.run(
            RuntimeRequest(messages=[{"role": "user", "content": "改 README"}], session_id="local_session"),
            event_sink=lambda name, payload: emitted.append((name, payload)),
        )

        self.assertEqual([artifact["type"] for artifact in result.artifacts], ["file_diff", "todo"])
        artifact_events = [payload["artifact"]["type"] for name, payload in emitted if name == "artifact_updated"]
        self.assertEqual(artifact_events, ["file_diff", "todo"])
        self.assertIn("session_diff", [name for name, _ in emitted])
        self.assertIn("session_todo", [name for name, _ in emitted])

    def test_run_translates_session_diff_and_todo_events(self):
        events = [
            event(
                "session.diff",
                {
                    "sessionID": "ses_test",
                    "diff": [
                        {
                            "file": "README.md",
                            "before": "old\n",
                            "after": "new\n",
                            "additions": 1,
                            "deletions": 1,
                            "status": "modified",
                        }
                    ],
                },
            ),
            event(
                "todo.updated",
                {
                    "sessionID": "ses_test",
                    "todos": [{"content": "review diff", "status": "pending", "priority": "medium", "id": "todo_1"}],
                },
            ),
            event("session.idle", {"sessionID": "ses_test"}),
        ]
        runtime = FakeOpenCodeServeRuntime(events)
        emitted = []

        result = runtime.run(
            RuntimeRequest(messages=[{"role": "user", "content": "hi"}], session_id="local_session"),
            event_sink=lambda name, payload: emitted.append((name, payload)),
        )

        self.assertEqual([artifact["type"] for artifact in result.artifacts], ["file_diff", "todo"])
        self.assertIn("session_diff", [name for name, _ in emitted])
        self.assertIn("session_todo", [name for name, _ in emitted])

    def test_run_synthesizes_diff_for_bash_created_untracked_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=workspace, check=True, stdout=subprocess.DEVNULL)
            (workspace / "new_file.txt").write_text("hello from bash\n", encoding="utf-8")
            events = [
                event(
                    "message.part.updated",
                    {
                        "part": {
                            "id": "prt_tool",
                            "sessionID": "ses_test",
                            "messageID": "msg_assistant",
                            "type": "tool",
                            "callID": "call_write",
                            "tool": "bash",
                            "state": {
                                "status": "completed",
                                "input": {"command": "cat > new_file.txt <<'EOF'\nhello from bash\nEOF"},
                                "output": "",
                                "metadata": {"exit": 0},
                            },
                        }
                    },
                ),
                event("session.idle", {"sessionID": "ses_test"}),
            ]
            runtime = FakeOpenCodeServeRuntime(events, workspace)

            result = runtime.run(
                RuntimeRequest(messages=[{"role": "user", "content": "create file"}], session_id="local_session")
            )

        diff_artifact = next(artifact for artifact in result.artifacts if artifact["type"] == "file_diff")
        self.assertEqual(diff_artifact["data"][0]["file"], "new_file.txt")
        self.assertEqual(diff_artifact["data"][0]["status"], "added")
        self.assertIn("hello from bash", diff_artifact["data"][0]["after"])

    def test_abort_maps_local_session_to_opencode_session(self):
        runtime = FakeOpenCodeServeRuntime([])
        runtime._session_for("local_session", "title")

        self.assertTrue(runtime.abort("local_session"))
        self.assertEqual(runtime.aborted_session_id, "ses_test")
        self.assertFalse(runtime.abort("missing_session"))


if __name__ == "__main__":
    unittest.main()
