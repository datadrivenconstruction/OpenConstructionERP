// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Typed client for the inbound-capture read surface. The capture endpoints
// themselves (POST email / webhook) are called by external systems, not the UI;
// this admin view only reads what was captured for a project.

import { apiGet } from '@/shared/lib/api';
import type { InboundCapturedList } from './types';

const BASE = '/v1/inbound-capture';

export function listCapturedMessages(
  projectId: string,
  opts: { offset?: number; limit?: number } = {},
): Promise<InboundCapturedList> {
  const params = new URLSearchParams();
  if (opts.offset != null) params.set('offset', String(opts.offset));
  if (opts.limit != null) params.set('limit', String(opts.limit));
  const qs = params.toString();
  return apiGet<InboundCapturedList>(
    `${BASE}/projects/${encodeURIComponent(projectId)}/captured${qs ? `?${qs}` : ''}`,
  );
}
