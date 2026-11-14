# 初中数学知识体系数据包（cf73951）

来源：[https://github.com/xiaoyang111222/cn-math-taxonomy](https://github.com/xiaoyang111222/cn-math-taxonomy)，固定提交 `cf73951`。

许可证：**CC BY-NC 4.0**（署名—非商业性使用 4.0 国际）。
商业用途需另行获得原作者授权。许可证全文见同目录 `LICENSE`。

## 内容

| 文件 | 说明 |
|---|---|
| `data/topics.json` | 315 个初中数学知识点 |
| `data/dependencies.json` | 563 条初中内部先修关系 |
| `data/cn-curriculum-standards.json` | 157 条课程标准 |
| `data/topic-standards.json` | 383 条知识点—课程标准映射 |
| `data/id-aliases.json` | 外部 ID 别名 |
| `manifest.json` | 来源、计数、校验值与修改说明 |

## 未包含

- 45 条小学→初中先修关系（本阶段不导入）
- 外部配套题目
- 小学、高中及其他学科数据

## 修改说明

本数据包由 `backend/scripts/build_junior_taxonomy_package.py` 从上游数据过滤生成，
仅保留初中数学范围；未修改任何知识点、关系或课标的内容与含义。

## 重新生成

```bash
cd backend
python scripts/build_junior_taxonomy_package.py \
  --source-dir /path/to/cn-math-taxonomy \
  --out ../data/cn-math-taxonomy/cf73951 \
  --commit cf73951
```
