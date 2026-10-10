// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// HakedisDialog - the payment certificate in a dialog, for a document that is
// shown as a row of a list and has no page of its own (a subcontractor payment
// application). The panel inside is the one a progress claim shows.

import { useTranslation } from 'react-i18next';

import { Button, WideModal } from '@/shared/ui';
import type { HakedisSource } from './api';
import { HakedisPanel } from './HakedisPanel';

export interface HakedisDialogProps {
  source: HakedisSource;
  /** Names the document in the title, e.g. its application number. */
  reference?: string;
  onClose: () => void;
}

export function HakedisDialog({ source, reference, onClose }: HakedisDialogProps) {
  const { t } = useTranslation();
  return (
    <WideModal
      open
      onClose={onClose}
      size="full"
      title={t('hakedis.title', { defaultValue: 'Payment certificate' })}
      subtitle={reference}
      footer={
        <Button variant="secondary" onClick={onClose} data-testid="hakedis-dialog-close">
          {t('hakedis.dialog.close', { defaultValue: 'Close' })}
        </Button>
      }
    >
      <HakedisPanel source={source} />
    </WideModal>
  );
}
