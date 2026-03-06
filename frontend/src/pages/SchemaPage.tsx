import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { apiDelete, apiGet, apiPost } from '../api'

type PaperType = 'research' | 'review' | 'software' | 'theoretical' | 'case_study'

type Schema = {
  paper_type: PaperType
  version: number
  name?: string
  steps: Array<{ id: string; label_zh?: string; label_en?: string; enabled?: boolean; order?: number }>
  claim_kinds: Array<{ id: string; label_zh?: string; label_en?: string; enabled?: boolean }>
  rules: Record<string, unknown>
  prompts?: Record<string, string>
}

type SchemaPreset = {
  id: string
  label_zh?: string
  label_en?: string
  summary_zh?: string
  focus_zh?: string
  use_case_zh?: string
  prompt_keys?: string[]
}

function clone<T>(x: T): T {
  return JSON.parse(JSON.stringify(x)) as T
}

const ID_RE = /^[A-Za-z][A-Za-z0-9_-]{0,47}$/

const DEFAULT_PROMPTS: Record<string, string> = {
  logic_claims_system:
    "You extract a paper's reasoning structure for a research knowledge graph.\nReturn STRICT JSON only (no prose, no Markdown).\n\nGROUNDING / FAITHFULNESS:\n- Be strictly faithful to the provided paper text.\n- Do NOT invent details, numbers, conditions, or causal claims.\n- If something is not explicitly supported, omit it (preferred) or lower confidence.\n\nLANGUAGE / STYLE:\n- Use the same language as the paper text.\n- Write COMPLETE sentences only (no fragments, no missing subjects/verbs).\n- Keep technical symbols/variables exactly as in the paper.\n\nDIFFERENT OUTPUT GRANULARITIES:\n1) logic: for EACH allowed step_type, write a DETAILED mini-paragraph summary.\n   - 2–6 complete sentences (NOT a single sentence).\n   - Include key entities, methods, assumptions/conditions, and important numbers/definitions if present.\n2) claims: write concise, atomic KEY POINTS.\n   - 1–2 complete sentences each.\n   - Each claim must be specific and directly supported by the text.\n   - Avoid duplicating the logic summaries verbatim.\n\nSCHEMA RULES:\n- Each claim MUST belong to exactly ONE step_type (from the allowed list).\n- Each claim MUST have claim_kinds as a LIST (multi-select) chosen from allowed kinds (prefer 1–3 kinds).\n- Confidence values must be in [0,1].\n",
  logic_claims_user_template:
    "Paper metadata:\nTitle: {{title}}\nAuthors: {{authors}}\nYear: {{year}}\nDOI: {{doi}}\n\nAllowed step types: {{step_ids}}\nAllowed claim kinds: {{kind_ids}}\nTarget number of claims: {{cmin}}-{{cmax}}\n\nPaper text (extracted from Markdown):\n{{body}}\n\nOutput JSON schema (STRICT):\n{\n  \"logic\": {\n    \"<StepType>\": {\"summary\": \"2-6 full sentences...\", \"confidence\": 0.0}\n  },\n  \"claims\": [\n    {\"text\":\"1-2 full sentences...\",\"confidence\":0.0,\"step_type\":\"<StepType>\",\"claim_kinds\":[\"KindA\",\"KindB\"]}\n  ]\n}\n",
  evidence_pick_system:
    "Pick evidence chunks for claims. Return STRICT JSON only (no prose).\n- Pick chunks that DIRECTLY support the claim wording.\n- Prefer chunks containing the key definition/number/equation mentioned.\n- If evidence is weak/indirect, still pick the best available and set weak=true.\n",
  evidence_pick_user_template:
    "Pick {{emin}}-{{emax}} chunk_id(s) per claim from its candidates.\nIf none strongly supports it, still pick best 1 and set weak=true.\n\nInput claims JSON:\n{{payload_json}}\n\nOutput JSON schema:\n{ \"items\": [ {\"claim_key\":\"...\",\"evidence_chunk_ids\":[\"...\"],\"weak\":false} ] }\n",
  phase1_logic_bind_system:
    "You bind each logic step summary to directly supporting chunk IDs.\nReturn STRICT JSON only.\nRules:\n- Use ONLY chunk IDs from the provided catalog.\n- evidence_chunk_ids should contain 1-4 chunk ids when support is available.\n- If support is weak/insufficient, set evidence_weak=true and keep ids minimal.\n",
  phase1_logic_bind_user_template:
    "Allowed step types: {{step_ids}}\n\nLogic summaries JSON:\n{{logic_brief_json}}\n\nChunk catalog JSON:\n{{chunks_json}}\n\nOutput JSON schema:\n{ \"items\": [ {\"step_type\":\"Background\",\"evidence_chunk_ids\":[\"c1\",\"c2\"],\"evidence_weak\":false} ] }\n",
  phase1_chunk_claim_extract_system:
    "Extract atomic claims from one paper chunk. Return STRICT JSON only.\nEach claim must be directly supported by the provided chunk text.\nDo not invent information outside this chunk.\n",
  phase1_chunk_claim_extract_user_template:
    "Allowed step types: {{step_ids}}\nAllowed claim kinds: {{kind_ids}}\nMax claims: {{max_claims}}\n\nChunk text:\n{{chunk_text}}\n\nOutput JSON schema:\n{ \"claims\": [ {\"text\":\"...\", \"step_type\":\"Background\", \"claim_kinds\":[\"Definition\"], \"confidence\":0.0} ] }\n",
  phase1_grounding_judge_system:
    "You are a scientific claim grounding judge.\nReturn STRICT JSON only.\nCompare each claim with its origin chunk and output label + score.\nLabels: supported | weak | unsupported | contradicted.\n",
  phase1_grounding_judge_user_template:
    "Supported threshold: {{supported_min}}\nWeak threshold: {{weak_min}}\n\nInput JSON:\n{{items_json}}\n\nOutput JSON schema:\n{ \"items\": [ {\"canonical_claim_id\":\"...\", \"label\":\"supported\", \"score\":0.0, \"reason\":\"...\"} ] }\n",
  phase2_conflict_judge_system:
    "You are a scientific contradiction judge.\nReturn STRICT JSON only.\nFor each claim pair, output contradict | not_conflict | insufficient with score in [0,1].\n",
  phase2_conflict_judge_user_template:
    "Pair count: {{pair_count}}\n\nInput JSON:\n{{pairs_json}}\n\nOutput JSON schema:\n{ \"items\": [ {\"pair_id\":\"p1\", \"label\":\"contradict\", \"score\":0.0, \"reason\":\"...\"} ] }\n",
  citation_purpose_batch_system:
    "You classify the PURPOSE of citations in a mechanics paper.\nReturn STRICT JSON only.\nFor each cited_paper_id, output 1-3 labels from the allowed list and scores in [0,1].\nBe conservative: if evidence is weak, use Background/Summary with low confidence.\nAllowed labels: {{allowed_labels}}",
  citation_purpose_batch_user_template:
    "Citing paper title: {{citing_title}}\n\nFor each citation, you are given the cited paper metadata (may be empty) and context snippets.\nInput JSON:\n{{cites_json}}\n\nOutput JSON schema:\n{\n  \"cites\": [\n    {\"cited_paper_id\": \"doi:10....\", \"labels\": [\"MethodUse\"], \"scores\":[0.72]}\n  ]\n}\n",
  reference_recovery_system:
    "You are a reference-recovery agent for scientific markdown.\nExtract bibliography entries only from the provided text.\nReturn STRICT JSON only.\nDo not fabricate references.\n",
  reference_recovery_user_template:
    "Title: {{title}}\nDOI: {{doi}}\nMax references: {{max_refs}}\n\nMarkdown text:\n{{markdown_text}}\n\nOutput JSON schema:\n{ \"references\": [ {\"raw\":\"...\"} ] }\n",
}

type RuleHelpSection = {
  title: string
  items: Array<{ key: string; desc: string }>
}

type PromptHelpSection = {
  title: string
  items: Array<{ key: string; desc: string; vars?: string }>
}

const RULE_HELP_SECTIONS: RuleHelpSection[] = [
  {
    title: '基础抽取规模与证据',
    items: [
      { key: 'claims_per_paper_min', desc: '单篇论文目标最少要点数，用于控制抽取下限。' },
      { key: 'claims_per_paper_max', desc: '单篇论文目标最多要点数，用于控制抽取上限。' },
      { key: 'machine_evidence_min', desc: '每条要点最少自动证据块数（旧轨道兼容参数）。' },
      { key: 'machine_evidence_max', desc: '每条要点最多自动证据块数（旧轨道兼容参数）。' },
      { key: 'logic_evidence_min', desc: '每个逻辑步骤最少证据块数。' },
      { key: 'logic_evidence_max', desc: '每个逻辑步骤最多证据块数。' },
      { key: 'evidence_verification', desc: '是否启用 LLM 证据复核（llm/off）。' },
      { key: 'citation_context_sentence_window', desc: '引用上下文句窗大小，用于构建引用证据。' },
      { key: 'targets_per_claim_max', desc: '每条要点最多关联的目标论文数量。' },
      { key: 'require_targets_for_kinds', desc: '这些要点类型必须尝试补齐目标论文。' },
    ],
  },
  {
    title: '抽取流程控制',
    items: [
      { key: 'phase1_claim_worker_count', desc: '并行抽取 worker 数，影响吞吐和成本。' },
      { key: 'phase1_logic_chunks_max', desc: '逻辑证据绑定阶段可见的 chunk 数上限。' },
      { key: 'phase1_logic_chunk_chars_max', desc: '逻辑证据绑定阶段单 chunk 文本截断上限。' },
      { key: 'phase1_claim_chunks_max', desc: 'Chunk 级要点抽取最多处理多少个 chunk。' },
      { key: 'phase1_claims_per_chunk_max', desc: '单个 chunk 最多抽取的要点数。' },
      { key: 'phase1_chunk_chars_max', desc: 'Chunk 级要点抽取时每个 chunk 最大字符数。' },
      { key: 'phase1_doc_chars_max', desc: '文档级逻辑/要点提示词注入时文本总长度上限。' },
      { key: 'phase1_filter_reference_sections', desc: '是否在 Phase1 前过滤参考文献类章节（References/Bibliography 等）。' },
      { key: 'phase1_excluded_section_terms', desc: '用于识别“应排除章节”的关键词列表（CSV）；命中则该 chunk 不进入抽取。' },
      { key: 'phase1_evidence_verify_batch_size', desc: '证据复核时每批 claim 数量。' },
      { key: 'phase1_logic_lexical_topk_min', desc: '逻辑步骤词法召回最小 topk。' },
      { key: 'phase1_logic_lexical_topk_multiplier', desc: '逻辑证据候选 topk 与 emax 的倍率。' },
      { key: 'phase1_logic_evidence_weak_score_threshold', desc: '逻辑证据 top1 分低于该阈值则标记弱证据。' },
      { key: 'phase1_evidence_lexical_topk', desc: '要点证据候选的词法召回 topk。' },
      { key: 'phase1_evidence_verify_candidates_max', desc: 'LLM 证据复核时每条要点最多看多少候选。' },
    ],
  },
  {
    title: 'Grounding 打分',
    items: [
      { key: 'phase1_grounding_supported_overlap_min', desc: '判定 supported 的词重叠率下限。' },
      { key: 'phase1_grounding_weak_overlap_min', desc: '判定 weak 的词重叠率下限。' },
      { key: 'phase1_grounding_supported_score_substring', desc: '子串直接命中时的评分。' },
      { key: 'phase1_grounding_supported_score_overlap', desc: '高重叠命中时的评分。' },
      { key: 'phase1_grounding_weak_score', desc: 'weak 命中时的评分。' },
      { key: 'phase1_grounding_insufficient_score', desc: '词特征不足时的评分。' },
      { key: 'phase1_grounding_unsupported_score', desc: '低重叠时的评分。' },
      { key: 'phase1_grounding_empty_score', desc: '空文本/空证据时的评分。' },
    ],
  },
  {
    title: '质量门禁',
    items: [
      { key: 'phase1_gate_supported_ratio_min', desc: '最低支持率阈值；低于则门禁失败。' },
      { key: 'phase1_gate_step_coverage_min', desc: '最低步骤覆盖率阈值；低于则门禁失败。' },
      { key: 'phase2_gate_critical_slot_coverage_min', desc: '关键槽位覆盖率阈值。' },
      { key: 'phase2_gate_conflict_rate_max', desc: '冲突率上限阈值；高于则门禁失败。' },
      { key: 'phase2_critical_steps', desc: '关键步骤列表（为空时默认全步骤）。' },
      { key: 'phase2_critical_kinds', desc: '关键要点类型列表（为空时按步骤槽位）。' },
      { key: 'phase2_critical_step_kind_map', desc: '步骤-类型映射（优先于 steps/kinds 笛卡尔组合），用于避免不合理槽位。' },
      { key: 'phase2_auto_step_kind_map_enabled', desc: '当步骤×类型槽位过多时，是否自动收敛为步骤定向映射。' },
      { key: 'phase2_auto_step_kind_map_trigger_slots', desc: '触发自动收敛映射的最小笛卡尔槽位数（steps*kinds）。' },
      { key: 'phase2_auto_step_kind_map_max_kinds_per_step', desc: '自动收敛后，每个步骤最多保留的关键类型数。' },
    ],
  },
  {
    title: '冲突检测',
    items: [
      { key: 'phase2_conflict_shared_tokens_min', desc: '两条要点进入冲突比较前需共享的最少主题词数。' },
      { key: 'phase2_conflict_samples_max', desc: '质量报告中最多保留的冲突样本条数。' },
      { key: 'phase2_conflict_gate_min_comparable_pairs', desc: '触发 conflict_rate 门禁前，最少可比较 claim 对数量。' },
      { key: 'phase2_conflict_gate_min_conflict_pairs', desc: '触发 conflict_rate 门禁前，最少冲突 claim 对数量。' },
      { key: 'phase2_conflict_positive_terms_en', desc: '英文正向极性词表。' },
      { key: 'phase2_conflict_negative_terms_en', desc: '英文负向极性词表。' },
      { key: 'phase2_conflict_positive_terms_zh', desc: '中文正向极性词表。' },
      { key: 'phase2_conflict_negative_terms_zh', desc: '中文负向极性词表。' },
      { key: 'phase2_conflict_stop_terms_en', desc: '英文停用词（冲突比较时忽略）。' },
      { key: 'phase2_conflict_stop_terms_zh', desc: '中文停用词（冲突比较时忽略）。' },
    ],
  },
  {
    title: '引用目的抽取（Citation Purpose）',
    items: [
      { key: 'citation_purpose_max_contexts_per_cite', desc: '每条引用最多送入多少段上下文。' },
      { key: 'citation_purpose_max_context_chars', desc: '每段引用上下文最大字符数。' },
      { key: 'citation_purpose_max_cites_per_batch', desc: '单次批量分类最多处理多少条引用。' },
      { key: 'citation_purpose_max_labels_per_cite', desc: '每条引用最多输出的目的标签数。' },
      { key: 'citation_purpose_fallback_score', desc: '模型输出异常时使用的默认分数。' },
    ],
  },
]

