import { describe, it, expect } from 'vitest'
import { describeParseWarnings } from '@/lib/importWarnings'

describe('describeParseWarnings', () => {
    it('把缺图与候选告警翻成可读文本', () => {
        const out = describeParseWarnings([
            'image_missing_for_figure_question:10',
            'image_candidate_for_question:20:images/page_5_image_21.jpg',
        ])
        expect(out).toEqual([
            '第 10 题题干提到“如图”，但未匹配到图片（原图可能过小或被压缩）',
            '第 20 题在答案/解析区发现候选图片，需人工核对',
        ])
    })

    it('翻译未解决原因与退化图', () => {
        const out = describeParseWarnings([
            'image_unresolved:answer_region:6',
            'image_unresolved:degenerate_image:2',
            'manual_review:image_anchoring',
        ])
        expect(out).toEqual([
            '有 6 张图片未能确认归属（位于答案区）',
            '有 2 张图片未能确认归属（图片过小或接近二维码/色块）',
            '图片归属需人工复核',
        ])
    })

    it('知识点检索不可用有明确文案', () => {
        expect(describeParseWarnings(['knowledge_points_unavailable'])).toEqual([
            '知识点检索服务暂不可用，本次未做知识点匹配（可稍后重新导入或检查 Embedding 配置）',
        ])
    })

    it('未知告警原样透出、重复提示去重、非数组输入返回空', () => {
        expect(describeParseWarnings(['something_new:1', 'something_new:1'])).toEqual([
            'something_new:1',
        ])
        expect(describeParseWarnings(undefined)).toEqual([])
        expect(describeParseWarnings('x')).toEqual([])
    })
})
