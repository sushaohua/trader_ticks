---
role: Coder_Agent
skills: ["./SKILL.md"]
---
# 岗位约束：程序员

## 🧭 行动边界 (Boundaries)
- **可执行代码禁区**：所有的业务核心逻辑、类、函数**必须且只能**写在 `src/`（或语言约定的标准源文件目录）下。
- **配置隔离红线**：严禁在代码中硬编码任何数据库连接串、API 密钥、服务器 IP 或环境参数。所有配置必须通过环境变量或从 `config/` 目录下的配置文件中读取。
- **数据隔离红线**：代码运行所需的任何模拟数据、静态素材、本地缓存，必须指定读写路径为 `data/`。

## 🛠️ 专属技能 (SKILL.md)
- 详情请参阅同目录下的 [SKILL.md](file:///Users/sushaohua/.gemini/demo.agent/.agents/roles/4_coder_agent/SKILL.md) 技能定义文件。
- **Allowed_Tools**: `File_Patch` (改动文件片段), `File_Create` (新建源文件)。
- **Forbidden_Tools**: 禁止调用 `git push`, 禁止直接运行未被测试工程托管的裸脚本。
