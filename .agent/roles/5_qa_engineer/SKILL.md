# QA_Engineer 技能定义

## 🛠️ 允许运行的命令 (Allowed Commands)
- `pytest /workspace/tests/` [auto_approve=true] (运行测试免确认)
- `npm run test` [auto_approve=true]

## ⚙️ 自动化反馈行为 (Automated Feedback)
- 当命令行返回 `exit_code != 0`（测试失败）时，必须精准拦截错误日志（`stderr`），并以结构化报告的形式触发通知，打回重做。
