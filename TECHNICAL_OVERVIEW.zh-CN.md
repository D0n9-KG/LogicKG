# LogicKG 项目技术文档

## 1. 文档目的

这份文档的目标，是从“系统实际如何运行”的角度，详细解释 `LogicKG` 项目的技术机制。它不是面向纯软件工程实现的源码注释，也不是面向普通用户的简化说明，而是面向具有一定科研和技术背景、希望理解系统内部逻辑的领域专家。文档重点回答的问题包括：文献进入系统后如何被解析和抽取、图谱如何构建和治理、系统如何选择搜索路径、科学问题如何被生成与打分、反馈如何反过来更新策略，以及主工作区与 worktree 工作区分别在这一体系中承担什么角色。

从研发结构上看，项目目前由两条工作线共同构成。主工作区负责较稳定的知识底座：文献导入、结构化抽取、图谱入库、问答检索、治理与配置中心。worktree `self-evolving-temporal-discovery` 则负责把这个底座推向更强的研究系统：在历史快照上提出科学问题、用未来窗口评价这些问题、根据反馈修图并生成后继问题。前者更像科研知识图谱平台，后者更像建立在该平台之上的自进化发现引擎。

## 2. 总体理解：这是一个两层系统，而不是一个单点功能

如果只从表面功能看，`LogicKG` 同时包含文献导入、知识抽取、图谱浏览、RAG 问答、发现模块、配置中心和自进化工作流，似乎很容易被理解成“多个功能拼在一起的科研工具”。但实际上，它更接近一个两层系统。

第一层是知识底座层。它的职责是把原始科研材料变成可计算、可治理、可追溯的结构化知识资产。这一层不追求“直接提出新问题”，而追求“让系统知道已有知识是什么、来自哪里、可靠程度如何、彼此如何连接”。第二层是发现与演化层。它把第一层沉淀下来的图谱当作研究环境，在这个环境中检测知识缺口、提出结构化科学问题、引入时间切片与未来反馈，并尝试通过修订图谱结构来改善下一代问题。

因此，这个项目的关键不在于某一个模型调用是否聪明，而在于它把“知识加工”和“问题演化”拆成了两个相互衔接的闭环：前一个闭环负责让知识变得可操作，后一个闭环负责让问题变得可进化。主工作区主要实现第一个闭环，worktree 主要实现第二个闭环。

## 3. 主工作区：科研知识图谱底座的实际运行流程

### 3.1 输入不是图谱，而是论文、教材和非结构化科研文本

主工作区面对的原始输入并不是图数据库中现成的节点和边，而是论文、教材、章节内容、参考文献上下文以及一系列典型的科研文档对象。系统在这一层首先做的事情，并不是“生成问题”，也不是“直接回答提问”，而是把这些非结构化材料转换成一套统一的中间表示。这个中间表示承接了文档的章节、段落、分块、元数据和来源标识，使后续抽取和证据追踪有明确对象可操作。

这一步的本质，是把“供人阅读的文档”变成“供系统加工的文档对象”。如果没有这一层，中后期所有的 claim、logic step、citation、graph evidence 和 research question 都无法追溯到原始文本。对于科研系统来说，可追溯性不是锦上添花，而是底线：任何后续结论都必须能够回链到原始文献片段或结构化证据来源。

### 3.2 抽取流水线不是单步 LLM 调用，而是阶段式编排

主工作区的抽取机制不是“把整篇论文交给模型，输出一堆结果”这么简单，而是一个带门控的分阶段编排流程。这个编排的总体思路可以概括为：先抽逻辑骨架，再抽原子 claim，再做 grounding 和质量门禁，最后才决定哪些结果进入图谱。

首先，系统会抽取论文的逻辑骨架，也就是不同研究步骤或逻辑阶段的结构，例如问题提出、方法、实验、结果、结论等。这个阶段的目标不是抽得细，而是为后续 claim 抽取提供结构约束。因为科学主张并不是均匀分布在全文中的，不同 claim 往往依附于不同的逻辑步骤。系统先拿到逻辑骨架，后面就可以按步骤组织证据，而不是在全文里无差别抽取。

在逻辑骨架形成后，系统再在更细粒度的 chunk 上抽取原子 claim。这里有两个关键约束。第一，每个 claim 必须直接受当前 chunk 文本支持，不能凭空泛化。第二，抽取结果不仅包含主张文本，还要求绑定证据片段或证据引用。也就是说，系统抽的不是“漂亮句子”，而是“带可验证证据的主张候选”。这一步的设计直接决定了图谱后续是否能承载科研推理，而不仅仅是承载文本摘要。

