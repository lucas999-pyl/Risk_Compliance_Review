# 化工合规 RAG 工具便携包启动说明

## 适用场景

这份说明用于把项目复制到另一台 Windows 电脑后，在本机 `8080` 端口启动演示服务。

便携包会包含打包时项目根目录的 `.env`，用于在其他电脑继续连接阿里云百炼 embedding/LLM。请只在受信任电脑或受控演示环境中分发该包，不要公开外发。

如果便携包中没有 `.env`，首次启动会自动创建离线演示配置，使用本地 hash embedding 和规则解释降级模式。

## 环境要求

- Windows 10/11
- Python 3.11 或更高版本
- 能访问 Python/pip 安装依赖的网络环境

## 启动步骤

1. 解压便携包。
2. 双击根目录的 `start-8080.bat`。
3. 等待依赖安装和服务启动。
4. 浏览器打开：

```text
http://127.0.0.1:8080/
```

首次启动会自动生成：

- `.venv/`：本地 Python 虚拟环境
- `.env`：如果包内已包含则直接使用；如果缺失则生成离线演示配置
- `data/risk-review.db`：本地 SQLite 数据库
- `data/objects/`：上传对象目录
- `data/vector_store/chemical_rag/vectors.sqlite3`：本地向量索引

## 演示流程

1. 打开首页。
2. 在左侧选择 `data_samples/chemical_knowledge_sources/official_pack_2026_05/manifest.json`。
3. 选择同目录下 5 份 `.md` 官方/内部源文档。
4. 点击“上传官方知识库源文档”。
5. 点击“查看已上传 Chunk”，确认来源、版本、Chunk 和向量状态。
6. 选择供应商资料包，或手动上传 SDS、配方表、工艺说明。
7. 填写或选择审查任务。
8. 点击“上传并运行审查”。
9. 查看三值判定、资料完整性、风险项、证据链、技术细节和流程回放。

## 阿里云百炼配置

便携包默认使用打包时携带的 `.env`。如果需要替换 Key 或切换账号，把 `.env` 改成：

```env
OPENAI_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENAI_API_KEY=你的百炼Key
RCR_ENABLE_LLM=true
CHEM_RAG_EMBEDDING_PROVIDER=qwen
CHEM_RAG_EMBEDDING_MODEL=text-embedding-v4
CHEM_RAG_LLM_PROVIDER=qwen
CHEM_RAG_LLM_MODEL=qwen3.6-plus
```

重启 `start-8080.bat` 即可。

## 常见问题

- 端口占用：如果 `8080` 被占用，可运行：

```powershell
powershell -ExecutionPolicy Bypass -NoProfile -File scripts/start-portable-8080.ps1 -Port 8081
```

- 依赖安装失败：确认 Python 版本和 pip 网络可用。
- 页面还是旧版：关闭旧命令窗口，重新双击 `start-8080.bat`，并在浏览器强制刷新。
- 知识库显示 0：这是正常初始状态，需要先手动上传 manifest 和源文档。
