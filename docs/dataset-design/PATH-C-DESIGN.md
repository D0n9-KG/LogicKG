# Path C 设计文档（骨架，待展开）

## 一句话定位
自进化元超图 schema（meta-hyperedge pattern，pattern split 的拓扑对象）
+ 实例层 hyper-relational（qualifier 挂条件/方法/证据，受控扩展治发散）
+ 种子骨架固定顶层维度 + 有界操作 + Constitutional 护栏。

## novelty 锚点（四真空，已查证）
1. schema 超图 + pattern split（DIAL-KG/AgentCAT/LOGOS 三邻居都不做）
2. 实例 hyper-relational qualifier（补 MeasEval 条件真空）
3. 分层混合（HEHRGNN 熔合、TRACE-KG taxonomy，都不分层）
4. 种子骨架+有界操作+Constitutional（四角拼中心）

## 结构（两层）
- schema 层：MetaHypergraph（现有），meta-hyperedge=pattern，保 split 对象
- 实例层：Hyperedge 带 qualifier（condition/method/evidence_strength/cited_from），受控扩展

## 收敛设计（借三邻居）
- AdaKGC 固定顶层维度（内容/结构/方法/证据 等 major classes）
- HyDRA 单根类约束
- AgentCAT conservative policy 叠加 split

## 有界操作集
add / split / merge / rename（无 free-form 新建维度）

## 待展开（下一步分小步写）
- [ ] 种子骨架具体维度清单
- [ ] qualifier 受控词表（condition/method/evidence 各枚举值）
- [ ] split/merge 触发判据（确定性）
- [ ] Constitutional 护栏具体规则
- [ ] 增益实验设计（分层混合 vs 熔合/taxonomy）
- [ ] 与现有代码的衔接改动清单