### 3.3 主工作区的抽取实际上是“两阶段门控”

主工作区抽取之所以稳定，关键在于它不是只抽取，还会把结果送入阶段性门控。第一阶段主要关注 grounding 和结构完整性，第二阶段主要关注冲突、关键槽位覆盖和整体质量分层。

第一阶段中，系统会对抽取出的 claim 做合并、去噪、grounding judgment 和结构性质量检查。grounding 部分既支持更偏 lexical 的检查，也支持 hybrid 或 LLM 风格的判断。系统会关注的不是“语义看起来差不多”而已，而是若干明确指标，例如 supported ratio、step coverage、evidence verification 结果、chunk fail rate，以及空 logic step 数量。换句话说，它会检查：抽取出的 claim 有多少真正被证据支持，有多少逻辑步骤被覆盖，有多少 chunk 由于抽取失败或低信息密度而无法形成可靠结果。只有通过这一阶段的门控，结果才适合进入后续图谱。

第二阶段则更像面向科研一致性的质量审计。系统会分析关键逻辑步骤是否被合理覆盖、关键槽位是否缺失、主张之间是否存在高冲突率、冲突是否达到需要警惕的程度，并将整体结果归入一个 quality tier。这里的 tier 不是装饰性的标签，而是一种浓缩的结构化诊断：当前这篇文献的结构化抽取究竟更接近“可直接入图”“可以保留但需复核”，还是“风险较高，不适合进入高信任图层”。

因此，主工作区的抽取结果并不是“模型说了算”，而是必须经过一系列结构性和证据性门槛。这种设计的价值在于：后续所有图谱搜索、问题发现与自进化，都会建立在较稳定的知识层之上，而不是直接建立在未经门控的原始抽取上。

### 3.4 图谱抽取策略如何定义：它由 schema、rules 和 prompts 三层共同决定

主工作区里所谓“抽取策略”，并不是一个隐藏在代码里的黑箱超参数集合，而是被明确建模为可版本化的 schema 对象。这个 schema 至少包含三层内容：第一层是论文类型、逻辑步骤和 claim kind 等结构性定义；第二层是 rules，也就是影响抽取与门控行为的阈值、窗口、批大小、top-k、coverage 与 conflict gate 等规则；第三层是 prompts，也就是控制逻辑抽取、chunk claim 抽取、grounding 判定、冲突判断、citation 目的判定等任务的提示词模板。

这种设计有两个直接后果。第一，抽取策略不再是“只能靠改代码更新”的实现细节，而是成为系统可管理的运行对象。第二，策略更新可以被版本化。系统支持创建新版本 schema、查看历史版本、激活某个版本、删除版本，以及在版本之间切换。因此，当团队希望从“高精度抽取”切换到“平衡模式”或“高召回模式”时，不需要重新实现整套流水线，只需要切换底层 schema 版本或套用相应 preset。

在具体参数层面，schema rules 会直接控制抽取行为。例如：`phase1_gate_supported_ratio_min` 会影响 grounded claim 的通过下限；`phase1_evidence_lexical_topk` 会影响证据候选的检索宽度；`phase2_conflict_semantic_threshold` 会影响冲突判定的灵敏度；`phase2_gate_conflict_rate_max` 会影响是否允许高冲突结果进入通过态；而 `phase1_chunk_chars_max`、`phase1_claims_per_chunk_max`、`phase1_claim_worker_count` 则直接影响 claim 抽取阶段的粒度与负载。

因此，从技术上说，主工作区的抽取策略是显式配置驱动的，不是硬编码常量驱动的。

### 3.5 抽取策略如何更新：当前实现是“版本化 + 助手建议 + 人在环”的半自动机制

用户特别关心的一个问题是：系统如何自动更新图谱抽取策略。这里需要准确地区分两个层次。主工作区目前已经具备“策略优化辅助”的自动化能力，但它还不是一种完全无监督、自动自改 schema 的机制。更准确地说，它是一个“版本化配置 + 自动建议 + 人在环确认”的半自动更新机制。

这个机制的核心入口是配置中心。配置中心把系统中的可调部分分成 discovery、similarity 和 schema 三个模块。对于 schema，它不仅能列出当前 active schema 中的 rule keys 和 prompt keys，还能根据用户给出的优化目标自动生成调优建议。这里的自动建议有两种来源：一是启发式建议，二是 LLM 生成建议。

