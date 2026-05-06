import json
import sys
from pathlib import Path

# 添加项目根目录
sys.path.append(str(Path(__file__).parent.parent))

from server import run_agent, skill_manager

def mock_event_sink(event, payload):
    if event == "message_start":
        print(f"--- Event: {event} ---")
        print(f"Model: {payload.get('model')}")
    elif event == "tool_start":
        print(f"--- Event: {event} ---")
        print(f"Tool: {payload.get('tool')}")
    elif event == "message_done":
        print(f"--- Event: {event} ---")

def test_skill_injection():
    print("Testing Skill Injection...")
    
    # 1. 模拟一个提及 Python 文件的用户消息
    messages = [
        {"role": "user", "content": "请帮我检查一下 main.py 这个文件。"}
    ]
    
    # 我们不真正调用 LLM，而是通过拦截 build_agent_input_messages 来观察
    import server
    original_build = server.build_agent_input_messages
    
    captured_prompt = ""
    def mocked_build(user_msgs, context_paths=None):
        nonlocal captured_prompt
        msgs = original_build(user_msgs, context_paths)
        captured_prompt = msgs[0]["content"]
        return msgs
    
    server.build_agent_input_messages = mocked_build
    
    # 模拟运行 Agent (这里可能会因为没配置 API Key 报错，但我们只关心 build 阶段)
    try:
        run_agent(messages, model_id="zhipu-glm-4.7-flash", event_sink=mock_event_sink)
    except Exception as e:
        # 忽略网络错误，只要 build 跑过了就行
        pass
    
    print("\nCaptured System Prompt Snippet:")
    if "ACTIVE SKILLS INSTRUCTIONS" in captured_prompt:
        print("✅ SUCCESS: Skill instructions found in prompt!")
        # 打印包含 ls 结果的那部分
        start_idx = captured_prompt.find("--- Skill: python-expert ---")
        print(captured_prompt[start_idx:start_idx+500])
    else:
        print("❌ FAILURE: No skill instructions in prompt.")
        print("Prompt was:", captured_prompt[:200] + "...")

if __name__ == "__main__":
    test_skill_injection()
