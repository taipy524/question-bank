/**
 * 把后端 `parse_meta.warnings` 的机器码翻译成审核页可读提示。
 *
 * 约定:
 * - 不隐藏任何未知告警(原样透出),避免"看不懂就丢掉"。
 * - 同一句提示只出现一次。
 * - 这里只做展示,不改变任何图片归属或导入行为。
 */

const UNRESOLVED_REASONS: Record<string, string> = {
    answer_region: '位于答案区',
    no_figure_reference: '题干没有“如图”等图片引用',
    outside_question: '不在任何题目范围内',
    after_answer_marker: '位于答案/解析标记之后',
    degenerate_image: '图片过小或接近二维码/色块',
}

function describeOne(code: string): string | null {
    if (code === 'knowledge_points_unavailable') {
        return '知识点检索服务暂不可用，本次未做知识点匹配（可稍后重新导入或检查 Embedding 配置）'
    }
    const [head, ...rest] = code.split(':')
    if (head === 'image_missing_for_figure_question') {
        return `第 ${rest[0]} 题题干提到“如图”，但未匹配到图片（原图可能过小或被压缩）`
    }
    if (head === 'image_candidate_for_question') {
        return `第 ${rest[0]} 题在答案/解析区发现候选图片，需人工核对`
    }
    if (head === 'image_unresolved') {
        const reason = UNRESOLVED_REASONS[rest[0]] ?? rest[0]
        return `有 ${rest[1]} 张图片未能确认归属（${reason}）`
    }
    if (head === 'image_missing_media') {
        return `有 ${rest[0]} 张图片引用找不到对应文件`
    }
    if (head === 'image_deduped') {
        return `有 ${rest[0]} 张重复图片已复用同一文件（引用均保留）`
    }
    if (head === 'image_placeholder_unused') {
        return `AI 未使用 ${rest[0]} 张已锚定的图片`
    }
    if (head === 'image_placeholder_overflow') {
        return `AI 多引用了 ${rest[0]} 个图片占位符，已自动清理`
    }
    if (head === 'image_anchoring_skipped') {
        return '未识别到题号结构，已跳过图片锚定（图片原样保留）'
    }
    if (code === 'manual_review:image_anchoring') {
        return '图片归属需人工复核'
    }
    return null
}

export function describeParseWarnings(warnings: unknown): string[] {
    if (!Array.isArray(warnings)) return []
    const seen = new Set<string>()
    const out: string[] = []
    for (const raw of warnings) {
        const code = String(raw ?? '').trim()
        if (!code) continue
        const text = describeOne(code) ?? code
        if (seen.has(text)) continue
        seen.add(text)
        out.push(text)
    }
    return out
}
