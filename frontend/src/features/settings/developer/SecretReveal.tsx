// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** A secret the server returns once: shown with a copy button until the person dismisses it. */
import { useTranslation } from 'react-i18next';
import { Copy } from 'lucide-react';
import { Button } from '@/shared/ui';
import { copyToClipboard } from '@/shared/lib/browser';
import { useToastStore } from '@/stores/useToastStore';

export interface SecretRevealProps {
  title: string;
  secret: string;
  hint: string;
  onDone: () => void;
  testId: string;
}

export function SecretReveal({ title, secret, hint, onDone, testId }: SecretRevealProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);

  const copy = async () => {
    const ok = await copyToClipboard(secret);
    addToast({
      type: ok ? 'success' : 'error',
      title: ok
        ? t('developer.copied', { defaultValue: 'Copied' })
        : t('developer.copy_failed', { defaultValue: 'Could not copy. Select the text and copy it by hand.' }),
    });
  };

  return (
    <div className="mt-4 rounded-lg border border-oe-blue/30 bg-oe-blue/[0.04] p-3" role="status" data-testid={testId}>
      <p className="text-sm font-medium text-content-primary">{title}</p>
      <p className="mt-0.5 text-xs text-content-secondary">{hint}</p>
      <div className="mt-2 flex items-center gap-2">
        <code
          className="min-w-0 flex-1 break-all rounded bg-surface-secondary px-2 py-1 text-xs"
          dir="ltr"
          data-testid={`${testId}-value`}
        >
          {secret}
        </code>
        <Button size="sm" variant="ghost" icon={<Copy size={14} />} onClick={() => void copy()}>
          {t('developer.copy', { defaultValue: 'Copy' })}
        </Button>
      </div>
      <div className="mt-2 flex justify-end">
        <Button size="sm" variant="secondary" onClick={onDone} data-testid={`${testId}-done`}>
          {t('developer.done', { defaultValue: 'I have saved it' })}
        </Button>
      </div>
    </div>
  );
}
