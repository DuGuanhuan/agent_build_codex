import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtimes.base import RuntimeRequest
from runtimes.claude_code import ClaudeCodeRuntime


class FakeStdout:
    def __init__(self, events):
        self.lines = [json.dumps(event, ensure_ascii=False) + "\n" for event in events]
        self.index = 0

    def __iter__(self):
        return self

    def __next__(self):
        if self.index >= len(self.lines):
            raise StopIteration
        line = self.lines[self.index]
        self.index += 1
        return line

    def append_events(self, events):
        self.lines.extend(json.dumps(event, ensure_ascii=False) + "\n" for event in events)


class FakeStdin:
    def __init__(self):
        self.writes = []

    def write(self, value):
        self.writes.append(value)
        return len(value)

    def flush(self):
        return None


class FakeProcess:
    def __init__(self, events, returncode=0):
        self.stdin = FakeStdin()
        self.stdout = FakeStdout(events)
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
        self.start_count = 0

    def _binary_path(self):
        return "/usr/local/bin/claude"

    def _start_process(self, command, env):
        self.start_count += 1
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
        self.assertIn("--input-format", runtime.command)
        self.assertIn("stream-json", runtime.command)
        self.assertIn("现在几号？", runtime.process.stdin.writes[0])
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

    def test_stream_tool_use_delta_updates_args_before_result(self):
        events = [
            system_event("init", session_id="claude-session", model="deepseek-v4-flash"),
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "tool_use", "id": "toolu_question", "name": "AskUserQuestion", "input": {}},
                },
            },
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "input_json_delta", "partial_json": '{"questions":[{"question":"如何处理日志？"}]}'},
                },
            },
            {
                "type": "stream_event",
                "event": {"type": "content_block_stop", "index": 0},
            },
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = FakeClaudeCodeRuntime(events, workspace=temp_dir)
            emitted = []
            with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "sk-test"}, clear=False):
                result = runtime.run(
                    RuntimeRequest(messages=[{"role": "user", "content": "处理一下"}], model_id="deepseek-v4-flash"),
                    event_sink=lambda name, payload: emitted.append((name, payload)),
                )

        step = result.steps[0]
        self.assertEqual(step["tool"], "AskUserQuestion")
        self.assertEqual(step["args"]["questions"][0]["question"], "如何处理日志？")
        self.assertEqual(step["status"], "awaiting_approval")
        self.assertEqual(step["permission"], "user-input")
        self.assertGreaterEqual([name for name, _ in emitted].count("tool_start"), 2)

    def test_answer_user_question_reuses_same_stream_process(self):
        events = [
            system_event("init", session_id="claude-session", model="deepseek-v4-flash"),
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "tool_use", "id": "toolu_question", "name": "AskUserQuestion", "input": {}},
                },
            },
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {
                        "type": "input_json_delta",
                        "partial_json": json.dumps(
                            {
                                "questions": [
                                    {
                                        "question": "如何处理测试文件？",
                                        "header": "Git 处理",
                                        "options": [
                                            {"label": "加入 .gitignore", "description": "跳过测试文件"},
                                            {"label": "全部提交", "description": "提交所有文件"},
                                        ],
                                    }
                                ]
                            },
                            ensure_ascii=False,
                        ),
                    },
                },
            },
            {"type": "stream_event", "event": {"type": "content_block_stop", "index": 0}},
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = FakeClaudeCodeRuntime(events, workspace=temp_dir)
            with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "sk-test"}, clear=False):
                first = runtime.run(
                    RuntimeRequest(
                        messages=[{"role": "user", "content": "处理一下测试文件"}],
                        model_id="deepseek-v4-flash",
                        session_id="local-session",
                    )
                )
                process = runtime.process
                process.stdout.append_events(
                    [
                        system_event("init", session_id="claude-session", model="deepseek-v4-flash"),
                        {"type": "result", "result": "已按你的选择继续"},
                    ]
                )
                second = runtime.run(
                    RuntimeRequest(
                        messages=[
                            {
                                "role": "user",
                                "content": json.dumps(
                                    {
                                        "__system_action": "answer_user_question",
                                        "question": "如何处理测试文件？",
                                        "label": "加入 .gitignore",
                                        "description": "跳过测试文件",
                                        "answer": "加入 .gitignore",
                                    },
                                    ensure_ascii=False,
                                ),
                            }
                        ],
                        model_id="deepseek-v4-flash",
                        session_id="local-session",
                    )
                )

        self.assertEqual(first.steps[0]["status"], "awaiting_approval")
        self.assertEqual(second.answer, "已按你的选择继续")
        self.assertEqual(runtime.start_count, 1)
        self.assertEqual(len(process.stdin.writes), 2)
        self.assertIn("用户已回答 Claude Code 的 AskUserQuestion", process.stdin.writes[1])
        self.assertIn("加入 .gitignore", process.stdin.writes[1])

    def test_stream_task_tool_use_is_displayed_as_subagent_step(self):
        events = [
            system_event("init", session_id="claude-session", model="deepseek-v4-flash"),
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "tool_use", "id": "toolu_task", "name": "Task", "input": {}},
                },
            },
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {
                        "type": "input_json_delta",
                        "partial_json": '{"description":"检查文件","prompt":"列出改动","subagent_type":"Explore"}',
                    },
                },
            },
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": "toolu_task", "content": "完成检查"}],
                },
            },
            {"type": "result", "result": "已完成"},
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = FakeClaudeCodeRuntime(events, workspace=temp_dir)
            with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "sk-test"}, clear=False):
                result = runtime.run(
                    RuntimeRequest(messages=[{"role": "user", "content": "检查"}], model_id="deepseek-v4-flash")
                )

        self.assertEqual(result.steps[0]["tool"], "Task")
        self.assertEqual(result.steps[0]["args"]["subagent_type"], "Explore")
        self.assertEqual(result.steps[0]["status"], "success")

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