启发式建议的行为已经相当明确。如果用户的目标偏向 precision，系统会建议收窄 discovery 批量范围、减小 `rag_top_k`、提高 proposition clustering threshold、提高 `phase1_gate_supported_ratio_min`，并收紧 `phase1_chunk_claim_extract_system` 的提示词约束，以减少无证据支撑的主张。如果目标偏向 recall，系统则会建议增加 gap seed 数量、增加随机探索样本、采用 `hybrid` 社区采样、适度降低 `phase1_gate_supported_ratio_min`，以保留更多候选主张进入下游筛选。如果目标偏向 speed，系统会建议减少 gap seed 和局部邻近样本，并关闭 prompt 优化循环，以换取更低成本和更快延迟。

LLM 模式则进一步把这些建议写成结构化 suggestion，每一条建议都必须落在允许的 anchor 上，例如 `schema.rules_json` 或 `schema.prompts_json` 的某个 focus key。这样做的好处是，系统不会生成漫无边际的“调大一点”“调小一点”式建议，而是总能映射到具体的策略项。

不过需要强调，主工作区目前并不会在没有确认的情况下自动改写 active schema。真正生效的更新，是通过创建新 schema 版本、验证 schema、激活版本，或者保存新的 config profile 来完成的。这种设计体现的是科研系统中的保守策略：允许系统提出优化建议，但避免它在没有审计的情况下悄悄改坏整套抽取策略。

### 3.6 schema preset 的作用：把抽取策略切换成“高精度 / 平衡 / 高召回”

为了让抽取策略不是一堆分散参数的堆叠，主工作区还提供了三个重要的 preset：`high_precision`、`balanced` 和 `high_recall`。这三个 preset 本质上是三种不同的抽取哲学。

`high_precision` 会提高 supported ratio 和 overlap 阈值，缩小 claims per chunk、降低候选上限、收紧 evidence verification，并提高冲突与关键槽位门限。它适合做高置信知识入图、强审计或高信任图层构建。`balanced` 则在 precision 和 recall 之间取得折中，适合作为日常运行配置。`high_recall` 的思路则是允许更多候选主张先进入中间层，再依赖下游质量门禁和人工治理来控制噪声。换句话说，这三个 preset 不是简单地调一个阈值，而是在 chunk 粒度、证据窗口、supported ratio、冲突阈值、coverage gate 与恢复策略等多个维度上共同变化。

对于技术文档而言，真正重要的一点是：**系统已经具备把“抽取策略”当作可切换实验条件的能力**。这为后续的系统评估、A/B 对比、不同领域迁移和专家协作提供了非常关键的基础。

### 3.7 图谱入库之后，检索策略不是单路，而是多路召回 + 结构补强

主工作区中的图谱搜索和问答，并不是只做一次向量检索。它采用的是一种分层、多路召回的检索策略，核心思想是：不同类型的证据适合由不同检索机制召回，最终再在上层做融合。

在问答路径中，系统首先会根据当前环境判断是否启用 pageindex 路径；如果 pageindex 适配器不可用，则自动退回到传统路径。随后，系统并行运行至少两类检索：第一类是 FAISS 向量召回，用于捕捉语义相近的 chunk；第二类是 lexical 检索，用于捕捉高词面重叠或强关键词命中的证据。pageindex 可用时，还会加入第三类结构化页面索引召回。实际运行时，系统会先做 oversample，再对结果做融合与去重，而不是直接相信某一条检索链。

在 lexical 路径中，系统并没有实现复杂的 BM25 全家桶，而是采用一种足够透明、低成本的 BM25-like 词频得分：对 query token 在 chunk 文本中的命中进行计数并累计分值，词面命中越多、重复越高，得分越高。这个策略虽然简单，但在科研场景里有一个重要优点：对于术语、变量名、方法名和具体现象的召回很稳，能为向量检索提供有效互补。

检索完成后，系统不会立刻把 chunk 发给 LLM，而是进一步做结构补强。它会从检索到的 paper sources 中回到图数据库，补充 citation context、structured knowledge（claims + logic steps），以及 fusion evidence。最终提供给问答层的上下文，不是单纯的文本片段集合，而是“文本证据 + 图谱上下文 + 结构化主张 + 可能的教材/融合证据”的联合包。也正因为如此，主工作区的问答更像 evidence-grounded scientific answering，而不是普通聊天。

### 3.8 主工作区中的 discovery：基础版问题发现是如何运行的

