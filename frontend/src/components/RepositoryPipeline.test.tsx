import { describe, it, expect } from 'vitest'
import { normalize } from './RepositoryPipeline'

describe('RepositoryPipeline.normalize', () => {
  it('converts snake_case to Title Case', () => {
    expect(normalize('workflow_discovery')).toBe('Workflow Discovery')
  })

  it('converts kebab-case and camelCase', () => {
    expect(normalize('deployment-analysis')).toBe('Deployment Analysis')
    expect(normalize('topologyInference')).toBe('Topology Inference')
  })
})
