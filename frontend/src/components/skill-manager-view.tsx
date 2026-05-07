"use client";

import { useEffect, useMemo, useState } from "react";
import {
  BookOpen,
  Bot,
  Layers3,
  Lock,
  Pencil,
  Plus,
  Save,
  Trash2,
  Wrench,
  Zap,
} from "lucide-react";
import type { RuntimeCatalogOption, SkillOption, ToolOption } from "@/lib/types";
import { cn } from "@/lib/utils";

type CatalogResponse = {
  skills?: SkillOption[];
  tools?: ToolOption[];
  runtimes?: RuntimeCatalogOption[];
  default?: string;
};

type ActiveTab = "skills" | "tools";
type EditableSkillType = "hook" | "invocable";

const ALL_RUNTIMES = "all";
const HANDMADE_RUNTIME = "handmade";

function runtimeLabel(runtimeId?: string, runtimes: RuntimeCatalogOption[] = []) {
  if (!runtimeId) return "Unknown";
  return runtimes.find((runtime) => runtime.id === runtimeId)?.label || runtimeId;
}

function isEditableSkill(skill: SkillOption | null) {
  return Boolean(skill && skill.runtime === HANDMADE_RUNTIME && skill.editable !== false && !skill.native);
}

function skillTypeLabel(type: string) {
  if (type === "hook") return "HOOK";
  if (type === "invocable") return "INVOKE";
  if (type === "native") return "NATIVE";
  return type.toUpperCase();
}

function normalizeEditableType(type: string): EditableSkillType {
  return type === "invocable" ? "invocable" : "hook";
}