主工作区已经包含 discovery 模块，但它更适合被理解为“基于当前知识图谱的基础发现流水线”，而不是最终的自进化系统。其典型运行流程是：先从图谱中检测 gap seed，再针对每个 gap 构造上下文，生成若干候选问题，对候选问题进行证据审计和排序，最后支持人工反馈与状态调整。

这一版 discovery 已经具备几个重要要素：有 gap seed，有候选问题，有 support/challenge evidence，有 quality score 和 ranking，也有人工反馈入口。但它的工作视角仍然是“当前图谱”，并没有把问题置于历史时间点与未来窗口中去检验，也没有形成“修图—再生成—再评估”的闭环。因此，它更像是 worktree 的前置台阶：证明图谱可以支持问题发现，但尚未进入真正的“时间反馈驱动的自进化”。

## 4. Worktree：自进化科学问题系统的实际运行流程

### 4.1 与主工作区相比，worktree 多出来的不是页面，而是时间、反馈和演化

worktree `self-evolving-temporal-discovery` 的本质变化，并不是多了几个接口，而是把“问题发现”从静态任务变成了带反馈的时序任务。在主工作区里，问题是从当前图谱中生成出来的；在 worktree 里，问题是在某个历史时间点上生成的，随后要接受未来窗口中的后验检验，并可能引发图谱修订和后继问题生成。

因此，worktree 的核心对象不再只是 claim、proposition 和 gap，也包括 `TemporalSnapshot`、`ResearchQuestionCandidate`、`StructuredQuestionFrame`、`FutureReward`、`GraphRevisionProposal`、`EpisodeSummary` 和 `lineage`。这些对象共同构成了一个比主工作区更像“研究过程管理器”的系统。

### 4.2 第一步：构建 temporal snapshot，把“当时已知知识”和“未来知识”切开

worktree 的所有流程都从时间快照开始。系统先给定一个 `cutoff year`，然后从图数据库中列出全部文献，按年份划分为两部分：不晚于 cutoff year 的作为 history papers，处于 `[cutoff + future_horizon_min, cutoff + future_horizon_max]` 区间内的作为 future papers。随后系统把这一切打包成 `snapshot_id = snap:<year>` 的时间快照对象，并把 history/future 论文列表以及统计信息写回图中。

这里的实现关键点在于：时间快照不是临时变量，而是图中的持久对象。也就是说，系统不是只在内存里做一次“年份过滤”，而是把这次切片的身份、历史论文集合、未来窗口范围和数量都保存下来，供后面的 episode、reward 和 lineage 使用。这样做的意义在于，后续任何问题、reward 或修订记录都能明确挂接到某个 snapshot，而不是变成脱离历史语境的孤立结果。

### 4.3 第二步：gap detection 不是凭空构造，而是从图谱中的四类信号生成

在历史快照建立后，系统会在当时的图谱上寻找可生成问题的 gap。当前 worktree 的 gap detector 主要从四类信号中取样：第一类是 gap-like claims，也就是明确带有 Gap、FutureWork、Limitation、Critique 等 kind 的 claim；第二类是 gap seeds，即系统预先识别出的知识空白种子；第三类是 conflict hotspot，也就是某个 proposition 周围存在明显 challenge/supersede 冲突事件的区域；第四类是 challenged proposition，即已经处于 challenged 状态的命题。

这些 gap 并不是平等对待的，系统会为它们分配 `priority_score`。例如，gap-like claim 的优先级会考虑 claim confidence、evidence count 以及是否属于 future work / limitation；conflict hotspot 会考虑 conflict events、challenge/supersede 事件数量和涉及论文数；gap seed 则更偏向依赖原始 confidence。换句话说，gap detector 不只是“列出所有空白”，而是在尽量把图谱中的潜在研究机会按科学紧迫性和结构可信度进行排序。

这一步很关键，因为后续候选问题的质量，很大程度上取决于 gap 输入的质量。如果最前面的 gap seed 只是噪声，后面的优化再多也很难救回来。

### 4.4 第三步：图搜索策略是“局部邻域 + 社区扩展 + 随机探索 + 受限 RAG”的混合策略

问题生成之前，系统不会只盯着 gap 本身，而是会为每个 gap 构造一份 hybrid context。这个 hybrid context 的构造方式，是整个 worktree 中最值得关注的图搜索策略之一。

它的第一层是 provenance-driven target selection。系统会优先从 gap 自带的 `source_paper_ids` 取起点；如果没有，则退回到 `source_claim_ids` 或 `source_proposition_ids`，再通过图谱关系反查关联论文。这意味着搜索不是从整个图上盲搜，而是从 gap 的来源位置向外展开。

