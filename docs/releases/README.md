# LogicKG Release Notes

本目录包含 LogicKG 项目的版本发布说明,按时间倒序排列。

## 版本列表

### 2026-02-20: Round 8 Evidence Quote + P0.3 Gate Optimization
- **文档**: [2026-02-20-round8-evidence-quote-and-p03-gate.md](./2026-02-20-round8-evidence-quote-and-p03-gate.md)
- **分支**:
  - Round 8: `feature/crossref-batch-resolve`
  - P0.3: `feature/gate-bypass-step-coverage`
- **Schema**: v8
- **核心改进**:
  - Evidence Quote 架构: Span 定位准确率从 59.8% 提升至 100%
  - 质量门禁优化: 适配软件/理论类论文,通过率从 70% 提升至 90%
- **影响范围**: Claim 抽取质量、质量门禁逻辑

---

## 如何阅读发布说明

每个发布说明包含以下章节:

1. **Executive Summary**: 快速了解核心改进和业务价值
2. **背景与问题定义**: 理解为什么需要这些改进
3. **特性详解**: 深入了解设计方案、实现细节和测试结果
4. **验证与复现**: 如何复现测试结果
5. **风险与后续计划**: 已知风险和未来规划
6. **附录**: 配置参数、代码位置、术语表等参考信息

## 版本命名规范

- 文件名格式: `YYYY-MM-DD-feature-name.md`
- 标题格式: `LogicKG Release Notes — Feature Name`
- 日期使用发布日期,不使用开发日期

## 贡献指南

添加新的发布说明时:

1. 在 `docs/releases/` 目录创建新的 Markdown 文件
2. 使用统一的文档模板(参考最新的发布说明)
3. 更新本 README.md,在版本列表顶部添加新版本
4. 确保包含测试结果和复现步骤
5. 标注影响范围和风险
