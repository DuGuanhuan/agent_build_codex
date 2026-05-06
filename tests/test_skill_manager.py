import unittest
import os
import sys
from pathlib import Path

# 添加项目根目录到 sys.path
sys.path.append(str(Path(__file__).parent.parent))

from skills.manager import SkillManager

class TestSkillManager(unittest.TestCase):
    def setUp(self):
        # 使用隔离的测试目录
        self.test_skills_dir = Path("tests/test_skills")
        self.test_skills_dir.mkdir(parents=True, exist_ok=True)
        
        # 创建一个模拟 Python 技能
        self.py_skill_dir = self.test_skills_dir / "test-py-expert"
        self.py_skill_dir.mkdir(exist_ok=True)
        
        with open(self.py_skill_dir / "skill.yaml", "w") as f:
            f.write('name: "test-py"\ntype: "hook"\npaths:\n- "*.py"\n- "src/*.py"')
        
        with open(self.py_skill_dir / "instructions.md", "w") as f:
            f.write("Python Expert Instructions")

    def test_load_skills(self):
        manager = SkillManager(skills_dir=str(self.test_skills_dir))
        self.assertIn("test-py", manager.skills)
        skill = manager.skills["test-py"]
        self.assertEqual(skill.type, "hook")
        self.assertIn("*.py", skill.path_patterns)

    def test_path_matching(self):
        manager = SkillManager(skills_dir=str(self.test_skills_dir))
        
        # 匹配 .py 文件
        active = manager.get_active_hooks(["main.py"])
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].name, "test-py")
        
        # 不匹配 .txt 文件
        active_none = manager.get_active_hooks(["README.md"])
        self.assertEqual(len(active_none), 0)

    def test_instruction_blob(self):
        manager = SkillManager(skills_dir=str(self.test_skills_dir))
        blob = manager.get_skill_instructions_blob(["script.py"])
        self.assertIn("Python Expert Instructions", blob)
        self.assertIn("test-py", blob)

if __name__ == "__main__":
    unittest.main()
