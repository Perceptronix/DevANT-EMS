export enum CognitionLayer {
  INGESTION = 'ingestion',
  SYSTEM_INTELLIGENCE = 'system_intelligence',
  OPERATIONAL_RISK = 'operational_risk',
  TEMPORAL_MEMORY = 'temporal_memory',
}

export const BackendStageToLayer: Record<string, CognitionLayer> = {
  // Ingestion
  repository_ingestion: CognitionLayer.INGESTION,
  workflow_discovery: CognitionLayer.INGESTION,
  deployment_analysis: CognitionLayer.INGESTION,

  // System intelligence
  observability_analysis: CognitionLayer.SYSTEM_INTELLIGENCE,
  topology_inference: CognitionLayer.SYSTEM_INTELLIGENCE,
  topology_propagation: CognitionLayer.SYSTEM_INTELLIGENCE,

  // Operational risk
  regression_risk_analysis: CognitionLayer.OPERATIONAL_RISK,
  operational_scoring: CognitionLayer.OPERATIONAL_RISK,
  confidence_calibration: CognitionLayer.OPERATIONAL_RISK,

  // Temporal memory
  incident_memory: CognitionLayer.TEMPORAL_MEMORY,
  temporal_memory_analysis: CognitionLayer.TEMPORAL_MEMORY,
}

export function mapStageToLayer(stageId: string) {
  return BackendStageToLayer[stageId] ?? CognitionLayer.SYSTEM_INTELLIGENCE
}