第二层是图邻域扩展。系统会调用 `sample_inspiration_papers`，按 `hop_order` 在 author-hop 或相关邻域中扩展 adjacent papers；同时根据 `community_method` 从更大的图社区中抽取 community papers；再加上少量 random papers 作为探索项，用来减轻局部图偏置。这种组合的直觉非常清楚：只看邻域会过拟合局部研究团体，只看社区会过度发散，只看随机又会失去上下文，所以三者必须同时存在。

第三层是受限 RAG。系统会先在由上述 paper sources 限定的范围内做 lexical chunk retrieval，只有 scoped retrieval 为空时才回退到更全局的 lexical 片段。这样做的目的，是尽可能让注入的文本片段与当前 gap 所在知识区域保持一致，而不是把无关但词面相似的片段塞进问题生成上下文。

最后，系统把 core papers、citation adjacency、dominant logic steps、evidence motifs 和 rag snippets 合成为 `graph_context_summary + rag_context_snippets`。因此，生成问题时看到的上下文不是“几段文本拼起来”，而是经过图谱局部搜索和结构总结后的混合证据场。

### 4.5 第四步：候选问题生成是“结构化问题对象生成”，不是单句文本生成

worktree 中的 research question candidate 从一开始就被设计成结构化对象。它不仅有问题文本，还包含 motivation、novelty、proposed_method、difference、feasibility、risk_statement、evaluation_metrics、timeline，以及最关键的 `structured_frame`、`trace_id`、`episode_id` 和 `agent_actions`。

其中 `structured_frame` 是系统对科学问题内部结构的显式建模，目前至少包含六个槽位：`phenomenon`、`target_variable`、`mechanism_candidate`、`condition_boundary`、`comparison_anchor` 和 `expected_future_signal`。这六个槽位的意义非常实用。phenomenon 指向研究现象，target_variable 指向关注变量，mechanism_candidate 指向候选机制，condition_boundary 约束适用条件，comparison_anchor 提供对照基准，而 expected_future_signal 则把问题和未来评价窗口连接起来。这样一来，问题就不再是一句孤立的“值得研究的方向”，而是一个带结构、带验证意图、带未来信号接口的对象。

这一步实际上为后面的评分和演化做了最关键的准备。如果问题不是结构化对象，未来 reward 只能依赖粗糙的文本相似性；而当问题有这些槽位后，系统就可以更精细地判断一个问题是否具体、是否有明确机制、是否给出了未来可观测信号。

### 4.6 第五步：生成策略不是单模板，而是模板 + LLM + prompt policy 的混合机制

候选问题生成既支持 template 模式，也支持 LLM 模式。template 模式主要在无外部模型或需要兜底时使用，它会从 gap 描述和缺失证据陈述出发，构造一组带固定结构的候选问题，并直接生成 novelty、feasibility、relevance 和 optimization 分数。LLM 模式则会把 gap、graph context summary 和 rag snippets 一并送入问题生成提示词中，要求模型返回严格 JSON，其中不仅有问题文本，还要返回方法、差异、风险、评价指标、timeline 以及三类基础分值。

更重要的是，LLM 模式并不是单一提示词，而是支持 `base` 和 `optimized` 两类 prompt variant。系统内部维护一个按 `(domain, gap_type)` 分 scope 的 prompt policy。当启用 `rl_bandit` 策略时，它会先做冷启动轮换；冷启动结束后采用 epsilon-greedy 多臂 bandit 选择 prompt variant，其中探索率按 `epsilon = max(0.05, 0.25 * 0.985^N)` 衰减。也就是说，系统在早期会更多尝试不同 prompt 风格，随着试验次数增加，再逐渐偏向历史平均 reward 更高的 variant。

这套机制非常值得强调，因为它意味着问题生成的 prompt 已经不是完全手工固定的，而是进入了在线策略优化状态。

### 4.7 第六步：候选问题在生成阶段就有第一层 optimization score

无论是 template 模式还是 LLM 模式，候选问题在进入证据审计前就会有一层“生成阶段评分”。template 模式下，`optimization_score` 由 novelty、feasibility 和 relevance 的加权和构成，大致形式是 `0.5 * novelty + 0.3 * feasibility + 0.2 * relevance`。LLM 模式则更细一些，它会把模型给出的 novelty、feasibility、relevance、generation_confidence 与上下文重合度一起组合成 model_quality，再把它作为 optimization score。

