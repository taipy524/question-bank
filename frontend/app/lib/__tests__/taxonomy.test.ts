import { describe, expect, it } from 'vitest'
import {
  batchModeLabel,
  canReviewAction,
  describeCandidate,
  matchTypeLabel,
  requiresHighRiskAcknowledgement,
  statusLabel,
} from '../taxonomy'

describe('taxonomy UI helpers', () => {
  it('labels review states and match types', () => {
    expect(statusLabel('pending_review')).toBe('待审核')
    expect(statusLabel('new_topic_pending')).toBe('待新增审核')
    expect(matchTypeLabel('one_to_many')).toBe('一对多')
    expect(matchTypeLabel('unknown')).toBe('unknown')
  })

  it('enforces review transitions in the UI', () => {
    expect(canReviewAction('pending_review', 'confirm')).toBe(true)
    expect(canReviewAction('pending_review', 'undo')).toBe(false)
    expect(canReviewAction('confirmed', 'undo')).toBe(true)
    expect(canReviewAction('rejected', 'confirm')).toBe(false)
  })

  it('requires acknowledgement only for high-risk confirmations', () => {
    expect(requiresHighRiskAcknowledgement({ high_risk: true, action: 'confirm' })).toBe(true)
    expect(requiresHighRiskAcknowledgement({ high_risk: true, action: 'reject' })).toBe(false)
    expect(requiresHighRiskAcknowledgement({ high_risk: false, action: 'confirm' })).toBe(false)
  })

  it('describes candidates without hiding risk', () => {
    expect(describeCandidate({ match_type: 'semantic', confidence: 0.6, high_risk: true })).toContain('高风险')
    expect(describeCandidate({ match_type: 'exact', confidence: 0.9, risk: 'single_char_difference' })).toContain('single_char_difference')
  })

  it('labels batch modes', () => {
    expect(batchModeLabel('apply')).toBe('正式执行')
    expect(batchModeLabel('dry_run')).toBe('差异预览')
  })
})
