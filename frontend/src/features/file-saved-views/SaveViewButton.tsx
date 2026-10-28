// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// SaveViewButton — pill CTA that opens the SaveViewDialog so the
// caller can capture the current filter snapshot as a named view.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Bookmark } from 'lucide-react';

import { Button } from '@/shared/ui/Button';
import { SaveViewDialog } from './SaveViewDialog';
import type { FilterSnapshot } from './types';

interface SaveViewButtonProps {
  projectId: string | null | undefined;
  /** The current filter snapshot to save when the user submits. */
  filter: FilterSnapshot;
  /** Hide the button entirely when the filter is empty (caller's
   *  responsibility to compute "non-default"); when omitted, render
   *  unconditionally. */
  visible?: boolean;
  size?: 'sm' | 'md';
}

export function SaveViewButton({ projectId, filter, visible = true, size = 'sm' }: SaveViewButtonProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);

  if (!visible) return null;

  return (
    <>
      <Button
        variant="secondary"
        size={size}
        icon={<Bookmark className="h-3.5 w-3.5" />}
        onClick={() => setOpen(true)}
        data-testid="save-view-button"
      >
        {t('files.views.save_button', { defaultValue: 'Save view' })}
      </Button>
      <SaveViewDialog
        open={open}
        onClose={() => setOpen(false)}
        projectId={projectId}
        filter={filter}
      />
    </>
  );
}