const PROMPT_HELP_SECTIONS: PromptHelpSection[] = [
  {
    title: '文档级逻辑与要点抽取',
    items: [
      {
        key: 'logic_claims_system',
        desc: '控制文档级“逻辑链 + 要点”抽取的总体行为、格式与约束。',
      },
      {
        key: 'logic_claims_user_template',
        desc: '拼接论文元信息、步骤/类型约束和正文内容，驱动主抽取阶段。',
        vars: 'title, authors, year, doi, step_ids, kind_ids, cmin, cmax, body',
      },
    ],
  },
  {
    title: '要点证据选择',
    items: [
      {
        key: 'evidence_pick_system',
        desc: '定义“claim -> chunk证据”选择策略，强调直接支撑与弱证据标记。',
      },
      {
        key: 'evidence_pick_user_template',
        desc: '注入候选证据负载，要求模型返回每条要点的证据 chunk_id。',
        vars: 'emin, emax, payload_json',
      },
    ],
  },
  {
    title: '逻辑证据绑定',
    items: [
      {
        key: 'phase1_logic_bind_system',
        desc: '约束逻辑步骤与证据 chunk 绑定规则（仅允许候选目录中的 chunk_id）。',
      },
      {
        key: 'phase1_logic_bind_user_template',
        desc: '提供逻辑摘要和 chunk 目录，要求模型输出每个步骤证据集合。',
        vars: 'step_ids, logic_brief_json, chunks_json, chunk_lines',
      },
    ],
  },
  {
    title: 'Chunk 级要点抽取',
    items: [
      {
        key: 'phase1_chunk_claim_extract_system',
        desc: '定义单 chunk 抽取原子要点的约束，防止脱离原文胡编。',
      },
      {
        key: 'phase1_chunk_claim_extract_user_template',
        desc: '提供单 chunk 文本与 schema 约束，输出该 chunk 的要点列表。',
        vars: 'step_ids, kind_ids, max_claims, chunk_text',
      },
    ],
  },
  {
    title: '引用目的分类',
    items: [
      {
        key: 'citation_purpose_batch_system',
        desc: '定义批量引用目的分类标准与输出约束。',
      },
      {
        key: 'citation_purpose_batch_user_template',
        desc: '注入引用上下文批次数据，输出每条引用的目的标签与分数。',
        vars: 'citing_title, cites_json, allowed_labels',
      },
    ],
  },
]

const RULE_HELP_MAP: Record<string, string> = Object.fromEntries(
  RULE_HELP_SECTIONS.flatMap((section) => section.items.map((item) => [item.key, item.desc] as const)),
)
RULE_HELP_MAP.reference_recovery_enabled = '是否启用参考文献二次补抽流程。'
RULE_HELP_MAP.reference_recovery_trigger_max_existing_refs = '触发补抽的最大“现有参考文献数”（<= 该值才会调用智能体）。'
RULE_HELP_MAP.reference_recovery_max_refs = '参考文献补抽阶段允许返回的最大条目数。'
RULE_HELP_MAP.reference_recovery_doc_chars_max = '补抽时送入智能体的 markdown 最大字符数。'
RULE_HELP_MAP.reference_recovery_agent_timeout_sec = '智能体补抽的超时秒数；超时后自动回退到启发式补抽。'
RULE_HELP_MAP.citation_event_recovery_enabled = '当正文引文事件不足时，是否启用“基于 references 的 citation_events 二次补抽”。'
RULE_HELP_MAP.citation_event_recovery_trigger_max_existing_events = '触发二次补抽的最大现有 citation_events 数量（<=该值才触发）。'
RULE_HELP_MAP.citation_event_recovery_numeric_bracket_enabled = '二次补抽时是否启用数字方括号模式（如 [12], [3-5]）。'
RULE_HELP_MAP.citation_event_recovery_paren_numeric_enabled = '二次补抽时是否启用圆括号数字模式（如 (12), （3,4））。'
RULE_HELP_MAP.citation_event_recovery_author_year_enabled = '二次补抽时是否启用作者-年份模式（如 Smith, 2019）。'
RULE_HELP_MAP.citation_event_recovery_max_events_per_chunk = '每个 chunk 最多补回的 citation_events 数量。'
RULE_HELP_MAP.citation_event_recovery_context_chars = '补回 citation_events 时写入 context 的最大字符数。'

RULE_HELP_MAP.phase1_grounding_mode = 'Claim 支持判定模式：lexical（纯规则）/ hybrid（规则+LLM）/ llm（全量LLM）。'
RULE_HELP_MAP.phase1_grounding_semantic_supported_min = '语义支持判定中，判为 supported 的最低分数阈值。'
RULE_HELP_MAP.phase1_grounding_semantic_weak_min = '语义支持判定中，判为 weak 的最低分数阈值。'
RULE_HELP_MAP.phase2_conflict_mode = '冲突判定模式：lexical（纯规则）/ hybrid（规则召回+LLM）/ llm（全量LLM）。'
RULE_HELP_MAP.phase2_conflict_semantic_threshold = '语义冲突判定阈值；仅当 score 达到阈值才计入冲突对。'
RULE_HELP_MAP.phase2_conflict_candidate_max_pairs = '进入语义冲突判定的最大候选 claim 对数。'
RULE_HELP_MAP.phase2_quality_tier_strategy = '论文级质量分层策略。当前支持 a1_fail_count（按失败项数量分层）。'
RULE_HELP_MAP.phase2_quality_tier_yellow_max_failures = 'yellow 最大失败项数量（>0 且 <= red_min-1）。'
RULE_HELP_MAP.phase2_quality_tier_red_min_failures = 'red 最小失败项数量（必须大于 yellow_max）。'

const PROMPT_HELP_MAP: Record<string, { desc: string; vars?: string }> = Object.fromEntries(
  PROMPT_HELP_SECTIONS.flatMap((section) => section.items.map((item) => [item.key, { desc: item.desc, vars: item.vars }] as const)),
)
PROMPT_HELP_MAP.reference_recovery_system = {
  desc: '参考文献补抽智能体的全局行为约束：只抽原文中真实存在的条目，不允许编造。',
}
PROMPT_HELP_MAP.reference_recovery_user_template = {
  desc: '注入待补抽论文文本与上限参数，要求模型输出参考文献列表。',
  vars: 'title, doi, max_refs, markdown_text',
}

PROMPT_HELP_MAP.phase1_grounding_judge_system = {
  desc: 'Grounding 语义裁判系统提示词：定义 claim 与 chunk 的支持关系判定规则。',
}
PROMPT_HELP_MAP.phase1_grounding_judge_user_template = {
  desc: 'Grounding 语义裁判用户模板：注入 claim+chunk 批次输入，返回支持标签与分数。',
  vars: 'items_json, supported_min, weak_min',
}
PROMPT_HELP_MAP.phase2_conflict_judge_system = {
  desc: '冲突语义裁判系统提示词：定义两条 claim 是否语义冲突的判定规则。',
}
PROMPT_HELP_MAP.phase2_conflict_judge_user_template = {
  desc: '冲突语义裁判用户模板：注入候选 claim 对，返回冲突标签与分数。',
  vars: 'pairs_json, pair_count',
}

function ruleHelp(key: string): string {
  return RULE_HELP_MAP[key] ?? ''
}

function promptHelp(key: string): { desc: string; vars?: string } {
  return PROMPT_HELP_MAP[key] ?? { desc: '' }
}

function RuleMeta({ ruleKey, label }: { ruleKey: string; label: string }) {
  return (
    <div style={{ minWidth: 180 }}>
      <div className="kicker">{label}</div>
      <div className="hint" style={{ marginTop: 2, lineHeight: 1.35 }}>
        {ruleHelp(ruleKey)}
      </div>
    </div>
  )
}

function intOr(v: unknown, fallback: number) {
  const n = Number(v)
  return Number.isFinite(n) ? Math.trunc(n) : fallback
}

function floatOr(v: unknown, fallback: number) {
  const n = Number(v)
  return Number.isFinite(n) ? n : fallback
}

function parseCsvList(v: string): string[] {
  return String(v ?? '')
    .split(',')
    .map((x) => x.trim())
    .filter((x) => x.length > 0)
}

function normalizeStringList(v: unknown): string[] {
  if (!Array.isArray(v)) return []
  const out: string[] = []
  for (const item of v) {
    const s = String(item ?? '').trim()
    if (s && !out.includes(s)) out.push(s)
  }
  return out
}

function csvFromRule(v: unknown): string {
  return normalizeStringList(v).join(', ')
}

function parseStepKindMap(v: string): Record<string, string[]> {
  const out: Record<string, string[]> = {}
  const text = String(v ?? '').trim()
  if (!text) return out
  const rows = text
    .split(/\r?\n|;/)
    .map((x) => x.trim())
    .filter((x) => x.length > 0)
  for (const row of rows) {
    const [stepRaw, kindsRaw] = row.split(/\s*=>\s*/, 2)
    const step = String(stepRaw ?? '').trim()
    if (!step) continue
    const kinds = String(kindsRaw ?? '')
      .split('|')
      .map((x) => x.trim())
      .filter((x) => x.length > 0)
    if (!kinds.length) continue
    out[step] = Array.from(new Set(kinds))
  }
  return out
}

function stepKindMapToText(v: unknown): string {
  if (!v || typeof v !== 'object' || Array.isArray(v)) return ''
  const obj = v as Record<string, unknown>
  const lines: string[] = []
  for (const step of Object.keys(obj)) {
    const kinds = normalizeStringList(obj[step])
    if (!step || !kinds.length) continue
    lines.push(`${step} => ${kinds.join('|')}`)
  }
  return lines.join('\n')
}

type SchemaPageProps = {
  jumpTarget?: string | null
  jumpFocusKey?: string | null
  jumpNonce?: number
}

