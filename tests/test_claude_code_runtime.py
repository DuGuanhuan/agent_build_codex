import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtimes.base import RuntimeRequest
from runtimes.claude_code import ClaudeCodeRuntime


class FakeProcess:
    def __init__(self, events, returncode=0):
        self.stdout = [json.dumps(event, ensure_ascii=False) + "\n" for event in events]
        self.returncode = returncode
        self.terminated = False

    def wait(self, timeout=None):
        return self.returncode

    def poll(self):
        return None if not self.terminated else self.returncode

    def terminate(self):
        self.terminated = True


class FakeClaudeCodeRuntime(ClaudeCodeRuntime):
    def __init__(self, events, returncode=0, workspace=None):
        super().__init__(Path(workspace or Path.cwd()))
        self.events = events
        self.returncode = returncode
        self.command = None
        self.env = None
        self.process = None

    def _binary_path(self):
        return "/usr/local/bin/claude"

    def _start_process(self, command, env):
        self.command = command
        self.env = env
        self.process = FakeProcess(self.events, self.returncode)
        return self.process


def system_event(subtype, **payload):
    return {"type": "system", "subtype": subtype, **payload}


def assistant_text(text):
    return {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


class ClaudeCodeRuntimeTests(unittest.TestCase):
    def test_run_translates_partial_text_and_tool_events(self):
        events = [
            system_event("init", session_id="claude-session", model="deepseek-v4-flash"),
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {"command": "date"}}],
                },
            },
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "Wed May 6"}],
                },
            },
            assistant_text("现在"),
            assistant_text("现在是 5 月 6 日"),
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = FakeClaudeCodeRuntime(events, workspace=temp_dir)
            emitted = []

            with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "sk-test"}, clear=False):
                result = runtime.run(
                    RuntimeRequest(
                        messages=[{"role": "user", "content": "现在几号？"}],
                        model_id="deepseek-v4-flash",
                        session_id="local-session",
                    ),
                    event_sink=lambda name, payload: emitted.append((name, payload)),
                )

        self.assertIn("--output-format", runtime.command)
        self.assertIn("stream-json", runtime.command)
        self.assertEqual(result.answer, "现在是 5 月 6 日")
        self.assertEqual(result.model, "deepseek-v4-flash")
        self.assertEqual(result.runtime, "claude-code")
        self.assertEqual(result.steps[0]["tool"], "Bash")
        self.assertEqual(result.steps[0]["status"], "success")

        event_names = [name for name, _ in emitted]
        self.assertEqual(event_names[0], "message_start")
        self.assertIn("session_status", event_names)
        self.assertIn("tool_start", event_names)
        self.assertIn("tool_result", event_names)
        self.assertIn("text_delta", event_names)
        self.assertEqual(event_names[-1], "message_done")

    def test_result_event_is_used_when_no_partial_text_arrives(self):
        events = [
            system_event("init", session_id="claude-session", model="deepseek-v4-pro[1m]"),
            {"type": "result", "result": "pong"},
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = FakeClaudeCodeRuntime(events, workspace=temp_dir)

            with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "sk-test"}, clear=False):
                result = runtime.run(RuntimeRequest(messages=[{"role": "user", "content": "ping"}]))

        self.assertEqual(result.answer, "pong")

    def test_resume_uses_persisted_claude_session_id(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = FakeClaudeCodeRuntime([], workspace=temp_dir)
            runtime._set_external_session_id("local-session", "claude-session")

            with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "sk-test"}, clear=False):
                runtime.run(
                    RuntimeRequest(
                        messages=[{"role": "user", "content": "继续"}],
                        model_id="deepseek-v4-pro",
                        session_id="local-session",
                    )
                )

        self.assertIn("--resume", runtime.command)
        self.assertIn("claude-session", runtime.command)

    def test_deepseek_model_maps_to_anthropic_compatible_env(self):
        events = [
            system_event("init", session_id="claude-session", model="deepseek-v4-pro[1m]"),
            {"type": "result", "result": "pong"},
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = FakeClaudeCodeRuntime(events, workspace=temp_dir)
            with patch.dict(
                "os.environ",
                {
                    "DEEPSEEK_API_KEY": "sk-test",
                    "ANTHROPIC_API_KEY": "stale-anthropic-key",
                },
                clear=False,
            ):
                result = runtime.run(
                    RuntimeRequest(
                        messages=[{"role": "user", "content": "ping"}],
                        model_id="deepseek-v4-pro",
                    )
                )

        self.assertEqual(result.answer, "pong")
        self.assertIn("deepseek-v4-pro[1m]", runtime.command)
        self.assertIn("--setting-sources", runtime.command)
        self.assertEqual(runtime.env["ANTHROPIC_BASE_URL"], "https://api.deepseek.com/anthropic")
        self.assertEqual(runtime.env["ANTHROPIC_AUTH_TOKEN"], "sk-test")
        self.assertEqual(runtime.env["ANTHROPIC_API_KEY"], "sk-test")
        self.assertEqual(runtime.env["ANTHROPIC_DEFAULT_SONNET_MODEL"], "deepseek-v4-pro[1m]")
        self.assertEqual(runtime.env["ANTHROPIC_DEFAULT_HAIKU_MODEL"], "deepseek-v4-flash")
        self.assertEqual(runtime.env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"], "1")

    def test_auth_failure_has_clear_error_message(self):
        events = [
            system_event("init", session_id="claude-session", model="deepseek-v4-flash"),
            system_event("api_retry", error_status=401, error="authentication_failed"),
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = FakeClaudeCodeRuntime(events, returncode=1, workspace=temp_dir)

            with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "sk-test"}, clear=False):
                with self.assertRaisesRegex(RuntimeError, "authentication_failed"):
                    runtime.run(RuntimeRequest(messages=[{"role": "user", "content": "hi"}]))

    def test_missing_deepseek_key_has_clear_error_message(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = FakeClaudeCodeRuntime([], workspace=temp_dir)

            with patch.dict("os.environ", {}, clear=True):
                with self.assertRaisesRegex(RuntimeError, "DEEPSEEK_API_KEY"):
                    runtime.run(RuntimeRequest(messages=[{"role": "user", "content": "hi"}]))

    def test_mimo_model_maps_to_anthropic_compatible_env(self):
        events = [
            system_event("init", session_id="claude-session", model="mimo-v2.5-pro"),
            {"type": "result", "result": "pong"},
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = FakeClaudeCodeRuntime(events, workspace=temp_dir)
            with patch.dict(
                "os.environ",
                {
                    "MIMO_API_KEY": "mimo-test",
                    "MIMO_BASE_URL": "https://token-plan-sgp.xiaomimimo.com/v1",
                    "ANTHROPIC_API_KEY": "stale-anthropic-key",
                },
                clear=False,
            ):
                result = runtime.run(
                    RuntimeRequest(
                        messages=[{"role": "user", "content": "ping"}],
                        model_id="mimo-v2.5-pro",
                    )
                )

        self.assertEqual(result.answer, "pong")
        self.assertIn("mimo-v2.5-pro", runtime.command)
        self.assertIn("--setting-sources", runtime.command)
        self.assertEqual(runtime.env["ANTHROPIC_BASE_URL"], "https://token-plan-sgp.xiaomimimo.com/anthropic")
        self.assertEqual(runtime.env["ANTHROPIC_AUTH_TOKEN"], "mimo-test")
        self.assertEqual(runtime.env["ANTHROPIC_API_KEY"], "mimo-test")
        self.assertEqual(runtime.env["ANTHROPIC_DEFAULT_OPUS_MODEL"], "mimo-v2.5-pro")
        self.assertEqual(runtime.env["ANTHROPIC_DEFAULT_SONNET_MODEL"], "mimo-v2.5-pro")
        self.assertEqual(runtime.env["ANTHROPIC_DEFAULT_HAIKU_MODEL"], "mimo-v2.5")

    def test_missing_mimo_key_has_clear_error_message(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = FakeClaudeCodeRuntime([], workspace=temp_dir)

            with patch.dict("os.environ", {}, clear=True):
                with self.assertRaisesRegex(RuntimeError, "MIMO_API_KEY"):
                    runtime.run(RuntimeRequest(messages=[{"role": "user", "content": "hi"}], model_id="mimo-v2.5"))


if __name__ == "__main__":
    unittest.main()
