# 演示资料导览

> 这是「找资料用」的中文索引副本（从 `data_samples/` 复制而来）。
> **测试和后端代码仍然走原英文路径**，本目录改名/挪动不影响业务。
> 如果要更新内容，请改 `data_samples/` 原件，再 `cp` 过来同步。

---

## 01_客户上传演示_三套场景/

模拟客户在 Wizard Step 2 上传资料包的三种典型场景。每套含 3 份文档（SDS + 配方表 + 工艺说明）。

| 子目录 | 用途 | 预期判定 |
|---|---|---|
| `A合规通过_水基清洁剂/` | 走通顺路径，全部合规 | ✅ pass |
| `B不相容阻断_氧化剂加易燃/` | 触发"不相容物料"红线 | ⛔ not_approved |
| `C资料不全_缺工艺说明/` | 工艺说明有缺项 | ⚠️ needs_supplement |

---

## 02_知识库演示包_官方法规/

知识库的 5 份法规摘要（管理端「导入演示包」按钮加载的就是这套）。

| 子目录 | 来源 | 用途 |
|---|---|---|
| `01_OSHA_美国_SDS与附录D/` | 美国 OSHA HCS 2024 | SDS 完整性核查 |
| `02_ECHA_欧盟_SVHC候选清单/` | 欧盟 ECHA | 受限物质筛查 |
| `03_EPA_美国_TSCA清单/` | 美国 EPA | 清单准入 |
| `04_中国_危化品目录2015版/` | 中国应急部 | 危化品识别 |
| `05_内部不相容红线规则/` | 内部规则 | 物料不相容判定 |
| `_manifest_清单.json` | — | 知识包清单（filename / title / jurisdiction / source_url 等元数据） |

---

## 03_单文件SDS兜底样本/

老 UI 「单文件兜底」演示用的 SDS（管理端调试时用）。

---

## 04_评测黄金集/

`/chemical/evaluation` 跑评测用的数据集。

- `01_供应商资料样本/` — 6 份不同复杂度的 SDS（完整/不全/无 CAS/未知物等）
- `02_知识包/` — 评测专用的法规演示包 JSON
- `_manifest_清单.json` — 黄金集清单
- `_README_黄金集说明.md` — 原 README（保留英文）

---

## 路径对照（如需找到代码里硬绑的原路径）

| 中文目录 | 原英文路径 |
|---|---|
| `01_客户上传演示_三套场景/` | `data_samples/chemical_rag_dataset/upload_samples/` |
| `02_知识库演示包_官方法规/` | `data_samples/chemical_knowledge_sources/official_pack_2026_05/` |
| `03_单文件SDS兜底样本/` | `data_samples/demo-sds.txt` |
| `04_评测黄金集/` | `data_samples/golden_dataset/` |
