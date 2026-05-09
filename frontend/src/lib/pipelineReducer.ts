export type StageState = 'pending' | 'running' | 'partial' | 'completed' | 'failed'

export interface StageEntry {
  id: string
  name: string
  state: StageState
  progress?: number
  evidence?: any
  note?: string
}

export interface PipelineState {
  stages: StageEntry[]
}

export function applyStageEvent(state: PipelineState, event: any): PipelineState {
  // event { seq, event, stage, status, evidence, partial_result }
  const stageId = event.stage
  const status = (event.status || 'partial') as StageState
  const idx = state.stages.findIndex((s) => s.id === stageId || s.name.toLowerCase() === stageId.toLowerCase())
  const copy = { ...state, stages: state.stages.map((s) => ({ ...s })) }

  if (idx >= 0) {
    const target = copy.stages[idx]
    target.state = status
    if (event.partial_result && typeof event.partial_result.progress === 'number') target.progress = event.partial_result.progress
    if (event.evidence) target.evidence = event.evidence
    if (event.partial_result?.note) target.note = event.partial_result.note
  } else {
    // append unknown stage
    copy.stages.push({ id: stageId, name: stageId, state: status, evidence: event.evidence, progress: event.partial_result?.progress })
  }

  return copy
}