这一层分值的作用，不是直接决定最终问题好坏，而是先度量“从生成器视角看，这个候选是否看起来值得继续保留”。换句话说，optimization score 更像生成器内部的先验质量估计，而不是终局判定。

### 4.8 第七步：evidence audit 才是候选问题真正进入排名前的第一道硬审计

候选问题生成完成后，会进入 evidence auditor。这个模块的任务是把“看起来不错的问题”转化为“有真实支持证据的问题”。它的做法有三层：首先复用上游 gap 的 provenance，把 source claim / proposition 转换成基础 support evidence；其次对问题文本做 chunk-level lexical evidence retrieval，在相关 paper source 范围内补充新的支撑证据和 rag snippets；再次，从 proposition 事件中补充 challenge evidence，用来判断问题不是只被单边支持，而是是否面对真实争议或边界条件。

在此基础上，系统计算 `support_coverage`、`challenge_coverage`、`novelty`、`feasibility` 和 `relevance`，再用一个明确的加权公式形成 `quality_score`：

`quality_score = 0.45 * support_coverage + 0.15 * challenge_coverage + 0.20 * novelty + 0.10 * feasibility + 0.10 * relevance`

如果 support evidence 不足，系统还会再乘以一个惩罚系数，并把状态降为 `needs_more_evidence`。也就是说，这一层评分把“生成质量”和“证据质量”明确分离开了：一个问题可以写得很像样，但如果没有至少足够的 support/challenge evidence，它仍然不会进入高质量候选层。

### 4.9 第八步：ranker 的目标不是只看一个分数，而是做科学实用性排序

evidence audit 完成后，候选问题才会进入 ranker。ranker 的排序并不是单一 `quality_score` 降序，而是一个多键排序：先按状态优先级，再按 quality_score、optimization_score、support_coverage、novelty_score、relevance_score 组合排序。也就是说，系统明确认为“状态是否可接受”比“数值分高一点点”更重要；而在同一状态下，证据充分度和科学效用信号再决定先后顺序。

这种排序策略其实非常符合科研直觉。一个高 novelty 但证据严重不足的问题，不应排在一个证据更充分、可检验性更高的问题前面。系统把这一点直接体现在排序逻辑中，而不是把所有质量维度都压缩成一个不可解释的黑箱总分。

### 4.10 第九步：future-window reward 负责评估“这个问题是否后来被历史部分验证”

worktree 的真正特色，是在候选问题进入时间维度后，还要再经历一次基于未来窗口的后验评分。系统会先根据 future papers 构造 `future_graph_delta`，把未来论文中的 logic steps 视作 emergent edges，把未来 claims 视作 new propositions。然后，它会把候选问题的 question 文本与 structured_frame 拼成统一 token 表示，再分别与 future graph delta 和 future papers 做重叠比较。

当前 reward 由六个部分组成：

- `graph_emergence_score`：问题与 future emergent edges / propositions 的重合程度；
- `paper_coverage_score`：问题与 future paper title / abstract / summary 的重合程度；
- `novelty_score`：问题与当前 graph_context_summary 的差异程度；
- `specificity_score`：structured frame 中被填充槽位的比例；
- `answerability_score`：问题是否有图谱摘要或 source papers 支撑；
- `dual_evidence_score`：是否同时命中 future graph 和 future papers 两种证据。

最终 reward 使用如下加权组合：

`total_reward = 0.35 * graph_emergence + 0.20 * paper_coverage + 0.15 * novelty + 0.10 * specificity + 0.10 * answerability + 0.10 * dual_evidence`

这里最值得注意的是，系统并没有把 future reward 设计成“只看文本相似度”，而是明确区分了图结构增量和未来文献文本增量，并且把双证据同时命中视为额外奖励。这说明它追求的不是“未来出现了类似词”，而是“未来既在文献文本上、也在图结构上朝着这个问题指向的方向演进”。

### 4.11 第十步：反馈更新不是只改分数，而是同时更新 candidate、revision 和 prompt policy

worktree 中的反馈分为两类：一类是人工反馈，一类是未来奖励反馈。

人工反馈通过 `accepted / rejected / needs_revision` 这类标签作用于候选问题。系统会把反馈记录存成 `FeedbackRecord`，同时更新候选问题的 `quality_score` 和 `status`。当前实现里，accepted 会带来正向增量，rejected 会带来明显负向增量，needs_revision 则是轻微负反馈。更关键的是，如果该候选带有 `prompt_variant` 元数据，人工反馈还会被映射成 prompt policy reward：accepted -> 1.0，rejected -> 0.0，其余中间态 -> 0.35。这样一来，人的判断不只是改了某个候选的状态，也会反过来改变未来 prompt variant 的选择偏好。

