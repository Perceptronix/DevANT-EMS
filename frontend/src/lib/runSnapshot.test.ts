import { describe, expect, it } from 'vitest'
import { isTerminalState, shouldApplySnapshot } from './runSnapshot'

describe('run snapshot guards', () => {
  it('blocks updates after terminal state', () => {
    const current = { state: 'COMPLETED' as const, transitions: [{}, {}] }
    const incoming = { state: 'COMPLETED' as const, transitions: [{}, {}, {}] }
    expect(shouldApplySnapshot(current, incoming)).toBe(false)
  })

  it('blocks stale incoming transition history', () => {
    const current = { state: 'ANALYZING' as const, transitions: [{}, {}, {}] }
    const incoming = { state: 'SCORING' as const, transitions: [{}] }
    expect(shouldApplySnapshot(current, incoming)).toBe(false)
  })

  it('accepts monotonic transition progress', () => {
    const current = { state: 'INGESTING' as const, transitions: [{}, {}] }
    const incoming = { state: 'ANALYZING' as const, transitions: [{}, {}, {}] }
    expect(shouldApplySnapshot(current, incoming)).toBe(true)
  })

  it('detects terminal states', () => {
    expect(isTerminalState('COMPLETED')).toBe(true)
    expect(isTerminalState('FAILED')).toBe(true)
    expect(isTerminalState('CANCELLED')).toBe(true)
    expect(isTerminalState('ANALYZING')).toBe(false)
  })
})
