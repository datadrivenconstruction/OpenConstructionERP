// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Read client for the Data & Security posture panel (#4). One read-only GET
// that mirrors backend GET /api/system/data-security: verifiable, non-secret
// facts about where this instance keeps its data and whether it reaches out
// anywhere. No secret is ever returned - AI providers are reported by name and
// presence only. The endpoint sits at /api/system/ (not /api/v1/), so the path
// passed to apiGet is /system/... and apiGet adds the /api prefix + auth header.

import { apiGet } from '@/shared/lib/api';

export type DeploymentMode = 'desktop' | 'server';
export type DatabaseManaged = 'embedded' | 'external';
export type StorageBackend = 'local' | 's3';

export interface DataSecurityPosture {
  self_hosted: boolean;
  deployment_mode: DeploymentMode;
  demo_instance: boolean;
  version: string;
  environment: string;
  database: {
    engine: string;
    managed: DatabaseManaged;
    on_your_infrastructure: boolean;
  };
  storage: {
    backend: StorageBackend;
    on_your_infrastructure: boolean;
  };
  ai: {
    enabled: boolean;
    providers: string[];
    offline_capable: boolean;
    external_calls: boolean;
  };
  registration_mode: string;
  analytics_bundled: boolean;
  source: {
    license: string;
    repository: string;
  };
}

export function getDataSecurity(): Promise<DataSecurityPosture> {
  return apiGet<DataSecurityPosture>('/system/data-security');
}

export const dataSecurityKeys = {
  posture: () => ['data-security', 'posture'] as const,
};
