import json
import os
import shutil
import unittest
from unittest.mock import patch

import server
import tools.registry as tool_registry


class CalculatorTests(unittest.TestCase):
    def test_safe_calculate_supports_basic_math_and_constants(self):
        self.assertEqual(server.safe_calculate("128 * 37"), 4736)
        self.assertAlmostEqual(server.safe_calculate("pi * 2"), 6.283185307179586)
        self.assertEqual(server.safe_calculate("2 ** 8 + 1"), 257)

    def test_safe_calculate_rejects_unsafe_expressions(self):
        with self.assertRaises(server.ToolError):
            server.safe_calculate("__import__('os').system('pwd')")

        with self.assertRaises(server.ToolError):
            server.safe_calculate("1 / 0")


class AgentJsonTests(unittest.TestCase):
    def test_parse_standard_json(self):
        decision = server.parse_agent_json('{"action":"final","answer":"你好"}')
        self.assertEqual(decision, {"action": "final", "answer": "你好"})

    def test_parse_json_code_fence(self):
        decision = server.parse_agent_json('```json\n{"action":"tool","tool":"calculator","args":{"expression":"1+1"}}\n```')
        self.assertEqual(decision["action"], "tool")
        self.assertEqual(decision["tool"], "calculator")
        self.assertEqual(decision["args"], {"expression": "1+1"})

    def test_parse_tool_name_fallback(self):
        decision = server.parse_agent_json('calculator\n{"expression":"2+2"}')
        self.assertEqual(decision, {"action": "tool", "tool": "calculator", "args": {"expression": "2+2"}})

    def test_parse_plain_text_as_final(self):
        decision = server.parse_agent_json("普通回答")
        self.assertEqual(decision, {"action": "final", "answer": "普通回答"})


class ModelConfigTests(unittest.TestCase):
    def test_get_model_config_returns_known_model(self):
        config = server.get_model_config("zhipu-glm-4.7-flash")
        self.assertEqual(config["model"], "glm-4.7-flash")

    def test_get_model_config_rejects_unknown_model(self):
        with self.assertRaises(ValueError):
            server.get_model_config("not-a-model")

    def test_public_model_options_marks_availability_from_env(self):
        with patch.dict(os.environ, {"ZAI_API_KEY": "test-key"}, clear=False):
            models = server.public_model_options()

        zhipu = next(model for model in models if model["id"] == "zhipu-glm-4.7-flash")
        self.assertTrue(zhipu["available"])

    def test_public_model_options_exposes_context_window(self):
        models = server.public_model_options()

        zhipu = next(model for model in models if model["id"] == "zhipu-glm-4.7-flash")
        deepseek = next(model for model in models if model["id"] == "deepseek-v4-flash")
        self.assertEqual(zhipu["context_window_tokens"], 200000)
        self.assertEqual(deepseek["context_window_tokens"], 1000000)
        self.assertEqual(zhipu["reserved_output_tokens"], server.LLM_MAX_TOKENS)


class ToolTests(unittest.TestCase):
    def test_run_tool_current_time(self):
        result = server.run_tool("current_time", {"timezone": "Asia/Shanghai"})
        self.assertEqual(result["timezone"], "Asia/Shanghai")
        self.assertIn("timestamp", result)
        self.assertIn("local_time", result)

    def test_run_tool_calculator(self):
        self.assertEqual(server.run_tool("calculator", {"expression": "12 * 7"})["result"], 84)

    def test_execute_tool_step_success_shape(self):
        step, result = server.execute_tool_step(1, "calculator", {"expression": "3 * 5"})
        self.assertEqual(result["result"], 15)
        self.assertEqual(step["id"], "step-1")
        self.assertEqual(step["status"], "success")
        self.assertEqual(step["error"], None)
        self.assertIsInstance(step["duration_ms"], int)

    def test_execute_tool_step_error_shape(self):
        step, result = server.execute_tool_step(1, "missing_tool", {})
        self.assertEqual(step["type"], "tool_error")
        self.assertEqual(step["status"], "error")
        self.assertEqual(result, {"error": "未知工具：missing_tool"})
        self.assertEqual(step["error"], "未知工具：missing_tool")


class ContextSummaryTests(unittest.TestCase):
    def test_clean_chat_messages_preserves_summary_when_trimming(self):
        messages = [
            {"role": "user", "content": "以下是此前会话摘要，用于延续上下文：\n旧目标"},
            *[{"role": "user", "content": f"消息 {index}"} for index in range(30)],
        ]

        cleaned = server.clean_chat_messages(messages, max_messages=6)

        self.assertEqual(len(cleaned), 6)
        self.assertEqual(cleaned[0]["content"], "以下是此前会话摘要，用于延续上下文：\n旧目标")
        self.assertEqual(cleaned[-1]["content"], "消息 29")

    def test_clean_chat_messages_trims_recent_messages_without_summary(self):
        messages = [{"role": "user", "content": f"消息 {index}"} for index in range(30)]

        cleaned = server.clean_chat_messages(messages, max_messages=6)

        self.assertEqual([message["content"] for message in cleaned], [f"消息 {index}" for index in range(24, 30)])

    def test_build_summary_messages_keeps_all_messages_to_summarize(self):
        messages = [{"role": "user", "content": f"历史 {index}"} for index in range(20)]

        summary_messages = server.build_summary_messages(messages, "旧摘要")
        summary_input = summary_messages[1]["content"]

        self.assertIn("旧摘要", summary_input)
        self.assertIn("历史 0", summary_input)
        self.assertIn("历史 19", summary_input)

    def test_summarize_conversation_uses_selected_model(self):
        with patch.object(server, "llm_chat", return_value="更新后的摘要") as llm_chat:
            result = server.summarize_conversation(
                [{"role": "user", "content": "继续做 Phase 4"}],
                "zhipu-glm-4.7-flash",
                "旧摘要",
            )

        self.assertEqual(result, {"summary": "更新后的摘要", "model": "zhipu-glm-4.7-flash"})
        self.assertEqual(llm_chat.call_args.args[1]["id"], "zhipu-glm-4.7-flash")

    def test_estimate_context_usage_uses_model_token_window(self):
        result = server.estimate_context_usage(
            [{"role": "user", "content": "你好，帮我继续实现上下文压缩。"}],
            "zhipu-glm-4.7-flash",
        )

        self.assertEqual(result["model"], "zhipu-glm-4.7-flash")
        self.assertEqual(result["context_window_tokens"], 200000)
        self.assertEqual(result["available_input_tokens"], 200000 - server.LLM_MAX_TOKENS)
        self.assertGreater(result["input_tokens"], 100)
        self.assertGreater(result["ratio"], 0)

    def test_estimate_text_tokens_counts_chinese_and_english_differently(self):
        self.assertGreater(server.estimate_text_tokens("你好世界"), server.estimate_text_tokens("abcd"))