export function SkillManagerView() {
  const [skills, setSkills] = useState<SkillOption[]>([]);
  const [tools, setTools] = useState<ToolOption[]>([]);
  const [runtimes, setRuntimes] = useState<RuntimeCatalogOption[]>([]);
  const [selectedSkill, setSelectedSkill] = useState<SkillOption | null>(null);
  const [selectedRuntimeId, setSelectedRuntimeId] = useState(ALL_RUNTIMES);
  const [activeTab, setActiveTab] = useState<ActiveTab>("skills");
  const [isNew, setIsNew] = useState(false);

  const [editName, setEditName] = useState("");
  const [editDesc, setEditDesc] = useState("");
  const [editType, setEditType] = useState<EditableSkillType>("hook");
  const [editInstructions, setEditInstructions] = useState("");
  const [editPaths, setEditPaths] = useState("");
  const [editTriggers, setEditTriggers] = useState("");

  async function fetchSkillManagerData() {
    const [skillsRes, toolsRes] = await Promise.all([fetch("/api/skills"), fetch("/api/tools")]);
    const skillsData = (await skillsRes.json()) as CatalogResponse;
    const toolsData = (await toolsRes.json()) as CatalogResponse;
    return {
      skills: skillsData.skills || [],
      tools: toolsData.tools || [],
      runtimes: skillsData.runtimes || toolsData.runtimes || [],
    };
  }

  const loadData = async () => {
    const data = await fetchSkillManagerData();
    setSkills(data.skills);
    setTools(data.tools);
    setRuntimes(data.runtimes);
  };

  useEffect(() => {
    let ignore = false;

    fetchSkillManagerData()
      .then((data) => {
        if (!ignore) {
          setSkills(data.skills);
          setTools(data.tools);
          setRuntimes(data.runtimes);
        }
      })
      .catch((error) => {
        console.error("Failed to load skills/tools:", error);
      });

    return () => {
      ignore = true;
    };
  }, []);

  const runtimeFilters = useMemo(() => {
    return [
      {
        id: ALL_RUNTIMES,
        label: "全部 Agent",
        toolCount: tools.length,
        skillCount: skills.length,
        available: true,
      },
      ...runtimes.map((runtime) => ({
        id: runtime.id,
        label: runtime.label,
        toolCount: runtime.tools?.length || tools.filter((tool) => tool.runtime === runtime.id).length,
        skillCount: runtime.skills?.length || skills.filter((skill) => skill.runtime === runtime.id).length,
        available: runtime.available,
      })),
    ];
  }, [runtimes, skills, tools]);

  const visibleSkills = useMemo(() => {
    if (selectedRuntimeId === ALL_RUNTIMES) return skills;
    return skills.filter((skill) => skill.runtime === selectedRuntimeId);
  }, [selectedRuntimeId, skills]);

  const visibleTools = useMemo(() => {
    if (selectedRuntimeId === ALL_RUNTIMES) return tools;
    return tools.filter((tool) => tool.runtime === selectedRuntimeId);
  }, [selectedRuntimeId, tools]);

  const canCreateSkill = selectedRuntimeId === ALL_RUNTIMES || selectedRuntimeId === HANDMADE_RUNTIME;
  const canEditSelectedSkill = isNew || isEditableSkill(selectedSkill);

  const handleSelectSkill = (skill: SkillOption) => {
    setSelectedSkill(skill);
    setIsNew(false);
    setEditName(skill.name);
    setEditDesc(skill.description);
    setEditType(normalizeEditableType(skill.type));
    setEditInstructions(skill.instructions || "");
    setEditPaths((skill.paths || []).join(", "));
    setEditTriggers((skill.trigger_words || []).join(", "));
  };

  const handleNewSkill = () => {
    setSelectedRuntimeId(HANDMADE_RUNTIME);
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
    if (!canEditSelectedSkill) return;
    const payload = {
      name: editName,
      meta: {
        description: editDesc,
        type: editType,
        paths: editPaths.split(",").map((s) => s.trim()).filter(Boolean),
        trigger_words: editTriggers.split(",").map((s) => s.trim()).filter(Boolean),
      },
      instructions: editInstructions,
    };

    try {
      const res = await fetch("/api/skills", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
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
      <header className="flex shrink-0 flex-col gap-4 border-b border-stone-200 px-6 py-4">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <h2 className="text-lg font-bold">技能与工具管理</h2>
            <div className="flex rounded-lg bg-stone-100 p-1">
              <button
                onClick={() => setActiveTab("skills")}
                className={cn(
                  "rounded-md px-3 py-1 text-xs font-bold transition",
                  activeTab === "skills" ? "bg-white text-stone-900 shadow-sm" : "text-stone-500 hover:text-stone-700",
                )}
              >
                技能库
              </button>
              <button
                onClick={() => setActiveTab("tools")}
                className={cn(
                  "rounded-md px-3 py-1 text-xs font-bold transition",
                  activeTab === "tools" ? "bg-white text-stone-900 shadow-sm" : "text-stone-500 hover:text-stone-700",
                )}
              >
                工具清单
              </button>
            </div>
          </div>
          {activeTab === "skills" && (
            <button
              onClick={handleNewSkill}
              disabled={!canCreateSkill}
              className="flex items-center gap-2 rounded-lg bg-stone-900 px-3 py-2 text-sm font-bold text-white transition hover:bg-stone-800 disabled:cursor-not-allowed disabled:bg-stone-200 disabled:text-stone-400"
            >
              <Plus className="h-4 w-4" />
              新建手搓技能
            </button>
          )}
        </div>

        <div className="flex gap-2 overflow-x-auto pb-1">
          {runtimeFilters.map((runtime) => (
            <button
              key={runtime.id}
              onClick={() => {
                setSelectedRuntimeId(runtime.id);
                setSelectedSkill(null);
                setIsNew(false);
              }}
              className={cn(
                "flex min-w-fit items-center gap-2 rounded-lg border px-3 py-2 text-left transition",
                selectedRuntimeId === runtime.id
                  ? "border-stone-900 bg-stone-900 text-white"
                  : "border-stone-200 bg-white text-stone-700 hover:border-stone-300",
              )}
            >
              <Layers3 className="h-4 w-4" />
              <span className="text-xs font-bold">{runtime.label}</span>
              <span className="text-[10px] opacity-70">
                {runtime.skillCount} skills · {runtime.toolCount} tools
              </span>
              {!runtime.available && runtime.id !== ALL_RUNTIMES && <Lock className="h-3.5 w-3.5 opacity-70" />}
            </button>
          ))}
        </div>
      </header>

      <main className="flex min-h-0 flex-1 overflow-hidden">
        {activeTab === "skills" ? (
          <>
            <div className="w-80 shrink-0 overflow-y-auto border-r border-stone-200 bg-stone-50/50">
              <div className="px-2 py-4">
                {visibleSkills.map((skill) => (
                  <button
                    key={`${skill.runtime || "unknown"}:${skill.name}`}
                    onClick={() => handleSelectSkill(skill)}
                    className={cn(
                      "group flex w-full flex-col gap-2 rounded-xl p-3 text-left transition",
                      selectedSkill?.name === skill.name && selectedSkill?.runtime === skill.runtime
                        ? "bg-white shadow-sm ring-1 ring-stone-200"
                        : "hover:bg-stone-100",
                    )}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <span className="min-w-0 truncate text-sm font-bold text-stone-900">{skill.name}</span>
                      <span
                        className={cn(
                          "rounded px-1.5 py-0.5 text-[10px] font-bold",
                          skill.native ? "bg-stone-200 text-stone-600" : "bg-amber-100 text-amber-700",
                        )}
                      >
                        {skillTypeLabel(skill.type)}
                      </span>
                    </div>
                    <p className="line-clamp-2 text-xs text-stone-500">{skill.description}</p>
                    <div className="flex items-center justify-between text-[10px] font-bold uppercase tracking-wide text-stone-400">
                      <span>{runtimeLabel(skill.runtime, runtimes)}</span>
                      {skill.editable === false || skill.native ? <span>READ ONLY</span> : <span>EDITABLE</span>}
                    </div>
                  </button>
                ))}
                {visibleSkills.length === 0 && (
                  <div className="px-4 py-10 text-center text-sm text-stone-400">当前 Agent 暂无技能目录。</div>
                )}
              </div>
            </div>

            <div className="flex min-w-0 flex-1 flex-col overflow-y-auto bg-white">
              {selectedSkill || isNew ? (
                <div className="mx-auto w-full max-w-3xl p-8">
                  <div className="mb-8 flex items-center justify-between gap-4">
                    <div>
                      <div className="mb-2 flex items-center gap-2">
                        {canEditSelectedSkill ? <Pencil className="h-4 w-4 text-emerald-600" /> : <Lock className="h-4 w-4 text-stone-400" />}
                        <span className="text-xs font-bold uppercase tracking-wide text-stone-400">
                          {isNew ? "Handmade" : runtimeLabel(selectedSkill?.runtime, runtimes)}
                        </span>
                      </div>
                      <h3 className="text-2xl font-bold">{isNew ? "新建技能" : selectedSkill?.name}</h3>
                      <p className="text-sm text-stone-500">
                        {canEditSelectedSkill ? "配置手搓 Agent 的技能激活规则和指令集" : "这是底层 Agent 的原生技能目录，只在这里做能力可视化"}
                      </p>
                    </div>
                    {canEditSelectedSkill && (
                      <div className="flex gap-2">
                        {!isNew && selectedSkill && (
                          <button
                            onClick={() => handleDelete(selectedSkill.name)}
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
                    )}
                  </div>

                  {canEditSelectedSkill ? (
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
                            onChange={(e) => setEditType(normalizeEditableType(e.target.value))}
                            className="rounded-lg border border-stone-200 bg-white px-3 py-2 text-sm outline-none focus:border-emerald-500"
                          >
                            <option value="hook">Hooks 自动感应</option>
                            <option value="invocable">Invocable 主动调用</option>
                          </select>
                        </div>
                        <div className="grid gap-2">
                          <label className="text-sm font-bold text-stone-700">文件路径模式</label>
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
                        <label className="text-sm font-bold text-stone-700">触发关键词</label>
                        <input
                          value={editTriggers}
                          onChange={(e) => setEditTriggers(e.target.value)}
                          placeholder="python, refactor, commit"
                          className="rounded-lg border border-stone-200 bg-white px-4 py-2 text-sm outline-none focus:border-emerald-500"
                        />
                      </div>

                      <div className="grid gap-2">
                        <label className="text-sm font-bold text-stone-700">核心指令</label>
                        <textarea
                          value={editInstructions}
                          onChange={(e) => setEditInstructions(e.target.value)}
                          rows={12}
                          className="rounded-lg border border-stone-200 bg-white px-4 py-3 font-mono text-sm leading-6 outline-none focus:border-emerald-500"
                          placeholder="### 技能指令&#10;&#10;1. 准则一&#10;2. 准则二..."
                        />
                      </div>
                    </div>
                  ) : (
                    <div className="grid gap-5">
                      <section className="rounded-xl border border-stone-200 bg-stone-50 p-5">
                        <div className="mb-3 flex items-center gap-2 text-xs font-bold uppercase tracking-wide text-stone-400">
                          <Bot className="h-4 w-4" />
                          Native Skill
                        </div>
                        <p className="text-sm leading-6 text-stone-700">{selectedSkill?.description}</p>
                        <div className="mt-4 flex flex-wrap gap-2 text-[11px] font-medium text-stone-500">
                          {selectedSkill?.scope && <span className="rounded bg-white px-2 py-1">scope: {selectedSkill.scope}</span>}
                          {selectedSkill?.source_detail && <span className="rounded bg-white px-2 py-1">{selectedSkill.source_detail}</span>}
                          {selectedSkill?.standard && <span className="rounded bg-white px-2 py-1">{selectedSkill.standard}</span>}
                        </div>
                        {selectedSkill?.path && (
                          <p className="mt-3 break-all font-mono text-xs leading-5 text-stone-400">{selectedSkill.path}</p>
                        )}
                      </section>
                      <section className="rounded-xl border border-stone-200 bg-white p-5">
                        <div className="mb-3 flex items-center justify-between gap-3">
                          <h4 className="text-sm font-bold text-stone-900">说明</h4>
                          {selectedSkill?.content_truncated && <span className="text-xs text-stone-400">已截断</span>}
                        </div>
                        <pre className="whitespace-pre-wrap break-words font-mono text-sm leading-6 text-stone-600">
                          {selectedSkill?.instructions || "该 runtime 暂未提供更详细的技能说明。"}
                        </pre>
                      </section>
                    </div>
                  )}
                </div>
              ) : (
                <div className="flex flex-1 flex-col items-center justify-center text-stone-400">
                  <BookOpen className="mb-4 h-12 w-12 opacity-20" />
                  <p>请选择一个技能查看详情，或新建手搓 Agent 技能。</p>
                </div>
              )}
            </div>
          </>
        ) : (
          <div className="flex flex-1 flex-col overflow-y-auto bg-stone-50/30 p-8">
            <div className="mx-auto w-full max-w-5xl">
              <div className="mb-8">
                <h3 className="text-2xl font-bold">工具能力清单</h3>
                <p className="text-sm text-stone-500">统一展示 Handmade、OpenCode、Claude Code 当前可见的工具能力。</p>
              </div>

              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                {visibleTools.map((tool) => (
                  <div
                    key={`${tool.runtime || "unknown"}:${tool.name}`}
                    className="flex flex-col gap-3 rounded-xl border border-stone-200 bg-white p-5 shadow-sm transition hover:shadow-md"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex min-w-0 items-center gap-2">
                        <div className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-stone-100 text-stone-600">
                          {tool.native ? <Wrench className="h-4 w-4" /> : <Zap className="h-4 w-4" />}
                        </div>
                        <span className="truncate font-bold text-stone-900">{tool.name}</span>
                      </div>
                      <span
                        className={cn(
                          "rounded-full px-2 py-0.5 text-[10px] font-bold uppercase",
                          tool.permission?.includes("safe") || tool.permission === "read"
                            ? "bg-emerald-100 text-emerald-700"
                            : "bg-amber-100 text-amber-700",
                        )}
                      >
                        {tool.permission}
                      </span>
                    </div>
                    <p className="min-h-10 text-xs leading-5 text-stone-600">{tool.description}</p>
                    <div className="flex flex-wrap gap-1.5">
                      <span className="rounded bg-stone-100 px-1.5 py-0.5 text-[10px] font-medium text-stone-500">
                        {runtimeLabel(tool.runtime, runtimes)}
                      </span>
                      {tool.source && (
                        <span className="rounded bg-stone-100 px-1.5 py-0.5 text-[10px] font-medium text-stone-500">
                          {tool.source}
                        </span>
                      )}
                      {tool.parameters?.required?.map((param) => (
                        <span key={param} className="rounded bg-stone-100 px-1.5 py-0.5 text-[10px] font-medium text-stone-500">
                          {param} 必填
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
              {visibleTools.length === 0 && (
                <div className="rounded-xl border border-dashed border-stone-300 bg-white p-10 text-center text-sm text-stone-400">
                  当前 Agent 暂无工具目录。
                </div>
              )}
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
