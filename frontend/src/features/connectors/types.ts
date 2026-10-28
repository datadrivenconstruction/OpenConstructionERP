// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

/** Summary of a connector's most recent sync. */
export interface ConnectorLastResult {
  created: number;
  duplicate: number;
  already_known: number;
  total: number;
  at?: string;
}

/** A registered inbound document source for a project. */
export interface ConnectorSource {
  id: string;
  project_id: string;
  kind: string;
  name: string;
  root_path: string;
  enabled: boolean;
  last_synced_at: string | null;
  last_result: ConnectorLastResult | null;
  created_at: string;
  updated_at: string;
}

/** Payload to register a new connector source. */
export interface ConnectorSourceCreate {
  name: string;
  root_path: string;
  kind?: string;
  enabled?: boolean;
}

/** Outcome of triggering a sync on a source. */
export interface ConnectorSyncResult {
  source_id: string;
  created: number;
  duplicate: number;
  already_known: number;
  total: number;
  created_document_ids: string[];
}