class ToolRegistryTests(unittest.TestCase):
    def test_tools_schema_exposes_registered_tools(self):
        names = {tool["name"] for tool in tool_registry.get_tools_schema()}
        self.assertTrue({"current_time", "calculator", "file_read", "repo_search", "web_fetch"}.issubset(names))

    def test_file_read_reads_workspace_file(self):
        result = server.run_tool("file_read", {"path": "README.md"})
        self.assertEqual(result["path"], "README.md")
        self.assertIn("# Handmade LLM Agent", result["content"])
        self.assertFalse(result["truncated"])

    def test_file_read_rejects_absolute_or_outside_path(self):
        with self.assertRaises(server.ToolError):
            server.run_tool("file_read", {"path": "/etc/passwd"})

        with self.assertRaises(server.ToolError):
            server.run_tool("file_read", {"path": "../outside.txt"})

    @unittest.skipUnless(shutil.which("rg"), "ripgrep is required for repo_search")
    def test_repo_search_finds_code(self):
        result = server.run_tool("repo_search", {"query": "build_agent_system_prompt", "max_results": 5})
        self.assertGreaterEqual(result["count"], 1)
        self.assertTrue(any(match["path"] == "server.py" for match in result["matches"]))

    def test_web_fetch_reads_text_response(self):
        class FakeHeaders(dict):
            def get(self, key, default=None):
                return super().get(key, default)

        class FakeResponse:
            headers = FakeHeaders({"Content-Type": "text/html; charset=utf-8"})

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self, max_size):
                del max_size
                return b"<html><head><title>Hello</title></head><body><h1>Hi</h1><script>bad()</script></body></html>"

        with patch.object(tool_registry.urllib.request, "urlopen", return_value=FakeResponse()):
            result = server.run_tool("web_fetch", {"url": "https://example.com"})

        self.assertEqual(result["title"], "Hello")
        self.assertIn("Hi", result["content"])
        self.assertNotIn("bad()", result["content"])

    def test_web_fetch_rejects_local_targets(self):
        for url in ("http://localhost:3000", "http://127.0.0.1:8000", "http://service.internal"):
            with self.subTest(url=url):
                with self.assertRaises(server.ToolError):
                    server.run_tool("web_fetch", {"url": url})


class AgentRunnerTests(unittest.TestCase):
    def test_run_agent_final_response(self):
        with patch.object(server, "llm_chat", return_value=json.dumps({"action": "final", "answer": "完成"})):
            result = server.run_agent([{"role": "user", "content": "你好"}], "zhipu-glm-4.7-flash")

        self.assertEqual(result["answer"], "完成")
        self.assertEqual(result["steps"], [])
        self.assertTrue(result["trace_id"].startswith("trace_"))

    def test_run_agent_tool_then_final(self):
        responses = [
            json.dumps({"action": "tool", "tool": "calculator", "args": {"expression": "6 * 7"}}),
            json.dumps({"action": "final", "answer": "6 * 7 = 42"}),
        ]

        with patch.object(server, "llm_chat", side_effect=responses):
            result = server.run_agent([{"role": "user", "content": "算一下 6*7"}], "zhipu-glm-4.7-flash")

        self.assertEqual(result["answer"], "6 * 7 = 42")
        self.assertEqual(len(result["steps"]), 1)
        self.assertEqual(result["steps"][0]["status"], "success")
        self.assertEqual(result["steps"][0]["result"]["result"], 42)

    def test_run_agent_emits_stream_events(self):
        responses = [
            json.dumps({"action": "tool", "tool": "calculator", "args": {"expression": "2 + 3"}}),
            json.dumps({"action": "final", "answer": "2 + 3 = 5"}),
        ]
        events = []

        def event_sink(event, payload):
            events.append((event, payload))

        def fake_stream(messages, model_config, on_delta, temperature=0.2):
            del messages, model_config, temperature
            on_delta("2 + ")
            on_delta("3 = 5")
            return "2 + 3 = 5"

        with patch.object(server, "llm_chat", side_effect=responses), patch.object(
            server, "llm_chat_stream", side_effect=fake_stream
        ):
            result = server.run_agent(
                [{"role": "user", "content": "算一下 2+3"}],
                "zhipu-glm-4.7-flash",
                event_sink=event_sink,
            )

        event_names = [event for event, _ in events]
        self.assertEqual(event_names[0], "message_start")
        self.assertIn("tool_start", event_names)
        self.assertIn("tool_result", event_names)
        self.assertIn("text_delta", event_names)
        self.assertEqual(event_names[-1], "message_done")
        self.assertEqual(result["answer"], "2 + 3 = 5")


if __name__ == "__main__":
    unittest.main()
