import json
import sys
from pathlib import Path

# 添加项目根目录
sys.path.append(str(Path(__file__).parent.parent))

from tools.registry import execute_tool, skill_manager

def test_skill_tool():
    print("Testing SkillTool (Invocable Skills)...")
    
    # 1. 验证技能是否加载
    skill_manager.load_skills() # 确保加载了最新的
    summary = skill_manager.get_invocable_skills_summary()
    print(f"Available Invocable Skills:\n{summary}")
    
    if "git-committer" not in summary:
        print("❌ FAILURE: git-committer not found in invocable skills.")
        return

    # 2. 模拟 LLM 调用 invoke_skill
    print("\nSimulating invoke_skill(skill_name='git-committer')...")
    try:
        result = execute_tool("invoke_skill", {"skill_name": "git-committer"})
        print("Tool Output Status:", result.get("status"))
        instructions = result.get("instructions", "")
        
        if "Git 提交规范专家" in instructions:
            print("✅ SUCCESS: Skill instructions retrieved!")
            
        if "git diff --cached" in instructions or "Dockerfile.backend" in instructions:
            # 说明嵌入式命令执行了（或者至少尝试执行并返回了结果）
            print("✅ SUCCESS: Embedded commands rendered in SkillTool output!")
            # print(instructions[:300] + "...")
        else:
            print("⚠️ WARNING: Embedded commands might not have rendered correctly.")
            print("Instructions snippet:", instructions[:300])
            
    except Exception as e:
        print(f"❌ FAILURE: Error executing SkillTool: {e}")

if __name__ == "__main__":
    test_skill_tool()
