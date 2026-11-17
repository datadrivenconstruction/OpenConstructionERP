// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import type { RequiredDocument } from './api';

/** Toggle a role in the list, keeping the order and never listing a role twice. */
export function toggleRole(list: RequiredDocument[], role: string, signed = false): RequiredDocument[] {
  return list.some((r) => r.role === role) ? list.filter((r) => r.role !== role) : [...list, { role, signed }];
}
