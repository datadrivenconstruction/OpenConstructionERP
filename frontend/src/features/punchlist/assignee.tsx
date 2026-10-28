// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Who a punch item is assigned to, in a form a reader can use.
 *
 * `assigned_to` is a free-text column and both a typed-in name and a contact
 * id are legitimate contents - the demo seeder, and the integrations that
 * follow it, store an id. Every screen printed the column as it stood, so a
 * row read "Assigned To 3f2b8c1e-9a44-..." and the avatar beside it took its
 * initial from a hex digit. The API now resolves ids against the contacts
 * register and sends `assigned_to_name` beside the raw value; this module
 * decides what to paint from the pair, so the list, the kanban card, the
 * drawer and the insights charts all say the same thing.
 *
 * An id that resolved to nothing is deliberately not shown as "Unassigned".
 * The snag does have an owner, we simply cannot name them, and telling a site
 * manager it is unassigned invites a second assignment.
 */

import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { resolvePartyName, type PartyName } from '@/shared/lib/partyName';

// Change orders, the plan-room overlay and the markup hub print the same kind
// of column, so the decision itself moved to `shared/lib/partyName`. The names
// stay here because they are what this module's callers and tests ask for, and
// those tests are the guard that moving it changed none of the answers.
export type Assignee = PartyName;
export const resolveAssignee = resolvePartyName;

type Variant = 'card' | 'row' | 'plain';

const AVATAR: Record<Variant, string> = {
  card: 'h-5 w-5 text-2xs',
  row: 'h-6 w-6 text-xs',
  plain: '',
};

const NAME: Record<Variant, string> = {
  card: 'truncate max-w-[80px]',
  row: 'text-sm text-content-secondary truncate max-w-[100px]',
  plain: '',
};

const MUTED: Record<Variant, string> = {
  card: 'text-content-quaternary',
  row: 'text-sm text-content-quaternary',
  plain: 'text-content-quaternary',
};

/**
 * Paint the assignee of one punch item.
 *
 * @param raw - `item.assigned_to`.
 * @param name - `item.assigned_to_name`.
 * @param variant - Which surface is painting: a kanban card, a table row, or
 *   a drawer field that carries its own label and needs no avatar.
 */
export function AssigneeLabel({
  raw,
  name,
  variant = 'row',
}: {
  raw: string | null | undefined;
  name?: string | null;
  variant?: Variant;
}) {
  const { t } = useTranslation();
  const assignee = resolveAssignee(raw, name);

  if (assignee.kind !== 'named') {
    return (
      <span className={MUTED[variant]}>
        {assignee.kind === 'none'
          ? t('punch.unassigned', { defaultValue: 'Unassigned' })
          : t('common.unknown', { defaultValue: 'Unknown' })}
      </span>
    );
  }

  if (variant === 'plain') return <>{assignee.name}</>;

  return (
    <>
      <div
        className={clsx(
          'rounded-full bg-oe-blue/10 text-oe-blue flex items-center justify-center font-semibold shrink-0',
          AVATAR[variant],
        )}
      >
        {assignee.name.charAt(0).toUpperCase()}
      </div>
      <span className={NAME[variant]}>{assignee.name}</span>
    </>
  );
}
