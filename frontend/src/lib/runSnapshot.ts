export type JobState =
  | 'PENDING'
  | 'INITIALIZING'
  | 'INGESTING'
  | 'ANALYZING'
  | 'SCORING'
  | 'FINALIZING'
  | 'COMPLETED'
  | 'FAILED'
  | 'CANCELLED'

export interface MinimalSnapshot {
  state: JobState
  transitions?: Array<unknown>
  partial?: Record<string, unknown>
}

export function isTerminalState(state: JobState | undefined): boolean {
  return state === 'COMPLETED' || state === 'FAILED' || state === 'CANCELLED'
}

export function shouldApplySnapshot(current: MinimalSnapshot | null, incoming: MinimalSnapshot): boolean {
  const currentCount = current?.transitions?.length ?? 0
  const incomingCount = incoming.transitions?.length ?? 0

  if (isTerminalState(current?.state)) return false
  if (incomingCount < currentCount) return false
  
  // Allow update if transition count increased
  if (incomingCount > currentCount) return true
  
  // Even if transition count is the same, allow update if partial data changed
  const currentPartialSig = JSON.stringify(current?.partial || {})
  const incomingPartialSig = JSON.stringify(incoming.partial || {})
  if (currentPartialSig !== incomingPartialSig) return true
  
  // Allow update if state changed
  if (current?.state !== incoming.state) return true
  
  return false
}
