// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * The base modules' view INTO the registers.
 *
 * An RFI list, a purchase-order table or a bid-package table knows its own
 * ids and nothing about the registers. One call per page answers "which of
 * these rows was raised from a register item", keyed by the native id, so
 * a row can wear its `REG-RFI-25406-0001` chip without a round trip each.
 */
import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  fetchLinkedItems,
  type Kind,
  type LinkedEntityType,
  type LinkedItem,
} from './registers-api';

/**
 * `Map<linked_entity_id, LinkedItem>` for one project and one native
 * register. Pass `ids` to narrow to the rows on screen (a detail page
 * passes its single id); leave it out to take the whole project in one go.
 *
 * Fails soft: a project without the registers module, or a viewer without
 * `register_workflow.read`, gets an empty map and the page is unchanged.
 */
export function useRegisterLinks(
  projectId: string | null | undefined,
  entityType: LinkedEntityType,
  ids?: string[],
): Map<string, LinkedItem> {
  const narrowed = ids ? Array.from(new Set(ids.filter(Boolean))).sort() : undefined;
  const idKey = narrowed ? narrowed.join(',') : '*';
  const query = useQuery<LinkedItem[]>({
    queryKey: ['register-links', projectId ?? '', entityType, idKey],
    queryFn: () => fetchLinkedItems(projectId as string, entityType, narrowed),
    // "Nothing on screen" is nothing to ask about.
    enabled: !!projectId && (narrowed === undefined || narrowed.length > 0),
    retry: false,
    staleTime: 30_000,
  });
  return useMemo(() => {
    const map = new Map<string, LinkedItem>();
    for (const row of query.data ?? []) map.set(row.linked_entity_id, row);
    return map;
  }, [query.data]);
}

/** What a Correspondence row's metadata says about the register item it went out for. */
export interface MetadataRegisterLink {
  item_id: string;
  reference: string;
  kind: Kind | null;
}

const KINDS: readonly string[] = ['rfi', 'rfq', 'order', 'variation', 'delay', 'toolbox'];

/**
 * A register send is filed as a Correspondence row carrying the item's id,
 * kind and reference in `metadata.project_mail` (see emailing.py). That is
 * enough for a chip without any fetch; older flat keys are honoured too.
 */
export function registerLinkFromMetadata(metadata: unknown): MetadataRegisterLink | null {
  if (!metadata || typeof metadata !== 'object') return null;
  const top = metadata as Record<string, unknown>;
  const pm =
    top.project_mail && typeof top.project_mail === 'object'
      ? (top.project_mail as Record<string, unknown>)
      : {};
  const itemId = String(pm.register_item_id ?? top.register_item_id ?? '').trim();
  if (!itemId) return null;
  const kindRaw = String(pm.register_kind ?? top.register_kind ?? '')
    .trim()
    .toLowerCase();
  const kind = KINDS.includes(kindRaw) ? (kindRaw as Kind) : null;
  const reference = String(pm.ref ?? top.register_reference ?? '').trim();
  return {
    item_id: itemId,
    reference: reference || (kind ? `REG-${kind.toUpperCase()}` : 'REG'),
    kind,
  };
}
