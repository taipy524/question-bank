export type TaxonomyMatchType =
  | 'exact'
  | 'semantic'
  | 'one_to_many'
  | 'many_to_one'
  | 'many_to_many'
  | 'new_topic'

export type TaxonomyReviewStatus =
  | 'pending_review'
  | 'confirmed'
  | 'rejected'
  | 'needs_split'
  | 'needs_merge'
  | 'new_topic_pending'

export const TAXONOMY_STATUS_LABELS: Record<string, string> = {
  pending_review: '待审核',
  confirmed: '已确认',
  rejected: '已拒绝',
  needs_split: '需拆分',
  needs_merge: '需合并',
  new_topic_pending: '待新增审核',
}

export const TAXONOMY_MATCH_TYPE_LABELS: Record<string, string> = {
  exact: '精确',
  semantic: '语义',
  one_to_many: '一对多',
  many_to_one: '多对一',
  many_to_many: '多对多',
  new_topic: '无候选',
}

export function statusLabel(status: string): string {
  return TAXONOMY_STATUS_LABELS[status] ?? status
}

export function matchTypeLabel(matchType: string): string {
  return TAXONOMY_MATCH_TYPE_LABELS[matchType] ?? matchType
}

export function canReviewAction(status: TaxonomyReviewStatus, action: 'confirm' | 'reject' | 'undo'): boolean {
  const allowed: Record<TaxonomyReviewStatus, string[]> = {
    pending_review: ['confirm', 'reject'],
    new_topic_pending: ['confirm', 'reject'],
    needs_split: ['confirm', 'reject', 'undo'],
    needs_merge: ['confirm', 'reject', 'undo'],
    confirmed: ['undo'],
    rejected: ['undo'],
  }
  return allowed[status]?.includes(action) ?? false
}

export function requiresHighRiskAcknowledgement(input: {
  high_risk?: boolean
  action: string
}): boolean {
  return Boolean(input.high_risk) && input.action === 'confirm'
}

export function describeCandidate(mapping: {
  match_type: string
  confidence?: number | null
  high_risk?: boolean
  risk?: string | null
}): string {
  const parts = [matchTypeLabel(mapping.match_type)]
  if (mapping.confidence != null) parts.push(`相似度 ${mapping.confidence.toFixed(3)}`)
  if (mapping.high_risk) parts.push('高风险：需人工确认')
  else if (mapping.risk) parts.push(mapping.risk)
  return parts.join(' · ')
}

export function batchModeLabel(mode: string): string {
  return mode === 'apply' ? '正式执行' : '差异预览'
}