未来奖励反馈则更复杂。系统会把 `total_reward` 回写到研究问题对象上，形成 future reward 节点或相关属性，同时把 reward 传播到相关 revision proposal 上，形成 revision reward。也就是说，未来窗口反馈不仅告诉系统“这个问题表现如何”，还告诉系统“围绕它做过的哪些修图动作是有收益的”。这为真正的结构更新提供了依据。

### 4.12 第十一步：prompt policy 的在线更新是当前系统里最接近“自动学习”的部分

在 worktree 中，当前最明确的在线学习机制其实不是 extraction schema 自动重写，而是 prompt policy 的 bandit 更新。每个 `(domain, gap_type)` scope 下的每个 prompt variant 都维护了试验次数 `n`、平均 value、累计 reward 和最后来源。系统既会用批处理候选的综合表现更新它，也会用人工反馈继续更新它。

批处理更新时，系统先根据候选的 `quality_score`、`optimization_score`、`support_coverage` 和状态标签算一个 candidate reward，大致形式是：

`reward = 0.55 * quality + 0.20 * optimization + 0.15 * support + 0.10 * status_bonus`

其中 status_bonus 会区分 accepted、ranked、needs_more_evidence 和 rejected。然后这个 reward 会通过增量均值公式更新对应 variant 的 value。人工反馈到来时，同样会映射成 reward 并更新同一个 scope 下的 arm。由此，系统生成科学问题所使用的 prompt 选择，不再是固定设置，而会随着 batch 结果和人工反馈逐渐发生偏移。

如果说当前系统里哪一部分已经表现出“在线适应”的味道，这就是最典型的一部分。

### 4.13 第十二步：revision 不是改措辞，而是改图谱中的科学表达单元

当某个候选问题在未来窗口中的表现不足时，系统不会立刻只重写问题文本，而是尝试生成 graph revision proposal。当前 revision 主要作用在两类对象上：`claim` 和 `logic_step`。系统会为每条修订建议生成 `proposal_id`，并同步生成 `decision_id`，将 proposal 和 decision 都写入图中。这意味着修订不是临时动作，而是正式的可追踪图谱事件。

修订的评价方式也很直接：如果某次修订让同一条问题 lineage 上的 future reward 提高了，那么 `revision_gain = after_score - before_score` 为正，系统就把这个 gain 作为 revision reward 记录下来。换句话说，revision 的好坏不是由人工想象决定，而是由它是否真的提高了该问题在未来窗口上的表现来判定。

### 4.14 第十三步：autonomous cycle 让系统开始从“会评价”走向“会演化”

autonomous revision cycle 是整个 worktree 最接近“真正自进化”的部分。它的运行流程大致如下：系统先读取某个候选问题的 lineage，并确定其对应的 cutoff year；然后加载相应 future window 的上下文；如果未来窗口没有未来论文，则直接跳过；若存在未来论文，则先计算 parent candidate 的当前 future reward；再根据该候选的 structured frame、gap 描述和 future graph delta，提炼 logic summary seed 与 claim text seed，据此生成一小组 revision proposal。

之后，系统会先构造一个 evolved candidate 的草稿版本，并对这个草稿版本重新计算 future reward。如果 `after_reward - before_reward <= 0`，说明本轮修订没有带来收益，系统不会写回图谱；如果 gain 为正，系统才真正执行 `_apply_revision_proposal`，把修订写回图中，再把 evolved candidate 作为 successor question 写入 discovery graph，并建立 `EVOLVES_FROM`、`GENERATED_BY_REVISION` 等 lineage 关系。

这里最值得强调的是 reward gate 的存在。系统不是“有修订就落图”，而是“只有修订后问题在 future reward 上更好，才允许图谱状态真正演化”。这使得自进化过程具有明确的方向性，而不是任意漂移。

### 4.15 第十四步：episode 和 lineage 让系统记住自己如何变好

在 worktree 中，每个 cutoff year 的未来窗口评估都会形成一个 episode，而每个问题的前后演化关系会形成 lineage。系统会保留 snapshot、episode、候选问题、future reward、revision proposal、revision decision 和 successor question 之间的连接关系。这意味着，系统并不是只存“当前最好问题”，而是存下整条研究问题的演化轨迹。