export default function SchemaPage({ jumpTarget, jumpFocusKey, jumpNonce }: SchemaPageProps = {}) {
  const [searchParams, setSearchParams] = useSearchParams()
  const [paperType, setPaperType] = useState<PaperType>('research')
  const [schema, setSchema] = useState<Schema | null>(null)
  const [baselineJson, setBaselineJson] = useState<string>('')
  const [versions, setVersions] = useState<Array<{ version: number; name?: string }>>([])
  const [error, setError] = useState<string>('')
  const [info, setInfo] = useState<string>('')
  const [busy, setBusy] = useState<boolean>(false)
  const [activateVersion, setActivateVersion] = useState<string>('')

  const [newStepId, setNewStepId] = useState<string>('')
  const [newStepZh, setNewStepZh] = useState<string>('')
  const [newStepEn, setNewStepEn] = useState<string>('')
  const [newStepOrder, setNewStepOrder] = useState<number>(0)
  const [newKindId, setNewKindId] = useState<string>('')
  const [newKindZh, setNewKindZh] = useState<string>('')
  const [newKindEn, setNewKindEn] = useState<string>('')
  const [rulesJsonDraft, setRulesJsonDraft] = useState<string>('{}')
  const [rulesJsonError, setRulesJsonError] = useState<string>('')
  const [promptsJsonDraft, setPromptsJsonDraft] = useState<string>('{}')
  const [promptsJsonError, setPromptsJsonError] = useState<string>('')
  const [presetCatalog, setPresetCatalog] = useState<SchemaPreset[]>([])
  const [jumpFlash, setJumpFlash] = useState<'rules' | 'prompts' | ''>('')

  useEffect(() => {
    if (!jumpTarget) return
    const anchorId =
      jumpTarget === 'schema.rules_json'
        ? 'schema-rules-json'
        : jumpTarget === 'schema.prompts_json'
          ? 'schema-prompts-json'
          : ''
    if (!anchorId) return
    const el = document.getElementById(anchorId)
    if (!el) return
    el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    if (jumpFocusKey?.trim()) setInfo(`定位建议 key: ${jumpFocusKey}`)
    setJumpFlash(anchorId === 'schema-rules-json' ? 'rules' : 'prompts')
    const timer = window.setTimeout(() => setJumpFlash(''), 1800)
    return () => window.clearTimeout(timer)
  }, [jumpTarget, jumpFocusKey, jumpNonce])

  async function refresh(pt: PaperType) {
    setBusy(true)
    setError('')
    setInfo('')
    try {
      const [s, vs] = await Promise.all([
        apiGet<{ schema: Schema }>(`/schema/active?paper_type=${encodeURIComponent(pt)}`),
        apiGet<{ versions: Array<{ version: number; name?: string }> }>(`/schema/versions?paper_type=${encodeURIComponent(pt)}`),
      ])
      setSchema(s.schema)
      setBaselineJson(JSON.stringify(s.schema))
      setVersions(
        (vs.versions ?? []).map((x) => ({
          version: Number(x.version),
          name: String(x.name ?? '').trim() || undefined,
        })),
      )
      try {
        const ps = await apiGet<{ presets: SchemaPreset[] }>('/schema/presets')
        setPresetCatalog(Array.isArray(ps.presets) ? ps.presets : [])
      } catch {
        setPresetCatalog([])
      }
      setActivateVersion('')
    } catch (e: unknown) {
      setError(String((e as { message?: unknown } | null)?.message ?? e))
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    refresh(paperType).catch(() => {})
  }, [paperType])

  useEffect(() => {
    if (!schema) return
    try {
      setRulesJsonDraft(JSON.stringify(schema.rules ?? {}, null, 2))
      setRulesJsonError('')
    } catch {
      setRulesJsonDraft('{}')
      setRulesJsonError('')
    }
    try {
      setPromptsJsonDraft(JSON.stringify(schema.prompts ?? {}, null, 2))
      setPromptsJsonError('')
    } catch {
      setPromptsJsonDraft('{}')
      setPromptsJsonError('')
    }
  }, [schema])

  const dirty = useMemo(() => {
    if (!schema || !baselineJson) return false
    try {
      return JSON.stringify(schema) !== baselineJson
    } catch {
      return false
    }
  }, [baselineJson, schema])

  type Tab = 'steps' | 'points' | 'rules' | 'prompts'
  const tab = useMemo(() => {
    const t = String(searchParams.get('tab') ?? '').trim()
    if (t === 'points' || t === 'rules' || t === 'prompts' || t === 'steps') return t
    return 'steps' as const
  }, [searchParams])

  function selectTab(t: Tab) {
    const next = new URLSearchParams(searchParams)
    next.set('tab', t)
    setSearchParams(next, { replace: true })
  }

  const steps = useMemo(() => (schema?.steps ?? []).slice().sort((a, b) => intOr(a.order, 0) - intOr(b.order, 0)), [schema])
  const kinds = useMemo(() => (schema?.claim_kinds ?? []).slice(), [schema])

  function updateStep(id: string, patch: Partial<Schema['steps'][number]>) {
    if (!schema) return
    const next = clone(schema)
    next.steps = next.steps.map((s) => (s.id === id ? { ...s, ...patch } : s))
    setSchema(next)
  }

  function updateKind(id: string, patch: Partial<Schema['claim_kinds'][number]>) {
    if (!schema) return
    const next = clone(schema)
    next.claim_kinds = next.claim_kinds.map((k) => (k.id === id ? { ...k, ...patch } : k))
    setSchema(next)
  }

  function updateRule(key: string, value: unknown) {
    if (!schema) return
    const next = clone(schema)
    next.rules = { ...(next.rules ?? {}), [key]: value }
    setSchema(next)
  }

  function updateSchemaName(value: string) {
    if (!schema) return
    const next = clone(schema)
    const trimmed = String(value ?? '').trim()
    if (trimmed) next.name = trimmed
    else delete next.name
    setSchema(next)
  }

  function versionOptionLabel(item: { version: number; name?: string }): string {
    const custom = String(item.name ?? '').trim()
    if (!custom) return `v${item.version}`
    return `${custom} (v${item.version})`
  }

  function applyRulesJson() {
    if (!schema) return
    try {
      const parsed = JSON.parse(rulesJsonDraft)
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        setRulesJsonError('rules JSON 必须是对象')
        return
      }
      const next = clone(schema)
      next.rules = parsed as Record<string, unknown>
      setSchema(next)
      setRulesJsonError('')
      setInfo('已应用 Rules JSON 草稿。')
    } catch (e: unknown) {
      setRulesJsonError(String((e as { message?: unknown } | null)?.message ?? e))
    }
  }

  function updatePrompt(key: string, value: string) {
    if (!schema) return
    const next = clone(schema)
    const prompts: Record<string, string> = { ...(next.prompts ?? {}) }
    // Treat empty as "no override" (fall back to default prompts on backend).
    if (!value.trim()) delete prompts[key]
    else prompts[key] = value
    next.prompts = Object.keys(prompts).length ? prompts : undefined
    setSchema(next)
  }

  function clearPrompt(key: string) {
    if (!schema) return
    const next = clone(schema)
    const prompts: Record<string, string> = { ...(next.prompts ?? {}) }
    delete prompts[key]
    next.prompts = Object.keys(prompts).length ? prompts : undefined
    setSchema(next)
  }

  function applyPromptsJson() {
    if (!schema) return
    try {
      const parsed = JSON.parse(promptsJsonDraft)
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        setPromptsJsonError('prompts JSON 必须是对象')
        return
      }
      const next = clone(schema)
      const out: Record<string, string> = {}
      for (const [k, v] of Object.entries(parsed)) {
        const key = String(k ?? '').trim()
        if (!key) continue
        const value = String(v ?? '').trim()
        if (value) out[key] = value
      }
      next.prompts = Object.keys(out).length ? out : undefined
      setSchema(next)
      setPromptsJsonError('')
      setInfo('已应用 Prompts JSON 草稿。')
    } catch (e: unknown) {
      setPromptsJsonError(String((e as { message?: unknown } | null)?.message ?? e))
    }
  }

  function fillDefaultPrompts() {
    if (!schema) return
    const next = clone(schema)
    next.prompts = { ...(DEFAULT_PROMPTS ?? {}), ...(next.prompts ?? {}) }
    setSchema(next)
    setInfo('已填入默认提示词（未覆盖你已编辑的项）。')
  }

  function promptValue(key: string): string {
    if (!schema) return ''
    const v = (schema.prompts ?? {})[key]
    if (typeof v === 'string' && v.length > 0) return v
    return String((DEFAULT_PROMPTS as Record<string, string>)[key] ?? '')
  }

  function removeStep(id: string) {
    if (!schema) return
    const next = clone(schema)
    next.steps = next.steps.filter((s) => s.id !== id)
    if (next.steps.length < 1) return
    setSchema(next)
  }

  function removeKind(id: string) {
    if (!schema) return
    const next = clone(schema)
    next.claim_kinds = next.claim_kinds.filter((k) => k.id !== id)
    if (next.claim_kinds.length < 1) return
    setSchema(next)
  }

  const canAddStep = useMemo(() => {
    if (!schema) return false
    const id = newStepId.trim()
    if (!ID_RE.test(id)) return false
    const exists = (schema.steps ?? []).some((s) => s.id === id)
    return !exists
  }, [newStepId, schema])

  const canAddKind = useMemo(() => {
    if (!schema) return false
    const id = newKindId.trim()
    if (!ID_RE.test(id)) return false
    const exists = (schema.claim_kinds ?? []).some((k) => k.id === id)
    return !exists
  }, [newKindId, schema])

  function addStep() {
    if (!schema || !canAddStep) return
    const next = clone(schema)
    next.steps = [
      ...(next.steps ?? []),
      { id: newStepId.trim(), label_zh: newStepZh.trim(), label_en: newStepEn.trim(), enabled: true, order: intOr(newStepOrder, 0) },
    ]
    setSchema(next)
    setNewStepId('')
    setNewStepZh('')
    setNewStepEn('')
    setNewStepOrder(0)
  }

  function addKind() {
    if (!schema || !canAddKind) return
    const next = clone(schema)
    next.claim_kinds = [
      ...(next.claim_kinds ?? []),
      { id: newKindId.trim(), label_zh: newKindZh.trim(), label_en: newKindEn.trim(), enabled: true },
    ]
    setSchema(next)
    setNewKindId('')
    setNewKindZh('')
    setNewKindEn('')
  }

  async function applyBuiltinPreset(presetId: string) {
    if (!schema || !presetId.trim()) return
    setBusy(true)
    setError('')
    setInfo('')
    try {
      const res = await apiPost<{ schema: Schema }>('/schema/presets/apply', {
        preset_id: presetId,
        schema,
      })
      setSchema(res.schema)
      const meta = presetCatalog.find((x) => x.id === presetId)
      setInfo(`已应用内置配置：${meta?.label_zh ?? presetId}。请点击“保存为新版本并激活”使其生效。`)
    } catch (e: unknown) {
      setError(String((e as { message?: unknown } | null)?.message ?? e))
    } finally {
      setBusy(false)
    }
  }

  async function saveNewVersion() {
    if (!schema) return
    setBusy(true)
    setError('')
    setInfo('')
    try {
      const schemaForSave: Schema = clone(schema)
      if (schemaForSave.prompts) {
        const p: Record<string, string> = {}
        for (const [k, v] of Object.entries(schemaForSave.prompts ?? {})) {
          const s = String(v ?? '')
          if (s.trim()) p[k] = s
        }
        schemaForSave.prompts = Object.keys(p).length ? p : undefined
      }
      const res = await apiPost<{ schema: Schema }>('/schema/new', {
        paper_type: paperType,
        schema: schemaForSave,
        activate: true,
      })
      setSchema(res.schema)
      const savedName = String(res.schema.name ?? '').trim()
      setInfo(savedName ? `已保存为新版本并激活：${savedName} (v${res.schema.version})` : `已保存为新版本并激活：v${res.schema.version}`)
      await refresh(paperType)
    } catch (e: unknown) {
      setError(String((e as { message?: unknown } | null)?.message ?? e))
    } finally {
      setBusy(false)
    }
  }

  async function activate() {
    const v = Number(activateVersion)
    if (!Number.isFinite(v) || v <= 0) return
    if (dirty && !window.confirm('当前有未保存改动，切换版本会丢失这些改动。确定继续吗？')) return
    setBusy(true)
    setError('')
    setInfo('')
    try {
      const res = await apiPost<{ schema: Schema }>('/schema/activate', { paper_type: paperType, version: Math.trunc(v) })
      setInfo(`已切换到版本：v${res.schema.version}`)
      await refresh(paperType)
    } catch (e: unknown) {
      setError(String((e as { message?: unknown } | null)?.message ?? e))
    } finally {
      setBusy(false)
    }
  }

  async function deleteSelectedVersion() {
    const v = Number(activateVersion)
    if (!schema || !Number.isFinite(v) || v <= 0) return
    if (versions.length <= 1) {
      setError('至少需要保留一个版本，无法删除最后一个版本。')
      return
    }
    if (dirty && !window.confirm('当前有未保存改动，删除版本后会刷新并丢失这些改动。确定继续吗？')) return
    const vv = Math.trunc(v)
    const selected = versions.find((x) => x.version === vv)
    const label = selected ? versionOptionLabel(selected) : `v${vv}`
    const isActive = vv === intOr(schema.version, 0)
    const msg = isActive
      ? `确定删除版本 ${label} 吗？\n该版本当前处于激活状态，删除后会自动切换到其余最新版本。`
      : `确定删除版本 ${label} 吗？`
    if (!window.confirm(msg)) return

    setBusy(true)
    setError('')
    setInfo('')
    try {
      const res = await apiDelete<{ ok: boolean; deleted_version: number; active_version: number; active_changed: boolean }>(
        `/schema/version/${vv}?paper_type=${encodeURIComponent(paperType)}`,
      )
      setInfo(
        res.active_changed
          ? `已删除 v${res.deleted_version}，当前已切换到 v${res.active_version}。`
          : `已删除 v${res.deleted_version}。`,
      )
      await refresh(paperType)
    } catch (e: unknown) {
      setError(String((e as { message?: unknown } | null)?.message ?? e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page">
      <div className="pageHeader">
        <div>
          <h2 className="pageTitle">Schema（可配置）</h2>
          <div className="pageSubtitle">在默认配置基础上自定义：逻辑链步骤、要点(Claim)类型、数量区间与规则（对未来重建生效）</div>
        </div>
        <div className="pageActions">
          <select
            className="select"
            style={{ width: 200 }}
            value={paperType}
            onChange={(e) => {
              const next = e.target.value as PaperType
              if (next === paperType) return
              if (dirty && !window.confirm('当前有未保存改动，切换论文类型会丢失这些改动。确定继续吗？')) return
              setPaperType(next)
            }}
          >
            <option value="research">研究型(Research)</option>
            <option value="review">综述型(Review)</option>
            <option value="software">软件型(Software)</option>
            <option value="theoretical">理论型(Theoretical)</option>
            <option value="case_study">案例型(Case Study)</option>
          </select>
          <button
            className="btn"
            disabled={busy}
            onClick={() => {
              if (dirty && !window.confirm('当前有未保存改动，刷新会丢失这些改动。确定继续吗？')) return
              refresh(paperType).catch(() => {})
            }}
          >
            {busy ? '加载中…' : '刷新'}
          </button>
        </div>
      </div>

      {error && <div className="errorBox">{error}</div>}
      {info && <div className="infoBox">{info}</div>}

      {!schema ? (
        <div className="panel">
          <div className="panelBody">加载中…</div>
        </div>
      ) : (
        <div className="stack">
          <div className="panel">
            <div className="panelHeader">
              <div className="split">
                <div className="panelTitle">版本</div>
                <div className="row">
                  {dirty && (
                    <span className="pill">
                      <span className="kicker">未保存</span> 有改动
                    </span>
                  )}
                  <span className="pill">
                    <span className="kicker">当前</span> {schema.name?.trim() ? `${schema.name} (v${schema.version})` : `v${schema.version}`}
                  </span>
                </div>
              </div>
            </div>
            <div className="panelBody">
              <div className="row" style={{ marginBottom: 10, alignItems: 'center' }}>
                <span className="kicker" style={{ minWidth: 92 }}>
                  版本名称
                </span>
                <input
                  className="input"
                  style={{ maxWidth: 320 }}
                  value={String(schema.name ?? '')}
                  onChange={(e) => updateSchemaName(e.target.value)}
                  placeholder="例如：高精度-力学论文"
                  maxLength={80}
                />
                <span className="hint">保存新版本时会写入此名称（用于“切换版本”下拉展示）</span>
              </div>
              <div className="row">
                <button className="btn btnPrimary" disabled={busy} onClick={saveNewVersion}>
                  保存为新版本并激活
                </button>
                <span className="kicker">切换版本</span>
                <select className="select" style={{ minWidth: 220 }} value={activateVersion} onChange={(e) => setActivateVersion(e.target.value)}>
                  <option value="">选择版本…</option>
                  {versions.map((v) => (
                    <option key={v.version} value={String(v.version)}>
                      {versionOptionLabel(v)}
                    </option>
                  ))}
                </select>
                <button className="btn" disabled={busy || !activateVersion} onClick={activate}>
                  激活
                </button>
                <button className="btn btnDanger" disabled={busy || !activateVersion || versions.length <= 1} onClick={deleteSelectedVersion}>
                  删除版本
                </button>
              </div>
              <div className="hint" style={{ marginTop: 10 }}>
                提示：Schema 变更只影响未来的“重建/替换/新导入”。已入库论文的展示会按其记录的 schema_version 渲染。
              </div>
              <div className="hint" style={{ marginTop: 4 }}>
                版本删除规则：至少保留 1 个版本；若删除当前激活版本，系统会自动切换到剩余版本中的最新版本。
              </div>
            </div>
          </div>

          <div className="panel">
            <div className="panelHeader">
              <div className="panelTitle">内置抽取配置（策略模板）</div>
            </div>
            <div className="panelBody">
              <div className="hint">
                内置三套策略：高精度 / 均衡 / 高召回。每套都同时覆盖规则阈值与全部核心提示词（文档级抽取、证据选择、逻辑绑定、Chunk 抽取、引用目的分类）。
              </div>
              <div className="list" style={{ marginTop: 12 }}>
                {(presetCatalog ?? []).map((preset) => (
                  <div key={preset.id} className="itemCard">
                    <div className="split">
                      <div className="itemTitle">
                        {preset.label_zh || preset.id}
                        {preset.label_en ? <span className="kicker">（{preset.label_en}）</span> : null}
                      </div>
                      <button className="btn btnSmall" disabled={busy} onClick={() => applyBuiltinPreset(preset.id)}>
                        应用到当前草稿
                      </button>
                    </div>
                    {preset.summary_zh ? (
                      <div className="hint" style={{ marginTop: 6 }}>
                        {preset.summary_zh}
                      </div>
                    ) : null}
                    {preset.focus_zh ? (
                      <div className="hint" style={{ marginTop: 4 }}>
                        优化重点：{preset.focus_zh}
                      </div>
                    ) : null}
                    {preset.use_case_zh ? (
                      <div className="hint" style={{ marginTop: 2 }}>
                        适用场景：{preset.use_case_zh}
                      </div>
                    ) : null}
                  </div>
                ))}
              </div>
              {!presetCatalog.length && <div className="hint" style={{ marginTop: 8 }}>未加载到预设模板，请刷新后重试。</div>}
              <div className="hint" style={{ marginTop: 10 }}>
                应用模板后，请点击上方“保存为新版本并激活”；随后对论文执行“重建”才会按该策略重新抽取。
              </div>
            </div>
          </div>

          <div className="row" style={{ marginBottom: 6 }}>
            <span className="kicker">页面</span>
            <button className={`chip ${tab === 'steps' ? 'chipActive' : ''}`} onClick={() => selectTab('steps')}>
              逻辑节点
            </button>
            <button className={`chip ${tab === 'points' ? 'chipActive' : ''}`} onClick={() => selectTab('points')}>
              要点类型
            </button>
            <button className={`chip ${tab === 'rules' ? 'chipActive' : ''}`} onClick={() => selectTab('rules')}>
              规则
            </button>
            <button className={`chip ${tab === 'prompts' ? 'chipActive' : ''}`} onClick={() => selectTab('prompts')}>
              提示词
            </button>
          </div>

          {tab === 'steps' && (
          <div className="panel">
            <div className="panelHeader">
              <div className="panelTitle">逻辑节点(Logic Chain)</div>
            </div>
            <div className="panelBody">
              <div className="itemCard" style={{ marginBottom: 14 }}>
                <div className="itemTitle">新增步骤</div>
                <div className="hint" style={{ marginTop: 6 }}>
                  Step ID 需为 ASCII slug：以字母开头，允许字母/数字/下划线/短横线，最长 48 字符。
                </div>
                <div className="row" style={{ marginTop: 12, alignItems: 'center' }}>
                  <div className="kicker" style={{ width: 110 }}>
                    id
                  </div>
                  <input className="input" value={newStepId} onChange={(e) => setNewStepId(e.target.value)} placeholder="例如 Background2" />
                  <div className="kicker" style={{ width: 110, marginLeft: 10 }}>
                    order
                  </div>
                  <input className="input" style={{ width: 120 }} type="number" value={newStepOrder} onChange={(e) => setNewStepOrder(intOr(e.target.value, 0))} />
                </div>
                <div className="row" style={{ marginTop: 10 }}>
                  <div className="kicker" style={{ width: 110 }}>
                    中文标签
                  </div>
                  <input className="input" value={newStepZh} onChange={(e) => setNewStepZh(e.target.value)} placeholder="例如 背景补充" />
                </div>
                <div className="row" style={{ marginTop: 10 }}>
                  <div className="kicker" style={{ width: 110 }}>
                    英文标签
                  </div>
                  <input className="input" value={newStepEn} onChange={(e) => setNewStepEn(e.target.value)} placeholder="例如 Background (Alt)" />
                </div>
                <div className="row" style={{ marginTop: 12 }}>
                  <button className="btn btnPrimary" disabled={busy || !canAddStep} onClick={addStep}>
                    新增步骤
                  </button>
                  {!canAddStep && newStepId.trim() && <span className="kicker">ID 无效或已存在</span>}
                </div>
              </div>

              <div className="list">
                {steps.map((s) => (
                  <div key={s.id} className="itemCard">
                    <div className="split">
                      <div className="itemTitle">
                        <code>{s.id}</code>
                      </div>
                      <div className="row" style={{ gap: 10 }}>
                        <label className="row" style={{ gap: 8 }}>
                          <input type="checkbox" checked={!!s.enabled} onChange={(e) => updateStep(s.id, { enabled: e.target.checked })} />
                          <span className="kicker">启用</span>
                        </label>
                        <button className="btn btnSmall" disabled={busy || (schema.steps?.length ?? 0) <= 1} onClick={() => removeStep(s.id)}>
                          删除
                        </button>
                      </div>
                    </div>
                    <div className="row" style={{ marginTop: 10 }}>
                      <div style={{ width: 110 }} className="kicker">
                        顺序(order)
                      </div>
                      <input className="input" style={{ width: 120 }} type="number" value={intOr(s.order, 0)} onChange={(e) => updateStep(s.id, { order: intOr(e.target.value, 0) })} />
                    </div>
                    <div className="row" style={{ marginTop: 10 }}>
                      <div style={{ width: 110 }} className="kicker">
                        中文标签
                      </div>
                      <input className="input" value={String(s.label_zh ?? '')} onChange={(e) => updateStep(s.id, { label_zh: e.target.value })} />
                    </div>
                    <div className="row" style={{ marginTop: 10 }}>
                      <div style={{ width: 110 }} className="kicker">
                        英文标签
                      </div>
                      <input className="input" value={String(s.label_en ?? '')} onChange={(e) => updateStep(s.id, { label_en: e.target.value })} />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
          )}

          {tab === 'points' && (
          <div className="panel">
            <div className="panelHeader">
              <div className="panelTitle">要点类型(Claim Kinds)</div>
            </div>
            <div className="panelBody">
              <div className="itemCard" style={{ marginBottom: 14 }}>
                <div className="itemTitle">新增类型</div>
                <div className="hint" style={{ marginTop: 6 }}>
                  Kind ID 需为 ASCII slug（同上规则）。新增后需“保存为新版本并激活”，并在论文上执行“重建”才会生效。
                </div>
                <div className="row" style={{ marginTop: 12 }}>
                  <div className="kicker" style={{ width: 110 }}>
                    id
                  </div>
                  <input className="input" value={newKindId} onChange={(e) => setNewKindId(e.target.value)} placeholder="例如 Hypothesis" />
                </div>
                <div className="row" style={{ marginTop: 10 }}>
                  <div className="kicker" style={{ width: 110 }}>
                    中文标签
                  </div>
                  <input className="input" value={newKindZh} onChange={(e) => setNewKindZh(e.target.value)} placeholder="例如 假说" />
                </div>
                <div className="row" style={{ marginTop: 10 }}>
                  <div className="kicker" style={{ width: 110 }}>
                    英文标签
                  </div>
                  <input className="input" value={newKindEn} onChange={(e) => setNewKindEn(e.target.value)} placeholder="例如 Hypothesis" />
                </div>
                <div className="row" style={{ marginTop: 12 }}>
                  <button className="btn btnPrimary" disabled={busy || !canAddKind} onClick={addKind}>
                    新增类型
                  </button>
                  {!canAddKind && newKindId.trim() && <span className="kicker">ID 无效或已存在</span>}
                </div>
              </div>

              <div className="list">
                {kinds.map((k) => (
                  <div key={k.id} className="itemCard">
                    <div className="split">
                      <div className="itemTitle">
                        <code>{k.id}</code>
                      </div>
                      <div className="row" style={{ gap: 10 }}>
                        <label className="row" style={{ gap: 8 }}>
                          <input type="checkbox" checked={!!k.enabled} onChange={(e) => updateKind(k.id, { enabled: e.target.checked })} />
                          <span className="kicker">启用</span>
                        </label>
                        <button className="btn btnSmall" disabled={busy || (schema.claim_kinds?.length ?? 0) <= 1} onClick={() => removeKind(k.id)}>
                          删除
                        </button>
                      </div>
                    </div>
                    <div className="row" style={{ marginTop: 10 }}>
                      <div style={{ width: 110 }} className="kicker">
                        中文标签
                      </div>
                      <input className="input" value={String(k.label_zh ?? '')} onChange={(e) => updateKind(k.id, { label_zh: e.target.value })} />
                    </div>
                    <div className="row" style={{ marginTop: 10 }}>
                      <div style={{ width: 110 }} className="kicker">
                        英文标签
                      </div>
                      <input className="input" value={String(k.label_en ?? '')} onChange={(e) => updateKind(k.id, { label_en: e.target.value })} />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
          )}

          {tab === 'rules' && (
          <div className="panel">
            <div className="panelHeader">
              <div className="panelTitle">规则(Rules)</div>
            </div>
            <div className="panelBody">
              <details className="itemCard" open style={{ marginBottom: 10 }}>
                <summary style={{ cursor: 'pointer', fontWeight: 600 }}>核心规则（优先调整）</summary>
                <div style={{ marginTop: 10 }}>
              <div className="row">
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="claims_per_paper_min" label="claims_min" />
                  <input
                    className="input"
                    style={{ width: 110 }}
                    type="number"
                    value={intOr(schema.rules?.claims_per_paper_min, 24)}
                    onChange={(e) => updateRule('claims_per_paper_min', intOr(e.target.value, 24))}
                  />
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="claims_per_paper_max" label="claims_max" />
                  <input
                    className="input"
                    style={{ width: 110 }}
                    type="number"
                    value={intOr(schema.rules?.claims_per_paper_max, 48)}
                    onChange={(e) => updateRule('claims_per_paper_max', intOr(e.target.value, 48))}
                  />
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="machine_evidence_min" label="evidence_min" />
                  <input
                    className="input"
                    style={{ width: 110 }}
                    type="number"
                    value={intOr(schema.rules?.machine_evidence_min, 1)}
                    onChange={(e) => updateRule('machine_evidence_min', intOr(e.target.value, 1))}
                  />
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="machine_evidence_max" label="evidence_max" />
                  <input
                    className="input"
                    style={{ width: 110 }}
                    type="number"
                    value={intOr(schema.rules?.machine_evidence_max, 2)}
                    onChange={(e) => updateRule('machine_evidence_max', intOr(e.target.value, 2))}
                  />
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="logic_evidence_min" label="logic_evidence_min" />
                  <input
                    className="input"
                    style={{ width: 110 }}
                    type="number"
                    value={intOr((schema.rules as Record<string, unknown>)?.logic_evidence_min, 1)}
                    onChange={(e) => updateRule('logic_evidence_min', intOr(e.target.value, 1))}
                  />
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="logic_evidence_max" label="logic_evidence_max" />
                  <input
                    className="input"
                    style={{ width: 110 }}
                    type="number"
                    value={intOr((schema.rules as Record<string, unknown>)?.logic_evidence_max, 2)}
                    onChange={(e) => updateRule('logic_evidence_max', intOr(e.target.value, 2))}
                  />
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="evidence_verification" label="evidence_verify" />
                  <select
                    className="select"
                    style={{ width: 150 }}
                    value={String((schema.rules as Record<string, unknown>)?.evidence_verification ?? 'llm')}
                    onChange={(e) => updateRule('evidence_verification', e.target.value)}
                  >
                    <option value="llm">大模型(LLM)</option>
                    <option value="off">关闭</option>
                  </select>
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="citation_context_sentence_window" label="citation_window" />
                  <input
                    className="input"
                    style={{ width: 110 }}
                    type="number"
                    value={intOr((schema.rules as Record<string, unknown>)?.citation_context_sentence_window, 1)}
                    onChange={(e) => updateRule('citation_context_sentence_window', intOr(e.target.value, 1))}
                  />
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="targets_per_claim_max" label="targets_per_claim_max" />
                  <input
                    className="input"
                    style={{ width: 110 }}
                    type="number"
                    value={intOr((schema.rules as Record<string, unknown>)?.targets_per_claim_max, 3)}
                    onChange={(e) => updateRule('targets_per_claim_max', intOr(e.target.value, 3))}
                  />
                </div>
              </div>
              <div className="row" style={{ marginTop: 10 }}>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="phase1_filter_reference_sections" label="phase1_filter_reference_sections" />
                  <select
                    className="input"
                    style={{ width: 120 }}
                    value={((schema.rules as Record<string, unknown>)?.phase1_filter_reference_sections ?? true) ? 'on' : 'off'}
                    onChange={(e) => updateRule('phase1_filter_reference_sections', e.target.value === 'on')}
                  >
                    <option value="on">on</option>
                    <option value="off">off</option>
                  </select>
                </div>
                <div className="pill" style={{ gap: 10, minWidth: 560 }}>
                  <RuleMeta ruleKey="phase1_excluded_section_terms" label="phase1_excluded_section_terms(csv)" />
                  <input
                    className="input"
                    value={csvFromRule((schema.rules as Record<string, unknown>)?.phase1_excluded_section_terms)}
                    onChange={(e) => updateRule('phase1_excluded_section_terms', parseCsvList(e.target.value))}
                    placeholder="例如: references, bibliography, 参考文献"
                  />
                </div>
              </div>
              <div className="row" style={{ marginTop: 10 }}>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="phase1_claim_worker_count" label="phase1_workers" />
                  <input
                    className="input"
                    style={{ width: 110 }}
                    type="number"
                    value={intOr((schema.rules as Record<string, unknown>)?.phase1_claim_worker_count, 3)}
                    onChange={(e) => updateRule('phase1_claim_worker_count', intOr(e.target.value, 3))}
                  />
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="phase1_logic_chunks_max" label="phase1_logic_chunks_max" />
                  <input
                    className="input"
                    style={{ width: 110 }}
                    type="number"
                    value={intOr((schema.rules as Record<string, unknown>)?.phase1_logic_chunks_max, 56)}
                    onChange={(e) => updateRule('phase1_logic_chunks_max', intOr(e.target.value, 56))}
                  />
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="phase1_claim_chunks_max" label="phase1_claim_chunks_max" />
                  <input
                    className="input"
                    style={{ width: 110 }}
                    type="number"
                    value={intOr((schema.rules as Record<string, unknown>)?.phase1_claim_chunks_max, 36)}
                    onChange={(e) => updateRule('phase1_claim_chunks_max', intOr(e.target.value, 36))}
                  />
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="phase1_claims_per_chunk_max" label="phase1_claims_per_chunk_max" />
                  <input
                    className="input"
                    style={{ width: 110 }}
                    type="number"
                    value={intOr((schema.rules as Record<string, unknown>)?.phase1_claims_per_chunk_max, 3)}
                    onChange={(e) => updateRule('phase1_claims_per_chunk_max', intOr(e.target.value, 3))}
                  />
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="phase1_chunk_chars_max" label="phase1_chunk_chars_max" />
                  <input
                    className="input"
                    style={{ width: 120 }}
                    type="number"
                    value={intOr((schema.rules as Record<string, unknown>)?.phase1_chunk_chars_max, 1800)}
                    onChange={(e) => updateRule('phase1_chunk_chars_max', intOr(e.target.value, 1800))}
                  />
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="phase1_logic_chunk_chars_max" label="phase1_logic_chunk_chars_max" />
                  <input
                    className="input"
                    style={{ width: 120 }}
                    type="number"
                    value={intOr((schema.rules as Record<string, unknown>)?.phase1_logic_chunk_chars_max, 420)}
                    onChange={(e) => updateRule('phase1_logic_chunk_chars_max', intOr(e.target.value, 420))}
                  />
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="phase1_doc_chars_max" label="phase1_doc_chars_max" />
                  <input
                    className="input"
                    style={{ width: 120 }}
                    type="number"
                    value={intOr((schema.rules as Record<string, unknown>)?.phase1_doc_chars_max, 18000)}
                    onChange={(e) => updateRule('phase1_doc_chars_max', intOr(e.target.value, 18000))}
                  />
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="phase1_evidence_verify_batch_size" label="phase1_evidence_batch_size" />
                  <input
                    className="input"
                    style={{ width: 120 }}
                    type="number"
                    value={intOr((schema.rules as Record<string, unknown>)?.phase1_evidence_verify_batch_size, 6)}
                    onChange={(e) => updateRule('phase1_evidence_verify_batch_size', intOr(e.target.value, 6))}
                  />
                </div>
              </div>
              <div className="row" style={{ marginTop: 10 }}>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="phase1_logic_lexical_topk_min" label="phase1_logic_lexical_topk_min" />
                  <input
                    className="input"
                    style={{ width: 120 }}
                    type="number"
                    value={intOr((schema.rules as Record<string, unknown>)?.phase1_logic_lexical_topk_min, 6)}
                    onChange={(e) => updateRule('phase1_logic_lexical_topk_min', intOr(e.target.value, 6))}
                  />
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="phase1_logic_lexical_topk_multiplier" label="phase1_logic_lexical_topk_multiplier" />
                  <input
                    className="input"
                    style={{ width: 120 }}
                    type="number"
                    value={intOr((schema.rules as Record<string, unknown>)?.phase1_logic_lexical_topk_multiplier, 3)}
                    onChange={(e) => updateRule('phase1_logic_lexical_topk_multiplier', intOr(e.target.value, 3))}
                  />
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="phase1_logic_evidence_weak_score_threshold" label="phase1_logic_evidence_weak_score_threshold" />
                  <input
                    className="input"
                    style={{ width: 140 }}
                    type="number"
                    step="0.1"
                    min={0}
                    value={floatOr((schema.rules as Record<string, unknown>)?.phase1_logic_evidence_weak_score_threshold, 2.0)}
                    onChange={(e) => updateRule('phase1_logic_evidence_weak_score_threshold', floatOr(e.target.value, 2.0))}
                  />
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="phase1_evidence_lexical_topk" label="phase1_evidence_lexical_topk" />
                  <input
                    className="input"
                    style={{ width: 120 }}
                    type="number"
                    value={intOr((schema.rules as Record<string, unknown>)?.phase1_evidence_lexical_topk, 10)}
                    onChange={(e) => updateRule('phase1_evidence_lexical_topk', intOr(e.target.value, 10))}
                  />
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="phase1_evidence_verify_candidates_max" label="phase1_evidence_verify_candidates_max" />
                  <input
                    className="input"
                    style={{ width: 120 }}
                    type="number"
                    value={intOr((schema.rules as Record<string, unknown>)?.phase1_evidence_verify_candidates_max, 6)}
                    onChange={(e) => updateRule('phase1_evidence_verify_candidates_max', intOr(e.target.value, 6))}
                  />
                </div>
              </div>
              <div className="row" style={{ marginTop: 10 }}>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="phase1_gate_supported_ratio_min" label="gate_supported_min" />
                  <input
                    className="input"
                    style={{ width: 110 }}
                    type="number"
                    step="0.01"
                    min={0}
                    max={1}
                    value={floatOr((schema.rules as Record<string, unknown>)?.phase1_gate_supported_ratio_min, 0.5)}
                    onChange={(e) => updateRule('phase1_gate_supported_ratio_min', floatOr(e.target.value, 0.5))}
                  />
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="phase1_gate_step_coverage_min" label="gate_step_coverage_min" />
                  <input
                    className="input"
                    style={{ width: 110 }}
                    type="number"
                    step="0.01"
                    min={0}
                    max={1}
                    value={floatOr((schema.rules as Record<string, unknown>)?.phase1_gate_step_coverage_min, 0.4)}
                    onChange={(e) => updateRule('phase1_gate_step_coverage_min', floatOr(e.target.value, 0.4))}
                  />
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="phase2_gate_critical_slot_coverage_min" label="phase2_critical_slot_min" />
                  <input
                    className="input"
                    style={{ width: 110 }}
                    type="number"
                    step="0.01"
                    min={0}
                    max={1}
                    value={floatOr((schema.rules as Record<string, unknown>)?.phase2_gate_critical_slot_coverage_min, 0.4)}
                    onChange={(e) => updateRule('phase2_gate_critical_slot_coverage_min', floatOr(e.target.value, 0.4))}
                  />
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="phase2_gate_conflict_rate_max" label="phase2_conflict_rate_max" />
                  <input
                    className="input"
                    style={{ width: 110 }}
                    type="number"
                    step="0.01"
                    min={0}
                    max={1}
                    value={floatOr((schema.rules as Record<string, unknown>)?.phase2_gate_conflict_rate_max, 0.35)}
                    onChange={(e) => updateRule('phase2_gate_conflict_rate_max', floatOr(e.target.value, 0.35))}
                  />
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="phase2_conflict_mode" label="phase2_conflict_mode" />
                  <select
                    className="input"
                    style={{ width: 150 }}
                    value={String((schema.rules as Record<string, unknown>)?.phase2_conflict_mode ?? 'lexical')}
                    onChange={(e) => updateRule('phase2_conflict_mode', e.target.value)}
                  >
                    <option value="lexical">lexical</option>
                    <option value="hybrid">hybrid</option>
                    <option value="llm">llm</option>
                  </select>
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="phase2_conflict_semantic_threshold" label="phase2_conflict_semantic_threshold" />
                  <input
                    className="input"
                    style={{ width: 120 }}
                    type="number"
                    step="0.01"
                    min={0}
                    max={1}
                    value={floatOr((schema.rules as Record<string, unknown>)?.phase2_conflict_semantic_threshold, 0.75)}
                    onChange={(e) => updateRule('phase2_conflict_semantic_threshold', floatOr(e.target.value, 0.75))}
                  />
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="phase2_conflict_candidate_max_pairs" label="phase2_conflict_candidate_max_pairs" />
                  <input
                    className="input"
                    style={{ width: 120 }}
                    type="number"
                    min={1}
                    value={intOr((schema.rules as Record<string, unknown>)?.phase2_conflict_candidate_max_pairs, 120)}
                    onChange={(e) => updateRule('phase2_conflict_candidate_max_pairs', intOr(e.target.value, 120))}
                  />
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="phase2_conflict_shared_tokens_min" label="phase2_conflict_shared_tokens_min" />
                  <input
                    className="input"
                    style={{ width: 110 }}
                    type="number"
                    value={intOr((schema.rules as Record<string, unknown>)?.phase2_conflict_shared_tokens_min, 2)}
                    onChange={(e) => updateRule('phase2_conflict_shared_tokens_min', intOr(e.target.value, 2))}
                  />
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="phase2_conflict_samples_max" label="phase2_conflict_samples_max" />
                  <input
                    className="input"
                    style={{ width: 110 }}
                    type="number"
                    value={intOr((schema.rules as Record<string, unknown>)?.phase2_conflict_samples_max, 8)}
                    onChange={(e) => updateRule('phase2_conflict_samples_max', intOr(e.target.value, 8))}
                  />
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="phase2_conflict_gate_min_comparable_pairs" label="phase2_conflict_gate_min_comparable_pairs" />
                  <input
                    className="input"
                    style={{ width: 120 }}
                    type="number"
                    min={0}
                    value={intOr((schema.rules as Record<string, unknown>)?.phase2_conflict_gate_min_comparable_pairs, 3)}
                    onChange={(e) => updateRule('phase2_conflict_gate_min_comparable_pairs', intOr(e.target.value, 3))}
                  />
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="phase2_conflict_gate_min_conflict_pairs" label="phase2_conflict_gate_min_conflict_pairs" />
                  <input
                    className="input"
                    style={{ width: 120 }}
                    type="number"
                    min={0}
                    value={intOr((schema.rules as Record<string, unknown>)?.phase2_conflict_gate_min_conflict_pairs, 1)}
                    onChange={(e) => updateRule('phase2_conflict_gate_min_conflict_pairs', intOr(e.target.value, 1))}
                  />
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="phase2_quality_tier_strategy" label="phase2_quality_tier_strategy" />
                  <select
                    className="input"
                    style={{ width: 180 }}
                    value={String((schema.rules as Record<string, unknown>)?.phase2_quality_tier_strategy ?? 'a1_fail_count')}
                    onChange={(e) => updateRule('phase2_quality_tier_strategy', e.target.value)}
                  >
                    <option value="a1_fail_count">a1_fail_count</option>
                  </select>
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="phase2_quality_tier_yellow_max_failures" label="phase2_quality_tier_yellow_max_failures" />
                  <input
                    className="input"
                    style={{ width: 120 }}
                    type="number"
                    min={0}
                    value={intOr((schema.rules as Record<string, unknown>)?.phase2_quality_tier_yellow_max_failures, 1)}
                    onChange={(e) => updateRule('phase2_quality_tier_yellow_max_failures', intOr(e.target.value, 1))}
                  />
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="phase2_quality_tier_red_min_failures" label="phase2_quality_tier_red_min_failures" />
                  <input
                    className="input"
                    style={{ width: 120 }}
                    type="number"
                    min={1}
                    value={intOr((schema.rules as Record<string, unknown>)?.phase2_quality_tier_red_min_failures, 2)}
                    onChange={(e) => updateRule('phase2_quality_tier_red_min_failures', intOr(e.target.value, 2))}
                  />
                </div>
              </div>
                </div>
              </details>
              <details className="itemCard" style={{ marginBottom: 10 }}>
                <summary style={{ cursor: 'pointer', fontWeight: 600 }}>高级规则（词表 / Grounding / Citation）</summary>
                <div style={{ marginTop: 10 }}>
              <div className="row" style={{ marginTop: 10 }}>
                <div className="pill" style={{ gap: 10, minWidth: 560 }}>
                  <RuleMeta ruleKey="require_targets_for_kinds" label="require_targets_for_kinds(csv)" />
                  <input
                    className="input"
                    value={csvFromRule((schema.rules as Record<string, unknown>)?.require_targets_for_kinds)}
                    onChange={(e) => updateRule('require_targets_for_kinds', parseCsvList(e.target.value))}
                    placeholder="例如: Gap, Critique, Limitation, Comparison"
                  />
                </div>
              </div>
              <div className="row" style={{ marginTop: 10 }}>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="phase1_grounding_mode" label="phase1_grounding_mode" />
                  <select
                    className="input"
                    style={{ width: 150 }}
                    value={String((schema.rules as Record<string, unknown>)?.phase1_grounding_mode ?? 'lexical')}
                    onChange={(e) => updateRule('phase1_grounding_mode', e.target.value)}
                  >
                    <option value="lexical">lexical</option>
                    <option value="hybrid">hybrid</option>
                    <option value="llm">llm</option>
                  </select>
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="phase1_grounding_semantic_supported_min" label="phase1_grounding_semantic_supported_min" />
                  <input
                    className="input"
                    style={{ width: 120 }}
                    type="number"
                    step="0.01"
                    min={0}
                    max={1}
                    value={floatOr((schema.rules as Record<string, unknown>)?.phase1_grounding_semantic_supported_min, 0.75)}
                    onChange={(e) => updateRule('phase1_grounding_semantic_supported_min', floatOr(e.target.value, 0.75))}
                  />
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="phase1_grounding_semantic_weak_min" label="phase1_grounding_semantic_weak_min" />
                  <input
                    className="input"
                    style={{ width: 120 }}
                    type="number"
                    step="0.01"
                    min={0}
                    max={1}
                    value={floatOr((schema.rules as Record<string, unknown>)?.phase1_grounding_semantic_weak_min, 0.55)}
                    onChange={(e) => updateRule('phase1_grounding_semantic_weak_min', floatOr(e.target.value, 0.55))}
                  />
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="phase1_grounding_supported_overlap_min" label="grounding_supported_overlap_min" />
                  <input
                    className="input"
                    style={{ width: 120 }}
                    type="number"
                    step="0.01"
                    min={0}
                    max={1}
                    value={floatOr((schema.rules as Record<string, unknown>)?.phase1_grounding_supported_overlap_min, 0.65)}
                    onChange={(e) => updateRule('phase1_grounding_supported_overlap_min', floatOr(e.target.value, 0.65))}
                  />
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="phase1_grounding_weak_overlap_min" label="grounding_weak_overlap_min" />
                  <input
                    className="input"
                    style={{ width: 120 }}
                    type="number"
                    step="0.01"
                    min={0}
                    max={1}
                    value={floatOr((schema.rules as Record<string, unknown>)?.phase1_grounding_weak_overlap_min, 0.42)}
                    onChange={(e) => updateRule('phase1_grounding_weak_overlap_min', floatOr(e.target.value, 0.42))}
                  />
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="phase1_grounding_supported_score_substring" label="grounding_supported_score_substring" />
                  <input
                    className="input"
                    style={{ width: 120 }}
                    type="number"
                    step="0.01"
                    min={0}
                    max={1}
                    value={floatOr((schema.rules as Record<string, unknown>)?.phase1_grounding_supported_score_substring, 0.78)}
                    onChange={(e) => updateRule('phase1_grounding_supported_score_substring', floatOr(e.target.value, 0.78))}
                  />
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="phase1_grounding_supported_score_overlap" label="grounding_supported_score_overlap" />
                  <input
                    className="input"
                    style={{ width: 120 }}
                    type="number"
                    step="0.01"
                    min={0}
                    max={1}
                    value={floatOr((schema.rules as Record<string, unknown>)?.phase1_grounding_supported_score_overlap, 0.72)}
                    onChange={(e) => updateRule('phase1_grounding_supported_score_overlap', floatOr(e.target.value, 0.72))}
                  />
                </div>
              </div>
              <div className="row" style={{ marginTop: 10 }}>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="phase1_grounding_weak_score" label="grounding_weak_score" />
                  <input
                    className="input"
                    style={{ width: 120 }}
                    type="number"
                    step="0.01"
                    min={0}
                    max={1}
                    value={floatOr((schema.rules as Record<string, unknown>)?.phase1_grounding_weak_score, 0.55)}
                    onChange={(e) => updateRule('phase1_grounding_weak_score', floatOr(e.target.value, 0.55))}
                  />
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="phase1_grounding_insufficient_score" label="grounding_insufficient_score" />
                  <input
                    className="input"
                    style={{ width: 120 }}
                    type="number"
                    step="0.01"
                    min={0}
                    max={1}
                    value={floatOr((schema.rules as Record<string, unknown>)?.phase1_grounding_insufficient_score, 0.18)}
                    onChange={(e) => updateRule('phase1_grounding_insufficient_score', floatOr(e.target.value, 0.18))}
                  />
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="phase1_grounding_unsupported_score" label="grounding_unsupported_score" />
                  <input
                    className="input"
                    style={{ width: 120 }}
                    type="number"
                    step="0.01"
                    min={0}
                    max={1}
                    value={floatOr((schema.rules as Record<string, unknown>)?.phase1_grounding_unsupported_score, 0.22)}
                    onChange={(e) => updateRule('phase1_grounding_unsupported_score', floatOr(e.target.value, 0.22))}
                  />
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="phase1_grounding_empty_score" label="grounding_empty_score" />
                  <input
                    className="input"
                    style={{ width: 120 }}
                    type="number"
                    step="0.01"
                    min={0}
                    max={1}
                    value={floatOr((schema.rules as Record<string, unknown>)?.phase1_grounding_empty_score, 0.0)}
                    onChange={(e) => updateRule('phase1_grounding_empty_score', floatOr(e.target.value, 0.0))}
                  />
                </div>
              </div>
              <div className="row" style={{ marginTop: 10 }}>
                <div className="pill" style={{ gap: 10, minWidth: 460 }}>
                  <RuleMeta ruleKey="phase2_conflict_positive_terms_en" label="phase2_conflict_positive_terms_en(csv)" />
                  <input
                    className="input"
                    value={csvFromRule((schema.rules as Record<string, unknown>)?.phase2_conflict_positive_terms_en)}
                    onChange={(e) => updateRule('phase2_conflict_positive_terms_en', parseCsvList(e.target.value))}
                  />
                </div>
                <div className="pill" style={{ gap: 10, minWidth: 460 }}>
                  <RuleMeta ruleKey="phase2_conflict_negative_terms_en" label="phase2_conflict_negative_terms_en(csv)" />
                  <input
                    className="input"
                    value={csvFromRule((schema.rules as Record<string, unknown>)?.phase2_conflict_negative_terms_en)}
                    onChange={(e) => updateRule('phase2_conflict_negative_terms_en', parseCsvList(e.target.value))}
                  />
                </div>
              </div>
              <div className="row" style={{ marginTop: 10 }}>
                <div className="pill" style={{ gap: 10, minWidth: 460 }}>
                  <RuleMeta ruleKey="phase2_conflict_positive_terms_zh" label="phase2_conflict_positive_terms_zh(csv)" />
                  <input
                    className="input"
                    value={csvFromRule((schema.rules as Record<string, unknown>)?.phase2_conflict_positive_terms_zh)}
                    onChange={(e) => updateRule('phase2_conflict_positive_terms_zh', parseCsvList(e.target.value))}
                  />
                </div>
                <div className="pill" style={{ gap: 10, minWidth: 460 }}>
                  <RuleMeta ruleKey="phase2_conflict_negative_terms_zh" label="phase2_conflict_negative_terms_zh(csv)" />
                  <input
                    className="input"
                    value={csvFromRule((schema.rules as Record<string, unknown>)?.phase2_conflict_negative_terms_zh)}
                    onChange={(e) => updateRule('phase2_conflict_negative_terms_zh', parseCsvList(e.target.value))}
                  />
                </div>
              </div>
              <div className="row" style={{ marginTop: 10 }}>
                <div className="pill" style={{ gap: 10, minWidth: 460 }}>
                  <RuleMeta ruleKey="phase2_conflict_stop_terms_en" label="phase2_conflict_stop_terms_en(csv)" />
                  <input
                    className="input"
                    value={csvFromRule((schema.rules as Record<string, unknown>)?.phase2_conflict_stop_terms_en)}
                    onChange={(e) => updateRule('phase2_conflict_stop_terms_en', parseCsvList(e.target.value))}
                  />
                </div>
                <div className="pill" style={{ gap: 10, minWidth: 460 }}>
                  <RuleMeta ruleKey="phase2_conflict_stop_terms_zh" label="phase2_conflict_stop_terms_zh(csv)" />
                  <input
                    className="input"
                    value={csvFromRule((schema.rules as Record<string, unknown>)?.phase2_conflict_stop_terms_zh)}
                    onChange={(e) => updateRule('phase2_conflict_stop_terms_zh', parseCsvList(e.target.value))}
                  />
                </div>
              </div>
              <div className="row" style={{ marginTop: 10 }}>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="citation_purpose_max_contexts_per_cite" label="citation_purpose_contexts_max" />
                  <input
                    className="input"
                    style={{ width: 120 }}
                    type="number"
                    value={intOr((schema.rules as Record<string, unknown>)?.citation_purpose_max_contexts_per_cite, 3)}
                    onChange={(e) => updateRule('citation_purpose_max_contexts_per_cite', intOr(e.target.value, 3))}
                  />
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="citation_purpose_max_context_chars" label="citation_purpose_context_chars_max" />
                  <input
                    className="input"
                    style={{ width: 120 }}
                    type="number"
                    value={intOr((schema.rules as Record<string, unknown>)?.citation_purpose_max_context_chars, 900)}
                    onChange={(e) => updateRule('citation_purpose_max_context_chars', intOr(e.target.value, 900))}
                  />
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="citation_purpose_max_cites_per_batch" label="citation_purpose_batch_max" />
                  <input
                    className="input"
                    style={{ width: 120 }}
                    type="number"
                    value={intOr((schema.rules as Record<string, unknown>)?.citation_purpose_max_cites_per_batch, 60)}
                    onChange={(e) => updateRule('citation_purpose_max_cites_per_batch', intOr(e.target.value, 60))}
                  />
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="citation_purpose_max_labels_per_cite" label="citation_purpose_labels_max" />
                  <input
                    className="input"
                    style={{ width: 120 }}
                    type="number"
                    value={intOr((schema.rules as Record<string, unknown>)?.citation_purpose_max_labels_per_cite, 3)}
                    onChange={(e) => updateRule('citation_purpose_max_labels_per_cite', intOr(e.target.value, 3))}
                  />
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="citation_purpose_fallback_score" label="citation_purpose_fallback_score" />
                  <input
                    className="input"
                    style={{ width: 120 }}
                    type="number"
                    step="0.01"
                    min={0}
                    max={1}
                    value={floatOr((schema.rules as Record<string, unknown>)?.citation_purpose_fallback_score, 0.4)}
                    onChange={(e) => updateRule('citation_purpose_fallback_score', floatOr(e.target.value, 0.4))}
                  />
                </div>
              </div>
              <div className="row" style={{ marginTop: 10 }}>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="reference_recovery_enabled" label="reference_recovery_enabled" />
                  <select
                    className="input"
                    value={((schema.rules as Record<string, unknown>)?.reference_recovery_enabled ?? true) ? 'on' : 'off'}
                    onChange={(e) => updateRule('reference_recovery_enabled', e.target.value === 'on')}
                  >
                    <option value="on">启用</option>
                    <option value="off">关闭</option>
                  </select>
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="reference_recovery_trigger_max_existing_refs" label="reference_recovery_trigger_max_existing_refs" />
                  <input
                    className="input"
                    style={{ width: 120 }}
                    type="number"
                    min={0}
                    max={200}
                    value={intOr((schema.rules as Record<string, unknown>)?.reference_recovery_trigger_max_existing_refs, 0)}
                    onChange={(e) => updateRule('reference_recovery_trigger_max_existing_refs', intOr(e.target.value, 0))}
                  />
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="reference_recovery_max_refs" label="reference_recovery_max_refs" />
                  <input
                    className="input"
                    style={{ width: 120 }}
                    type="number"
                    value={intOr((schema.rules as Record<string, unknown>)?.reference_recovery_max_refs, 180)}
                    onChange={(e) => updateRule('reference_recovery_max_refs', intOr(e.target.value, 180))}
                  />
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="reference_recovery_doc_chars_max" label="reference_recovery_doc_chars_max" />
                  <input
                    className="input"
                    style={{ width: 120 }}
                    type="number"
                    value={intOr((schema.rules as Record<string, unknown>)?.reference_recovery_doc_chars_max, 48000)}
                    onChange={(e) => updateRule('reference_recovery_doc_chars_max', intOr(e.target.value, 48000))}
                  />
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="reference_recovery_agent_timeout_sec" label="reference_recovery_agent_timeout_sec" />
                  <input
                    className="input"
                    style={{ width: 120 }}
                    type="number"
                    step="0.5"
                    min={0.5}
                    max={300}
                    value={floatOr((schema.rules as Record<string, unknown>)?.reference_recovery_agent_timeout_sec, 45)}
                    onChange={(e) => updateRule('reference_recovery_agent_timeout_sec', floatOr(e.target.value, 45))}
                  />
                </div>
              </div>
              <div className="row" style={{ marginTop: 10 }}>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="citation_event_recovery_enabled" label="citation_event_recovery_enabled" />
                  <select
                    className="input"
                    value={((schema.rules as Record<string, unknown>)?.citation_event_recovery_enabled ?? true) ? 'on' : 'off'}
                    onChange={(e) => updateRule('citation_event_recovery_enabled', e.target.value === 'on')}
                  >
                    <option value="on">启用</option>
                    <option value="off">关闭</option>
                  </select>
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="citation_event_recovery_trigger_max_existing_events" label="citation_event_recovery_trigger_max_existing_events" />
                  <input
                    className="input"
                    style={{ width: 120 }}
                    type="number"
                    min={0}
                    max={50}
                    value={intOr((schema.rules as Record<string, unknown>)?.citation_event_recovery_trigger_max_existing_events, 0)}
                    onChange={(e) => updateRule('citation_event_recovery_trigger_max_existing_events', intOr(e.target.value, 0))}
                  />
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="citation_event_recovery_max_events_per_chunk" label="citation_event_recovery_max_events_per_chunk" />
                  <input
                    className="input"
                    style={{ width: 120 }}
                    type="number"
                    min={1}
                    max={40}
                    value={intOr((schema.rules as Record<string, unknown>)?.citation_event_recovery_max_events_per_chunk, 6)}
                    onChange={(e) => updateRule('citation_event_recovery_max_events_per_chunk', intOr(e.target.value, 6))}
                  />
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="citation_event_recovery_context_chars" label="citation_event_recovery_context_chars" />
                  <input
                    className="input"
                    style={{ width: 120 }}
                    type="number"
                    min={120}
                    max={4000}
                    value={intOr((schema.rules as Record<string, unknown>)?.citation_event_recovery_context_chars, 800)}
                    onChange={(e) => updateRule('citation_event_recovery_context_chars', intOr(e.target.value, 800))}
                  />
                </div>
              </div>
              <div className="row" style={{ marginTop: 10 }}>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="citation_event_recovery_numeric_bracket_enabled" label="citation_event_recovery_numeric_bracket_enabled" />
                  <select
                    className="input"
                    value={((schema.rules as Record<string, unknown>)?.citation_event_recovery_numeric_bracket_enabled ?? true) ? 'on' : 'off'}
                    onChange={(e) => updateRule('citation_event_recovery_numeric_bracket_enabled', e.target.value === 'on')}
                  >
                    <option value="on">启用</option>
                    <option value="off">关闭</option>
                  </select>
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="citation_event_recovery_paren_numeric_enabled" label="citation_event_recovery_paren_numeric_enabled" />
                  <select
                    className="input"
                    value={((schema.rules as Record<string, unknown>)?.citation_event_recovery_paren_numeric_enabled ?? false) ? 'on' : 'off'}
                    onChange={(e) => updateRule('citation_event_recovery_paren_numeric_enabled', e.target.value === 'on')}
                  >
                    <option value="on">启用</option>
                    <option value="off">关闭</option>
                  </select>
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="citation_event_recovery_author_year_enabled" label="citation_event_recovery_author_year_enabled" />
                  <select
                    className="input"
                    value={((schema.rules as Record<string, unknown>)?.citation_event_recovery_author_year_enabled ?? true) ? 'on' : 'off'}
                    onChange={(e) => updateRule('citation_event_recovery_author_year_enabled', e.target.value === 'on')}
                  >
                    <option value="on">启用</option>
                    <option value="off">关闭</option>
                  </select>
                </div>
              </div>
              <div className="row" style={{ marginTop: 10 }}>
                <div className="pill" style={{ gap: 10, minWidth: 460 }}>
                  <RuleMeta ruleKey="phase2_critical_steps" label="phase2_critical_steps(csv)" />
                  <input
                    className="input"
                    value={csvFromRule((schema.rules as Record<string, unknown>)?.phase2_critical_steps)}
                    onChange={(e) => updateRule('phase2_critical_steps', parseCsvList(e.target.value))}
                    placeholder="例如: Background, Method, Result"
                  />
                </div>
                <div className="pill" style={{ gap: 10, minWidth: 460 }}>
                  <RuleMeta ruleKey="phase2_critical_kinds" label="phase2_critical_kinds(csv)" />
                  <input
                    className="input"
                    value={csvFromRule((schema.rules as Record<string, unknown>)?.phase2_critical_kinds)}
                    onChange={(e) => updateRule('phase2_critical_kinds', parseCsvList(e.target.value))}
                    placeholder="例如: Definition, Comparison"
                  />
                </div>
              </div>
              <div className="row" style={{ marginTop: 10 }}>
                <div className="pill" style={{ gap: 10, minWidth: 760 }}>
                  <RuleMeta ruleKey="phase2_critical_step_kind_map" label="phase2_critical_step_kind_map" />
                  <textarea
                    className="textarea"
                    style={{ minHeight: 90 }}
                    value={stepKindMapToText((schema.rules as Record<string, unknown>)?.phase2_critical_step_kind_map)}
                    onChange={(e) => updateRule('phase2_critical_step_kind_map', parseStepKindMap(e.target.value))}
                    placeholder={'每行一条：Step => KindA|KindB\n例如：\nMethod => Method|Comparison\nResult => Result|Comparison'}
                  />
                </div>
              </div>
              <div className="row" style={{ marginTop: 10 }}>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="phase2_auto_step_kind_map_enabled" label="phase2_auto_step_kind_map_enabled" />
                  <select
                    className="input"
                    style={{ width: 120 }}
                    value={((schema.rules as Record<string, unknown>)?.phase2_auto_step_kind_map_enabled ?? true) ? 'on' : 'off'}
                    onChange={(e) => updateRule('phase2_auto_step_kind_map_enabled', e.target.value === 'on')}
                  >
                    <option value="on">on</option>
                    <option value="off">off</option>
                  </select>
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="phase2_auto_step_kind_map_trigger_slots" label="phase2_auto_step_kind_map_trigger_slots" />
                  <input
                    className="input"
                    style={{ width: 120 }}
                    type="number"
                    min={1}
                    value={intOr((schema.rules as Record<string, unknown>)?.phase2_auto_step_kind_map_trigger_slots, 12)}
                    onChange={(e) => updateRule('phase2_auto_step_kind_map_trigger_slots', intOr(e.target.value, 12))}
                  />
                </div>
                <div className="pill" style={{ gap: 10 }}>
                  <RuleMeta ruleKey="phase2_auto_step_kind_map_max_kinds_per_step" label="phase2_auto_step_kind_map_max_kinds_per_step" />
                  <input
                    className="input"
                    style={{ width: 120 }}
                    type="number"
                    min={1}
                    max={6}
                    value={intOr((schema.rules as Record<string, unknown>)?.phase2_auto_step_kind_map_max_kinds_per_step, 1)}
                    onChange={(e) => updateRule('phase2_auto_step_kind_map_max_kinds_per_step', intOr(e.target.value, 1))}
                  />
                </div>
              </div>
                </div>
              </details>
              <div id="schema-rules-json" className={`itemCard${jumpFlash === 'rules' ? ' configJumpFlash' : ''}`} style={{ marginTop: 12 }}>
                <div className="split">
                  <div className="itemTitle">Rules JSON（高级，支持任意 key）</div>
                  <button className="btn btnSmall" disabled={busy} onClick={applyRulesJson}>
                    应用 JSON
                  </button>
                </div>
                <div className="hint" style={{ marginTop: 6 }}>
                  这里可编辑完整 rules 对象，覆盖页面未显式展示的任何规则项。
                </div>
                <textarea className="textarea" value={rulesJsonDraft} onChange={(e) => setRulesJsonDraft(e.target.value)} />
                {rulesJsonError && <div className="errorBox">{rulesJsonError}</div>}
              </div>
              <div className="hint" style={{ marginTop: 10 }}>
                保存后需要对论文执行“重建”才会按新规则重新生成逻辑链/要点/证据。
              </div>
            </div>
          </div>
          )}

          {tab === 'prompts' && (
          <div className="panel">
            <div className="panelHeader">
              <div className="panelTitle">提示词(Prompts)</div>
            </div>
            <div className="panelBody">
              <div className="hint">
                这是“高级配置”：可覆盖默认提示词。支持简单变量替换（形如 <code>{'{{title}}'}</code>）。推荐先只改 system，再逐步调 user_template。
                <br />
                <b>留空表示使用默认提示词</b>（不会清空；也不会影响已入库论文，需重建才生效）。
                <br />
                说明：提示词里仍使用 <code>claims</code> 字段名（系统内部 JSON key），但前端展示称为“要点”。
              </div>

              <div className="row" style={{ marginTop: 10 }}>
                <button className="btn" disabled={busy} onClick={fillDefaultPrompts}>
                  填入默认提示词
                </button>
              </div>

              <div className="list" style={{ marginTop: 12 }}>
                <details className="itemCard" open style={{ padding: 10 }}>
                  <summary style={{ cursor: 'pointer', fontWeight: 600 }}>核心提示词（文档级抽取 + 证据选择）</summary>
                  <div className="list" style={{ marginTop: 10 }}>
                <div className="itemCard">
                  <div className="split">
                    <div className="itemTitle">Logic/要点 提取：system</div>
                    <div className="row" style={{ gap: 8 }}>
                      <span className={schema.prompts?.logic_claims_system ? 'badge badgeOk' : 'badge'}>
                        {schema.prompts?.logic_claims_system ? '已覆盖' : '默认'}
                      </span>
                      <button className="btn btnSmall" disabled={busy || !schema.prompts?.logic_claims_system} onClick={() => clearPrompt('logic_claims_system')}>
                        清除覆盖
                      </button>
                    </div>
                  </div>
                  <div className="hint" style={{ marginTop: 6 }}>
                    {promptHelp('logic_claims_system').desc}
                  </div>
                  <textarea className="textarea" value={promptValue('logic_claims_system')} onChange={(e) => updatePrompt('logic_claims_system', e.target.value)} />
                </div>
                <div className="itemCard">
                  <div className="split">
                    <div className="itemTitle">Logic/要点 提取：user_template</div>
                    <div className="row" style={{ gap: 8 }}>
                      <span className={schema.prompts?.logic_claims_user_template ? 'badge badgeOk' : 'badge'}>
                        {schema.prompts?.logic_claims_user_template ? '已覆盖' : '默认'}
                      </span>
                      <button className="btn btnSmall" disabled={busy || !schema.prompts?.logic_claims_user_template} onClick={() => clearPrompt('logic_claims_user_template')}>
                        清除覆盖
                      </button>
                    </div>
                  </div>
                  <div className="hint" style={{ marginTop: 6 }}>
                    {promptHelp('logic_claims_user_template').desc}
                  </div>
                  <div className="hint" style={{ marginTop: 4 }}>
                    可用变量：<code>{promptHelp('logic_claims_user_template').vars ?? ''}</code>
                  </div>
                  <textarea className="textarea" value={promptValue('logic_claims_user_template')} onChange={(e) => updatePrompt('logic_claims_user_template', e.target.value)} />
                </div>

                <div className="itemCard">
                  <div className="split">
                    <div className="itemTitle">Evidence 选择：system</div>
                    <div className="row" style={{ gap: 8 }}>
                      <span className={schema.prompts?.evidence_pick_system ? 'badge badgeOk' : 'badge'}>
                        {schema.prompts?.evidence_pick_system ? '已覆盖' : '默认'}
                      </span>
                      <button className="btn btnSmall" disabled={busy || !schema.prompts?.evidence_pick_system} onClick={() => clearPrompt('evidence_pick_system')}>
                        清除覆盖
                      </button>
                    </div>
                  </div>
                  <div className="hint" style={{ marginTop: 6 }}>
                    {promptHelp('evidence_pick_system').desc}
                  </div>
                  <textarea className="textarea" value={promptValue('evidence_pick_system')} onChange={(e) => updatePrompt('evidence_pick_system', e.target.value)} />
                </div>
                <div className="itemCard">
                  <div className="split">
                    <div className="itemTitle">Evidence 选择：user_template</div>
                    <div className="row" style={{ gap: 8 }}>
                      <span className={schema.prompts?.evidence_pick_user_template ? 'badge badgeOk' : 'badge'}>
                        {schema.prompts?.evidence_pick_user_template ? '已覆盖' : '默认'}
                      </span>
                      <button className="btn btnSmall" disabled={busy || !schema.prompts?.evidence_pick_user_template} onClick={() => clearPrompt('evidence_pick_user_template')}>
                        清除覆盖
                      </button>
                    </div>
                  </div>
                  <div className="hint" style={{ marginTop: 6 }}>
                    {promptHelp('evidence_pick_user_template').desc}
                  </div>
                  <div className="hint" style={{ marginTop: 4 }}>
                    可用变量：<code>{promptHelp('evidence_pick_user_template').vars ?? ''}</code>
                  </div>
                  <textarea className="textarea" value={promptValue('evidence_pick_user_template')} onChange={(e) => updatePrompt('evidence_pick_user_template', e.target.value)} />
                </div>
                  </div>
                </details>

                <details className="itemCard" style={{ padding: 10 }}>
                  <summary style={{ cursor: 'pointer', fontWeight: 600 }}>语义裁判提示词（Grounding + 冲突判定）</summary>
                  <div className="list" style={{ marginTop: 10 }}>
                    <div className="itemCard">
                      <div className="split">
                        <div className="itemTitle">Grounding 语义裁判：system</div>
                        <div className="row" style={{ gap: 8 }}>
                          <span className={schema.prompts?.phase1_grounding_judge_system ? 'badge badgeOk' : 'badge'}>
                            {schema.prompts?.phase1_grounding_judge_system ? '已覆盖' : '默认'}
                          </span>
                          <button className="btn btnSmall" disabled={busy || !schema.prompts?.phase1_grounding_judge_system} onClick={() => clearPrompt('phase1_grounding_judge_system')}>
                            清除覆盖
                          </button>
                        </div>
                      </div>
                      <div className="hint" style={{ marginTop: 6 }}>
                        {promptHelp('phase1_grounding_judge_system').desc}
                      </div>
                      <textarea className="textarea" value={promptValue('phase1_grounding_judge_system')} onChange={(e) => updatePrompt('phase1_grounding_judge_system', e.target.value)} />
                    </div>
                    <div className="itemCard">
                      <div className="split">
                        <div className="itemTitle">Grounding 语义裁判：user_template</div>
                        <div className="row" style={{ gap: 8 }}>
                          <span className={schema.prompts?.phase1_grounding_judge_user_template ? 'badge badgeOk' : 'badge'}>
                            {schema.prompts?.phase1_grounding_judge_user_template ? '已覆盖' : '默认'}
                          </span>
                          <button className="btn btnSmall" disabled={busy || !schema.prompts?.phase1_grounding_judge_user_template} onClick={() => clearPrompt('phase1_grounding_judge_user_template')}>
                            清除覆盖
                          </button>
                        </div>
                      </div>
                      <div className="hint" style={{ marginTop: 6 }}>
                        {promptHelp('phase1_grounding_judge_user_template').desc}
                      </div>
                      <div className="hint" style={{ marginTop: 4 }}>
                        可用变量：<code>{promptHelp('phase1_grounding_judge_user_template').vars ?? ''}</code>
                      </div>
                      <textarea className="textarea" value={promptValue('phase1_grounding_judge_user_template')} onChange={(e) => updatePrompt('phase1_grounding_judge_user_template', e.target.value)} />
                    </div>
                    <div className="itemCard">
                      <div className="split">
                        <div className="itemTitle">冲突语义裁判：system</div>
                        <div className="row" style={{ gap: 8 }}>
                          <span className={schema.prompts?.phase2_conflict_judge_system ? 'badge badgeOk' : 'badge'}>
                            {schema.prompts?.phase2_conflict_judge_system ? '已覆盖' : '默认'}
                          </span>
                          <button className="btn btnSmall" disabled={busy || !schema.prompts?.phase2_conflict_judge_system} onClick={() => clearPrompt('phase2_conflict_judge_system')}>
                            清除覆盖
                          </button>
                        </div>
                      </div>
                      <div className="hint" style={{ marginTop: 6 }}>
                        {promptHelp('phase2_conflict_judge_system').desc}
                      </div>
                      <textarea className="textarea" value={promptValue('phase2_conflict_judge_system')} onChange={(e) => updatePrompt('phase2_conflict_judge_system', e.target.value)} />
                    </div>
                    <div className="itemCard">
                      <div className="split">
                        <div className="itemTitle">冲突语义裁判：user_template</div>
                        <div className="row" style={{ gap: 8 }}>
                          <span className={schema.prompts?.phase2_conflict_judge_user_template ? 'badge badgeOk' : 'badge'}>
                            {schema.prompts?.phase2_conflict_judge_user_template ? '已覆盖' : '默认'}
                          </span>
                          <button className="btn btnSmall" disabled={busy || !schema.prompts?.phase2_conflict_judge_user_template} onClick={() => clearPrompt('phase2_conflict_judge_user_template')}>
                            清除覆盖
                          </button>
                        </div>
                      </div>
                      <div className="hint" style={{ marginTop: 6 }}>
                        {promptHelp('phase2_conflict_judge_user_template').desc}
                      </div>
                      <div className="hint" style={{ marginTop: 4 }}>
                        可用变量：<code>{promptHelp('phase2_conflict_judge_user_template').vars ?? ''}</code>
                      </div>
                      <textarea className="textarea" value={promptValue('phase2_conflict_judge_user_template')} onChange={(e) => updatePrompt('phase2_conflict_judge_user_template', e.target.value)} />
                    </div>
                  </div>
                </details>

                <details className="itemCard" style={{ padding: 10 }}>
                  <summary style={{ cursor: 'pointer', fontWeight: 600 }}>结构化抽取提示词（逻辑绑定 + Chunk抽取）</summary>
                  <div className="list" style={{ marginTop: 10 }}>
                <div className="itemCard">
                  <div className="split">
                    <div className="itemTitle">逻辑证据绑定：system</div>
                    <div className="row" style={{ gap: 8 }}>
                      <span className={schema.prompts?.phase1_logic_bind_system ? 'badge badgeOk' : 'badge'}>
                        {schema.prompts?.phase1_logic_bind_system ? '已覆盖' : '默认'}
                      </span>
                      <button className="btn btnSmall" disabled={busy || !schema.prompts?.phase1_logic_bind_system} onClick={() => clearPrompt('phase1_logic_bind_system')}>
                        清除覆盖
                      </button>
                    </div>
                  </div>
                  <div className="hint" style={{ marginTop: 6 }}>
                    {promptHelp('phase1_logic_bind_system').desc}
                  </div>
                  <textarea className="textarea" value={promptValue('phase1_logic_bind_system')} onChange={(e) => updatePrompt('phase1_logic_bind_system', e.target.value)} />
                </div>
                <div className="itemCard">
                  <div className="split">
                    <div className="itemTitle">逻辑证据绑定：user_template</div>
                    <div className="row" style={{ gap: 8 }}>
                      <span className={schema.prompts?.phase1_logic_bind_user_template ? 'badge badgeOk' : 'badge'}>
                        {schema.prompts?.phase1_logic_bind_user_template ? '已覆盖' : '默认'}
                      </span>
                      <button className="btn btnSmall" disabled={busy || !schema.prompts?.phase1_logic_bind_user_template} onClick={() => clearPrompt('phase1_logic_bind_user_template')}>
                        清除覆盖
                      </button>
                    </div>
                  </div>
                  <div className="hint" style={{ marginTop: 6 }}>
                    {promptHelp('phase1_logic_bind_user_template').desc}
                  </div>
                  <div className="hint" style={{ marginTop: 4 }}>
                    可用变量：<code>{promptHelp('phase1_logic_bind_user_template').vars ?? ''}</code>
                  </div>
                  <textarea className="textarea" value={promptValue('phase1_logic_bind_user_template')} onChange={(e) => updatePrompt('phase1_logic_bind_user_template', e.target.value)} />
                </div>

                <div className="itemCard">
                  <div className="split">
                    <div className="itemTitle">Chunk 要点抽取：system</div>
                    <div className="row" style={{ gap: 8 }}>
                      <span className={schema.prompts?.phase1_chunk_claim_extract_system ? 'badge badgeOk' : 'badge'}>
                        {schema.prompts?.phase1_chunk_claim_extract_system ? '已覆盖' : '默认'}
                      </span>
                      <button className="btn btnSmall" disabled={busy || !schema.prompts?.phase1_chunk_claim_extract_system} onClick={() => clearPrompt('phase1_chunk_claim_extract_system')}>
                        清除覆盖
                      </button>
                    </div>
                  </div>
                  <div className="hint" style={{ marginTop: 6 }}>
                    {promptHelp('phase1_chunk_claim_extract_system').desc}
                  </div>
                  <textarea className="textarea" value={promptValue('phase1_chunk_claim_extract_system')} onChange={(e) => updatePrompt('phase1_chunk_claim_extract_system', e.target.value)} />
                </div>
                <div className="itemCard">
                  <div className="split">
                    <div className="itemTitle">Chunk 要点抽取：user_template</div>
                    <div className="row" style={{ gap: 8 }}>
                      <span className={schema.prompts?.phase1_chunk_claim_extract_user_template ? 'badge badgeOk' : 'badge'}>
                        {schema.prompts?.phase1_chunk_claim_extract_user_template ? '已覆盖' : '默认'}
                      </span>
                      <button className="btn btnSmall" disabled={busy || !schema.prompts?.phase1_chunk_claim_extract_user_template} onClick={() => clearPrompt('phase1_chunk_claim_extract_user_template')}>
                        清除覆盖
                      </button>
                    </div>
                  </div>
                  <div className="hint" style={{ marginTop: 6 }}>
                    {promptHelp('phase1_chunk_claim_extract_user_template').desc}
                  </div>
                  <div className="hint" style={{ marginTop: 4 }}>
                    可用变量：<code>{promptHelp('phase1_chunk_claim_extract_user_template').vars ?? ''}</code>
                  </div>
                  <textarea className="textarea" value={promptValue('phase1_chunk_claim_extract_user_template')} onChange={(e) => updatePrompt('phase1_chunk_claim_extract_user_template', e.target.value)} />
                </div>
                  </div>
                </details>

                <details className="itemCard" style={{ padding: 10 }}>
                  <summary style={{ cursor: 'pointer', fontWeight: 600 }}>引用目的提示词（Citation Purpose）</summary>
                  <div className="list" style={{ marginTop: 10 }}>
                <div className="itemCard">
                  <div className="split">
                    <div className="itemTitle">Citation Purpose（批量）：system</div>
                    <div className="row" style={{ gap: 8 }}>
                      <span className={schema.prompts?.citation_purpose_batch_system ? 'badge badgeOk' : 'badge'}>
                        {schema.prompts?.citation_purpose_batch_system ? '已覆盖' : '默认'}
                      </span>
                      <button className="btn btnSmall" disabled={busy || !schema.prompts?.citation_purpose_batch_system} onClick={() => clearPrompt('citation_purpose_batch_system')}>
                        清除覆盖
                      </button>
                    </div>
                  </div>
                  <div className="hint" style={{ marginTop: 6 }}>
                    {promptHelp('citation_purpose_batch_system').desc}
                  </div>
                  <textarea className="textarea" value={promptValue('citation_purpose_batch_system')} onChange={(e) => updatePrompt('citation_purpose_batch_system', e.target.value)} />
                </div>
                <div className="itemCard">
                  <div className="split">
                    <div className="itemTitle">Citation Purpose（批量）：user_template</div>
                    <div className="row" style={{ gap: 8 }}>
                      <span className={schema.prompts?.citation_purpose_batch_user_template ? 'badge badgeOk' : 'badge'}>
                        {schema.prompts?.citation_purpose_batch_user_template ? '已覆盖' : '默认'}
                      </span>
                      <button className="btn btnSmall" disabled={busy || !schema.prompts?.citation_purpose_batch_user_template} onClick={() => clearPrompt('citation_purpose_batch_user_template')}>
                        清除覆盖
                      </button>
                    </div>
                  </div>
                  <div className="hint" style={{ marginTop: 6 }}>
                    {promptHelp('citation_purpose_batch_user_template').desc}
                  </div>
                  <div className="hint" style={{ marginTop: 4 }}>
                    可用变量：<code>{promptHelp('citation_purpose_batch_user_template').vars ?? ''}</code>
                  </div>
                  <textarea className="textarea" value={promptValue('citation_purpose_batch_user_template')} onChange={(e) => updatePrompt('citation_purpose_batch_user_template', e.target.value)} />
                </div>
                  </div>
                </details>
                <details className="itemCard" style={{ padding: 10 }}>
                  <summary style={{ cursor: 'pointer', fontWeight: 600 }}>Reference Recovery（参考文献补抽）</summary>
                  <div className="list" style={{ marginTop: 10 }}>
                    <div className="itemCard">
                      <div className="split">
                        <div className="itemTitle">Reference Recovery：system</div>
                        <div className="row" style={{ gap: 8 }}>
                          <span className={schema.prompts?.reference_recovery_system ? 'badge badgeOk' : 'badge'}>
                            {schema.prompts?.reference_recovery_system ? '已覆盖' : '默认'}
                          </span>
                          <button className="btn btnSmall" disabled={busy || !schema.prompts?.reference_recovery_system} onClick={() => clearPrompt('reference_recovery_system')}>
                            清除覆盖
                          </button>
                        </div>
                      </div>
                      <div className="hint" style={{ marginTop: 6 }}>
                        {promptHelp('reference_recovery_system').desc}
                      </div>
                      <textarea className="textarea" value={promptValue('reference_recovery_system')} onChange={(e) => updatePrompt('reference_recovery_system', e.target.value)} />
                    </div>
                    <div className="itemCard">
                      <div className="split">
                        <div className="itemTitle">Reference Recovery：user_template</div>
                        <div className="row" style={{ gap: 8 }}>
                          <span className={schema.prompts?.reference_recovery_user_template ? 'badge badgeOk' : 'badge'}>
                            {schema.prompts?.reference_recovery_user_template ? '已覆盖' : '默认'}
                          </span>
                          <button className="btn btnSmall" disabled={busy || !schema.prompts?.reference_recovery_user_template} onClick={() => clearPrompt('reference_recovery_user_template')}>
                            清除覆盖
                          </button>
                        </div>
                      </div>
                      <div className="hint" style={{ marginTop: 6 }}>
                        {promptHelp('reference_recovery_user_template').desc}
                      </div>
                      <div className="hint" style={{ marginTop: 4 }}>
                        可用变量：<code>{promptHelp('reference_recovery_user_template').vars ?? ''}</code>
                      </div>
                      <textarea className="textarea" value={promptValue('reference_recovery_user_template')} onChange={(e) => updatePrompt('reference_recovery_user_template', e.target.value)} />
                    </div>
                  </div>
                </details>
              </div>

              <div id="schema-prompts-json" className={`itemCard${jumpFlash === 'prompts' ? ' configJumpFlash' : ''}`} style={{ marginTop: 12 }}>
                <div className="split">
                  <div className="itemTitle">Prompts JSON（高级，支持任意 key）</div>
                  <button className="btn btnSmall" disabled={busy} onClick={applyPromptsJson}>
                    应用 JSON
                  </button>
                </div>
                <div className="hint" style={{ marginTop: 6 }}>
                  这里可编辑完整 prompts 对象，支持新增任意 prompt key（后端按 key 读取）。
                </div>
                <textarea className="textarea" value={promptsJsonDraft} onChange={(e) => setPromptsJsonDraft(e.target.value)} />
                {promptsJsonError && <div className="errorBox">{promptsJsonError}</div>}
              </div>

              <div className="hint" style={{ marginTop: 10 }}>
                保存后对论文执行“重建”才会用新提示词生成；提示词写错可能导致 JSON 解析失败。
              </div>
            </div>
          </div>
          )}
        </div>
      )}
    </div>
  )
}
