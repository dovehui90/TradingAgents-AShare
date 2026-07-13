# 代码开发与交付规范（强制执行）

## 1. 需求明确
- 需求写清楚：做什么、怎么做算完成
- 未明确的需求先讨论确认，不动手写代码

## 2. 代码开发
- 从 `main` 拉新分支开发，禁止在 `main` 上直接改
- 小步提交，每个 commit 只做一件事
- 遵循项目 Skill 流程：修bug/新功能/提交代码 各有对应步骤

## 3. 本地自动化检查
- 本地运行 lint、类型检查、测试，全部通过才能进入下一步
- 不依赖 GitHub，确保提交前的代码质量

## 4. 本地部署验证
- Claude 拉分支代码到本地环境，跑完整功能验证
- Claude 验证通过后，交给用户在本地测试

## 5. ⚠️ 用户确认（强制关卡）
- **用户确认没问题后，才能进入后续步骤**
- 确认后：commit → push GitHub → PR → Staging → 生产部署
- 发现问题 → 回第2步修复

## 6. 提交备份 + 代码评审
- 代码 push 到 GitHub（备份 + 触发 GitHub CI）
- 提交 PR，审查代码变更，评审通过后合并到 `main`

## 7. 预发布环境（Staging）
- 合并后的代码部署到 staging 环境
- 跑自动化回归测试 + 手动冒烟测试
- Staging 与生产环境配置一致

## 8. 生产部署
- 旧进程先强制停干净并验证端口释放，新进程再启动
- 部署完成后验证服务可用

## 9. 监控 + 回滚
- 部署后观察日志、错误率、服务指标
- 出问题立即回滚到上一个稳定版本

---

**核心规则：上一步未完成，不得进入下一步。第5步（用户确认）为强制关卡——代码在本地验证通过、用户点头之前，禁止 push GitHub、禁止部署。**

---

# 任务执行流程（每次代码任务必须执行）

**收到代码任务后，按对应场景顺序执行，不得跳过任何步骤：**

| 场景 | 步骤1 | 步骤2 | 步骤3 | 步骤4 |
|------|-------|-------|-------|-------|
| 修bug | Skill(systematic-debugging) | Skill(test-driven-development) | 写修复代码 | Skill(verification-before-completion) |
| 新功能 | Skill(brainstorming) | Skill(test-driven-development) | 写实现代码 | Skill(verification-before-completion) |
| 提交代码 | Skill(chinese-code-review) | Skill(chinese-commit-conventions) | git commit | — |

**规则：上一步 Skill 未执行完毕，不得进入下一步。**

---

<!-- superpowers-zh:begin (do not edit between these markers) -->
# Superpowers-ZH 中文增强版

本项目已安装 superpowers-zh 技能框架（20 个 skills）。

## 核心规则

1. **收到任务时，先检查是否有匹配的 skill** — 哪怕只有 1% 的可能性也要检查
2. **设计先于编码** — 收到功能需求时，先用 brainstorming skill 做需求分析
3. **测试先于实现** — 写代码前先写测试（TDD）
4. **验证先于完成** — 声称完成前必须运行验证命令

## 可用 Skills

Skills 位于 `.claude/skills/` 目录，完整清单及描述见系统注入的可用技能列表，此处不赘述。

## 如何使用

当任务匹配某个 skill 时，使用 `Skill` 工具加载对应 skill 并严格遵循其流程。绝不要用 Read 工具读取 SKILL.md 文件。

如果你认为哪怕只有 1% 的可能性某个 skill 适用于你正在做的事情，你必须调用该 skill 检查。
<!-- superpowers-zh:end -->