这种做法的技术意义非常大。没有 episode，系统只能做单次打分；没有 lineage，系统无法学习“哪种修订路径更有效”。有了二者之后，系统开始拥有可回放的经验记录：可以回看某条问题是如何从原始 gap 出发，经由哪些修订，最终变成一个 reward 更高的 successor。这种记忆结构正是后续更强策略学习、meta-analysis 和实验研究的基础。

## 5. “抽取策略更新”和“问题生成策略更新”在项目中是两类不同机制

为了避免概念混淆，有必要专门说明：项目里实际上存在两套不同的策略更新机制。

第一套是主工作区的抽取策略更新机制。它基于 schema 版本、preset、config profile 和 assistant suggestion，本质上是“半自动、可审计、人在环”的。系统会自动提出如何改阈值、改 prompt、改聚类配置的建议，但最终生效要通过版本切换或 profile 保存完成。这一套机制偏向“科研知识底座的稳定治理”。

第二套是 worktree 的问题生成策略更新机制。它基于 prompt bandit、candidate reward、human feedback 和 future reward，更接近“在线适应”。系统会自动根据 batch 表现和人工反馈更新 prompt variant 的估值，并在下一轮 generation 时改变 variant 选择偏好。这一套机制偏向“发现引擎的持续优化”。

前者解决的是“如何稳定地抽出更好、更可信的图谱”；后者解决的是“如何在已有图谱上逐渐学会提出更好的问题”。这两个机制互相依赖，但不能混为一谈。

## 6. 把主工作区和 worktree 串起来看：完整运行链是什么

如果把两个工作区连起来，系统的完整运行链其实是非常清晰的。主工作区先把论文导入系统，形成统一文档对象；然后通过分阶段抽取、grounding、冲突门控和质量分层，把文献中的 claim、logic step、citation 与结构化知识沉淀到图谱和索引中；接着再通过图谱浏览、RAG 问答、配置中心和基础 discovery 让研究者和系统都能使用这些知识。

在此基础上，worktree 从主图谱中选择某个历史时间点，构造 temporal snapshot；从该 snapshot 上的 claims、propositions 和 conflict hotspot 中生成 gap；围绕每个 gap 通过 author-hop、community 和 random exploration 构造 hybrid context；生成结构化 research question candidate；通过 evidence audit 和 ranking 初步筛选候选；再使用 future window 构造图结构增量与未来论文增量，对问题进行后验 reward 评价；最后在必要时生成 revision proposal，比较修订前后收益，并将真正带来增益的修订写回图谱，形成 successor question 和 lineage。

这条链路说明项目已经不再是“一个知识图谱平台”或者“一个问题生成器”这样单层次的系统，而是在逐渐变成一个“以知识图谱为底座、以时间反馈为评估、以结构修订为驱动的科研发现系统”。

## 7. 当前阶段的能力边界

尽管 worktree 已经形成了一个真实的自进化闭环，但仍然需要准确描述它的当前边界。第一，时间反馈目前仍然主要是 retrospective 的，也就是历史回放式的未来验证，而不是面向真实未知未来的强预测。第二，抽取策略更新在主工作区中仍以半自动、人机协同为主，不是无监督自改 schema。第三，问题生成的在线适应目前主要体现在 prompt policy 和 revision reward 上，还没有形成更强的策略学习器。第四，revision 目前聚焦于 claim 和 logic step 层面的科学表达修订，而不是全领域 ontology 的大规模自动重构。

不过这些边界并不削弱系统当前的技术价值。相反，它们清楚地表明项目已经越过了最难的第一道门槛：把“图谱抽取”“问题生成”“未来评估”“反馈更新”和“结构修订”放进同一个可以运行、可以落库、可以回放的系统里。这正是项目与一般科研辅助工具真正不同的地方。

## 8. 结语

从技术文档的角度来看，`LogicKG` 的关键不是某一个模型、某一条 API 或某一个页面，而是它形成了一条明确的系统运行逻辑。主工作区负责把科研文本变成高质量、可治理的结构化知识层；worktree 负责在这个知识层上构建时间切片、生成结构化科学问题、用未来窗口做后验评价，再通过修图和 successor question 让系统逐步改进自己的问题提出能力。

如果用最凝练的方式描述这个项目，可以说它在尝试建立这样一种机制：**让知识图谱不再只是存储已有知识，而是成为一个可以支持历史回放、问题提出、反馈更新和结构自我修订的科研运行环境。** 这也是为什么这个项目不能被简单看成“图谱 + RAG”或“图谱 + LLM question generation”。它真正做的是把知识底座、证据检索、质量门控、时间反馈和自进化逻辑组织成一条可持续运行的科研系统链。
