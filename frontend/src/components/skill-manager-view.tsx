"use client";

import { useEffect, useState } from "react";
import { 
  Plus, 
  Trash2, 
  Save, 
  Zap, 
  BookOpen,
} from "lucide-react";
import type { SkillOption, ToolOption } from "@/lib/types";
import { cn } from "@/lib/utils";

export function SkillManagerView() {
  const [skills, setSkills] = useState<SkillOption[]>([]);
  const [tools, setTools] = useState<ToolOption[]>([]);
  const [selectedSkill, setSelectedSkill] = useState<SkillOption | null>(null);
  const [activeTab, setActiveTab] = useState<"skills" | "tools">("skills");
  const [isNew, setIsNew] = useState(false);

  // 编辑状态
  const [editName, setEditName] = useState("");
  const [editDesc, setEditDesc] = useState("");
  const [editType, setEditType] = useState<"hook" | "invocable">("hook");
  const [editInstructions, setEditInstructions] = useState("");
  const [editPaths, setEditPaths] = useState("");
  const [editTriggers, setEditTriggers] = useState("");

  async function fetchSkillManagerData() {
    const [skillsRes, toolsRes] = await Promise.all([
      fetch("/api/skills"),
      fetch("/api/tools")
    ]);
    const skillsData = await skillsRes.json();
    const toolsData = await toolsRes.json();
    return {
      skills: skillsData.skills || [],
      tools: toolsData.tools || [],
    };
  }

  const loadData = async () => {
    const data = await fetchSkillManagerData();
    setSkills(data.skills);
    setTools(data.tools);
  };

  useEffect(() => {
    let ignore = false;

    fetchSkillManagerData()
      .then((data) => {
        if (!ignore) {
          setSkills(data.skills);
          setTools(data.tools);
        }
      })
      .catch((error) => {
        console.error("Failed to load skills/tools:", error);
      });

    return () => {
      ignore = true;
    };
  }, []);

  const handleSelectSkill = (skill: SkillOption) => {
    setSelectedSkill(skill);
    setIsNew(false);
    setEditName(skill.name);
    setEditDesc(skill.description);
    setEditType(skill.type);
    setEditInstructions(skill.instructions);
    setEditPaths(skill.paths.join(", "));
    setEditTriggers(skill.trigger_words.join(", "));
  };

  const handleNewSkill = () => {
    setSelectedSkill(null);
    setIsNew(true);
    setEditName("");
    setEditDesc("");
    setEditType("hook");
    setEditInstructions("");
    setEditPaths("");
    setEditTriggers("");
  };

  const handleSave = async () => {
    const payload = {
      name: editName,
      meta: {
        description: editDesc,
        type: editType,
        paths: editPaths.split(",").map(s => s.trim()).filter(Boolean),
        trigger_words: editTriggers.split(",").map(s => s.trim()).filter(Boolean)
      },
      instructions: editInstructions
    };

    try {
      const res = await fetch("/api/skills", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (res.ok) {
        await loadData();
        setIsNew(false);
      }
    } catch {
      alert("保存失败");
    }
  };

  const handleDelete = async (name: string) => {
    if (!confirm(`确定要删除技能 "${name}" 吗？`)) return;
    try {
      const res = await fetch(`/api/skills/${name}`, { method: "DELETE" });
      if (res.ok) {
        setSelectedSkill(null);
        await loadData();
      }
    } catch {
      alert("删除失败");
    }
  };

  return (
    <div className="flex h-full flex-col bg-white">
      <header className="flex h-14 shrink-0 items-center justify-between border-b border-stone-200 px-6">
        <div className="flex items-center gap-4">
          <h2 className="text-lg font-bold">技能与工具管理</h2>
          <div className="flex rounded-lg bg-stone-100 p-1">
            <button
              onClick={() => setActiveTab("skills")}
              className={cn(
                "px-3 py-1 text-xs font-bold transition rounded-md",
                activeTab === "skills" ? "bg-white shadow-sm text-stone-900" : "text-stone-500 hover:text-stone-700"
              )}
            >
              技能库 (Skills)
            </button>
            <button
              onClick={() => setActiveTab("tools")}
              className={cn(
                "px-3 py-1 text-xs font-bold transition rounded-md",
                activeTab === "tools" ? "bg-white shadow-sm text-stone-900" : "text-stone-500 hover:text-stone-700"
              )}
            >
              工具清单 (Tools)
            </button>
          </div>
        </div>
      </header>

      <main className="flex min-h-0 flex-1 overflow-hidden">
        {activeTab === "skills" ? (
          <>
            {/* 技能列表 */}
            <div className="w-80 shrink-0 border-r border-stone-200 bg-stone-50/50 overflow-y-auto">
              <div className="p-4">
                <button
                  onClick={handleNewSkill}
                  className="flex w-full items-center justify-center gap-2 rounded-lg bg-stone-900 py-2 text-sm font-bold text-white transition hover:bg-stone-800"
                >
                  <Plus className="h-4 w-4" />
                  新建技能
                </button>
              </div>
              <div className="px-2 pb-4">
                {skills.map((skill) => (
                  <button
                    key={skill.name}
                    onClick={() => handleSelectSkill(skill)}
                    className={cn(
                      "group flex w-full flex-col gap-1 rounded-xl p-3 text-left transition",
                      selectedSkill?.name === skill.name ? "bg-white shadow-sm ring-1 ring-stone-200" : "hover:bg-stone-100"
                    )}
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-bold text-stone-900">{skill.name}</span>
                      <span className={cn(
                        "rounded px-1.5 py-0.5 text-[10px] font-bold uppercase",
                        skill.type === "hook" ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700"
                      )}>
                        {skill.type}
                      </span>
                    </div>
                    <p className="line-clamp-2 text-xs text-stone-500">{skill.description}</p>
                  </button>
                ))}
              </div>
            </div>

            {/* 编辑区域 */}
            <div className="flex min-w-0 flex-1 flex-col bg-white overflow-y-auto">
              {selectedSkill || isNew ? (
                <div className="mx-auto w-full max-w-3xl p-8">
                  <div className="mb-8 flex items-center justify-between">
                    <div>
                      <h3 className="text-2xl font-bold">{isNew ? "新建技能" : "编辑技能"}</h3>
                      <p className="text-sm text-stone-500">配置技能的激活规则和指令集</p>
                    </div>
                    <div className="flex gap-2">
                      {!isNew && (
                        <button
                          onClick={() => handleDelete(selectedSkill!.name)}
                          className="flex items-center gap-2 rounded-lg border border-stone-200 px-4 py-2 text-sm font-bold text-rose-600 transition hover:bg-rose-50"
                        >
                          <Trash2 className="h-4 w-4" />
                          删除
                        </button>
                      )}
                      <button
                        onClick={handleSave}
                        className="flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-bold text-white transition hover:bg-emerald-700"
                      >
                        <Save className="h-4 w-4" />
                        保存配置
                      </button>
                    </div>
                  </div>

                  <div className="grid gap-6">
                    <div className="grid gap-2">
                      <label className="text-sm font-bold text-stone-700">技能名称</label>
                      <input
                        value={editName}
                        onChange={(e) => setEditName(e.target.value)}
                        placeholder="例如: python-expert"
                        className="rounded-lg border border-stone-200 bg-white px-4 py-2 text-sm outline-none focus:border-emerald-500"
                        disabled={!isNew}
                      />
                    </div>

                    <div className="grid gap-2">
                      <label className="text-sm font-bold text-stone-700">简介说明</label>
                      <input
                        value={editDesc}
                        onChange={(e) => setEditDesc(e.target.value)}
                        placeholder="简短描述这个技能的作用"
                        className="rounded-lg border border-stone-200 bg-white px-4 py-2 text-sm outline-none focus:border-emerald-500"
                      />
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                      <div className="grid gap-2">
                        <label className="text-sm font-bold text-stone-700">激活类型</label>
                        <select
                          value={editType}
                          onChange={(e) => {
                            const value = e.target.value;
                            if (value === "hook" || value === "invocable") {
                              setEditType(value);
                            }
                          }}
                          className="rounded-lg border border-stone-200 bg-white px-3 py-2 text-sm outline-none focus:border-emerald-500"
                        >
                          <option value="hook">Hooks (自动感应)</option>
                          <option value="invocable">Invocable (主动调用)</option>
                        </select>
                      </div>
                      <div className="grid gap-2">
                        <label className="text-sm font-bold text-stone-700">文件路径模式 (Hooks 专用)</label>
                        <input
                          value={editPaths}
                          onChange={(e) => setEditPaths(e.target.value)}
                          placeholder="*.py, src/**/*.js"
                          className="rounded-lg border border-stone-200 bg-white px-4 py-2 text-sm outline-none focus:border-emerald-500"
                          disabled={editType !== "hook"}
                        />
                      </div>
                    </div>

                    <div className="grid gap-2">
                      <label className="text-sm font-bold text-stone-700">触发关键词 (选填)</label>
                      <input
                        value={editTriggers}
                        onChange={(e) => setEditTriggers(e.target.value)}
                        placeholder="python, refactor, commit"
                        className="rounded-lg border border-stone-200 bg-white px-4 py-2 text-sm outline-none focus:border-emerald-500"
                      />
                    </div>

                    <div className="grid gap-2">
                      <div className="flex items-center justify-between">
                        <label className="text-sm font-bold text-stone-700">核心指令 (Markdown)</label>
                        <span className="text-[10px] text-stone-400">支持 !`cmd` 语法执行实时命令</span>
                      </div>
                      <textarea
                        value={editInstructions}
                        onChange={(e) => setEditInstructions(e.target.value)}
                        rows={12}
                        className="font-mono rounded-lg border border-stone-200 bg-white px-4 py-3 text-sm leading-6 outline-none focus:border-emerald-500"
                        placeholder="### 技能指令\n\n1. 准则一\n2. 准则二..."
                      />
                    </div>
                  </div>
                </div>
              ) : (
                <div className="flex flex-1 flex-col items-center justify-center text-stone-400">
                  <BookOpen className="mb-4 h-12 w-12 opacity-20" />
                  <p>请选择一个技能进行编辑，或点击“新建技能”</p>
                </div>
              )}
            </div>
          </>
        ) : (
          /* 工具能力查看 (Read-only) */
          <div className="flex flex-1 flex-col overflow-y-auto bg-stone-50/30 p-8">
            <div className="mx-auto w-full max-w-4xl">
              <div className="mb-8">
                <h3 className="text-2xl font-bold">工具能力清单</h3>
                <p className="text-sm text-stone-500">这些是 Agent 当前拥有的底层原子能力，受安全策略严格管控。</p>
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                {tools.map((tool) => (
                  <div key={tool.name} className="flex flex-col gap-3 rounded-2xl border border-stone-200 bg-white p-5 shadow-sm transition hover:shadow-md">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <div className="grid h-8 w-8 place-items-center rounded-lg bg-stone-100 text-stone-600">
                          <Zap className="h-4 w-4" />
                        </div>
                        <span className="font-bold text-stone-900">{tool.name}</span>
                      </div>
                      <span className={cn(
                        "rounded-full px-2 py-0.5 text-[10px] font-bold uppercase",
                        tool.permission.includes("safe") ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700"
                      )}>
                        {tool.permission}
                      </span>
                    </div>
                    <p className="text-xs leading-5 text-stone-600">{tool.description}</p>
                    
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {tool.parameters.required?.map(p => (
                        <span key={p} className="rounded bg-stone-100 px-1.5 py-0.5 text-[10px] font-medium text-stone-500">
                          {p} (必填)
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
