# taxonomy_import_prototype

独立、只读、默认 dry-run 的知识体系导入原型，用于第一阶段
（QuestionBank 内部 62 个初三数学知识点 × `cn-math-taxonomy` 315 个初中数学知识点）。

## 安全边界

- 纯标准库（`json/csv/hashlib/unicodedata/difflib/argparse/pathlib`）。
- **不** import FastAPI 业务代码、SQLAlchemy 模型或写入服务。
- **不** 连接 MySQL、ChromaDB、AI Provider；不发起网络请求。
- 所有输入通过命令行参数指定；所有输出只能写到 `--out-dir`。
- `preview_import.py` 为 dry-run：`database_writes = 0`，不创建/更新任何数据。

## 输入

外部数据（仓库外，固定 commit `cf73951cf4b5d2bdbc8a75bb9cb9e961e55277ab`）：

```
/workspace/.opencode/tmp/cn-math-taxonomy-cf73951/
  data/topics.json
  data/dependencies.json
  data/cn-curriculum-standards.json
  data/id-aliases.json
  docs/standards-mapping.md
  scripts/validate.py
  CHANGELOG.md
  LICENSE
```

默认可用环境变量覆盖：`CNM_SOURCE_DIR`。

内部快照：默认解析只读导出
`/workspace/.opencode/tmp/finalize-20261025_235534/mysql.sql`
（62 行、导出时间 2026-10-25 15:55:35）。可用 `QB_INTERNAL_DUMP` 覆盖。
不会启动或连接 MySQL。

未来数据库可用时，可用以下**只读** SQL 生成 `--rows-json` 输入：

```sql
SELECT kp.id AS internal_id, kp.name, kp.slug, kp.subject_id,
       s.name AS subject_name, kp.parent_id
FROM knowledge_points kp
JOIN subjects s ON s.id = kp.subject_id
ORDER BY kp.id;
```

## 使用

```bash
cd /workspace/repos/question-bank-taipy

python3 tools/taxonomy_import_prototype/inspect_source.py
python3 tools/taxonomy_import_prototype/validate_source.py
python3 tools/taxonomy_import_prototype/export_internal.py
python3 tools/taxonomy_import_prototype/build_mapping.py
python3 tools/taxonomy_import_prototype/validate_mapping.py
python3 tools/taxonomy_import_prototype/preview_import.py

# 生成最终交付物到仓库根 reports/
for step in inspect_source validate_source export_internal \
            build_mapping validate_mapping preview_import; do
  python3 "tools/taxonomy_import_prototype/$step.py" --out-dir reports
done
```

脚本按顺序运行；`build_mapping` 需要 `internal_snapshot.json`，
`validate_mapping` / `preview_import` 需要前序输出。

## 映射规则

- `exact`：规范化名称完全相同（NFKC、去空白/标点、统一括号）。
  路径或 domain 冲突仍保留，但标记 `conflict=true`。
- `semantic`：同一 domain 族，且字符 bigram Jaccard ≥ 0.6。
  仅字面接近、单字差异的语义候选会标记 `risk=single_char_difference`。
- 基数统计基于**去重后的候选关系图**：1-1 / 1-N / N-1 / N-M，
  每个连通分量只计一次，避免重复计数。
- 所有结果 `review_status=pending_review`；无规则依据时 `confidence=null`。
- 未做 AI 语义判断，`new_topic` 只表示“没有确定性候选”，不表示一定需要新增。

## 测试

```bash
python3 -m unittest discover -s tools/taxonomy_import_prototype/tests -v
```

测试使用合成内部快照；外部真实数据计数测试读取 `CNM_SOURCE_DIR`（默认见上）。
源文件与内部快照在测试前后做 SHA256 校验，确保不被修改。
