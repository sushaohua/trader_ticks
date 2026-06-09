# DevOps_Engineer 技能定义

## 🛠️ 允许运行的命令 (Allowed Commands)
- `docker build -t ...` [auto_approve=true]
- `docker-compose up -d` [auto_approve=true]

## 🚫 高危拦截与安全限制 (High-Risk Interception)
- 涉及类似 `rm -rf` 或未经审计的生产环境 `push` 操作，必须降级为交互模式，弹窗等待用户 Submit。
