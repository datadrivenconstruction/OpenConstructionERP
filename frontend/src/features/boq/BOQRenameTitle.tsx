// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The estimate name in the editor header. A pencil button or a double click
 * turns it into an input: Enter or blur saves, Esc cancels, an empty name is
 * refused. A locked estimate keeps a plain title.
 */

import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Pencil } from 'lucide-react';

import { useRenameBOQ } from './useRenameBOQ';

interface BOQRenameTitleProps {
  boqId: string;
  name: string;
  locked: boolean;
}

export function BOQRenameTitle({ boqId, name, locked }: BOQRenameTitleProps) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(name);
  const inputRef = useRef<HTMLInputElement>(null);
  // Esc unmounts the input, and the blur that follows must not save.
  const cancelled = useRef(false);
  const rename = useRenameBOQ(() => setEditing(false));

  useEffect(() => {
    if (editing) inputRef.current?.select();
  }, [editing]);

  const start = () => {
    if (locked) return;
    cancelled.current = false;
    setDraft(name);
    setEditing(true);
  };

  const commit = () => {
    if (cancelled.current || rename.isPending) return;
    const next = draft.trim();
    if (!next) return;
    if (next === name) {
      setEditing(false);
      return;
    }
    rename.mutate({ boqId, name: next });
  };

  if (editing) {
    return (
      <input
        ref={inputRef}
        autoFocus
        value={draft}
        maxLength={255}
        disabled={rename.isPending}
        data-testid="boq-rename-input"
        aria-label={t('boq.rename', { defaultValue: 'Rename estimate' })}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            commit();
          } else if (e.key === 'Escape') {
            cancelled.current = true;
            setEditing(false);
          }
        }}
        className="min-w-0 flex-1 rounded-md border border-oe-blue bg-surface-primary px-2 py-0.5 text-xl font-bold text-content-primary focus:outline-none"
      />
    );
  }

  return (
    <>
      <h1 className="text-xl font-bold text-content-primary truncate" onDoubleClick={start}>
        {name}
      </h1>
      {!locked && (
        <button
          type="button"
          onClick={start}
          data-testid="boq-rename-button"
          title={t('boq.rename', { defaultValue: 'Rename estimate' })}
          aria-label={t('boq.rename', { defaultValue: 'Rename estimate' })}
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-content-tertiary transition-all hover:bg-oe-blue-subtle hover:text-oe-blue-text"
        >
          <Pencil size={14} />
        </button>
      )}
    </>
  );
}
