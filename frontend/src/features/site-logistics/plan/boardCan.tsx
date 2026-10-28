// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// What the server lets this reader create on the delivery board. Gates,
// laydown zones and deliveries are listed as plain arrays, so the answer is a
// read of its own. A button is never active on an answer that is not there:
// it waits while the read is on its way, and when the read failed the board
// says so in one line and offers to ask again.

import { useQuery } from '@tanstack/react-query';
import { AlertTriangle } from 'lucide-react';

import { Button } from '@/shared/ui/Button';

import { fetchBoardCan, type BoardKind } from '../api';
import type { Verdict } from './api';
import { useWords } from './hooks';
import { WAITING } from './rules';
import { tx } from './texts';

function useBoardCan(projectId: string) {
  return useQuery({
    queryKey: ['site-logistics-can', projectId],
    queryFn: () => fetchBoardCan(projectId),
    enabled: !!projectId,
  });
}

/**
 * The verdict on adding a record of one kind. Without a project there is
 * nothing to ask and no verdict; otherwise it is WAITING until the server has
 * answered, and stays so when the read failed.
 */
export function useBoardCreate(projectId: string, kind: BoardKind): Verdict | undefined {
  const query = useBoardCan(projectId);
  if (!projectId) return undefined;
  return query.data ? query.data[kind]?.create : WAITING;
}

/** One line where the verdicts could not be read, with the way to ask again. */
export function BoardCanNotice({ projectId }: { projectId: string }) {
  const { t } = useWords();
  const query = useBoardCan(projectId);
  if (!query.isError || query.data) return null;
  return (
    <div
      role="alert"
      className="flex flex-wrap items-center gap-2 rounded-lg border border-semantic-warning/40 bg-semantic-warning/5 p-3 text-sm text-content-primary"
      data-testid="board-can-failed"
    >
      <AlertTriangle size={15} className="shrink-0 text-semantic-warning" aria-hidden />
      <span className="flex-1">{tx(t, 'board.can_failed')}</span>
      <Button size="sm" variant="secondary" disabled={query.isFetching} onClick={() => void query.refetch()}>
        {tx(t, 'retry')}
      </Button>
    </div>
  );
}
