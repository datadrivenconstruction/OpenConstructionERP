// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Typed client for the /api/v1/connectors/* surface.

import { apiGet, apiPost } from '@/shared/lib/api';
import type { ConnectorSource, ConnectorSourceCreate, ConnectorSyncResult } from './types';

const BASE = '/v1/connectors';

export const listConnectorSources = (projectId: string) =>
  apiGet<ConnectorSource[]>(`${BASE}/sources/?project_id=${encodeURIComponent(projectId)}`);

export const createConnectorSource = (projectId: string, body: ConnectorSourceCreate) =>
  apiPost<ConnectorSource, ConnectorSourceCreate>(
    `${BASE}/sources/?project_id=${encodeURIComponent(projectId)}`,
    body,
  );

export const syncConnectorSource = (sourceId: string) =>
  apiPost<ConnectorSyncResult, Record<string, never>>(`${BASE}/sources/${sourceId}/sync`, {});
