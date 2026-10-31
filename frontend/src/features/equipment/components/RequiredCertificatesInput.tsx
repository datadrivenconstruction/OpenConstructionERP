// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { X } from 'lucide-react';

/** Trim, drop blanks and case-insensitive duplicates, keep order. */
export function addCertificate(current: string[], raw: string): string[] {
  const name = raw.trim();
  if (!name || current.some((c) => c.toLowerCase() === name.toLowerCase())) return current;
  return [...current, name];
}

interface Props {
  value: string[];
  onChange: (next: string[]) => void;
  /** Certificate types already on file in the resources module. */
  suggestions: string[];
}

/** Tag input for the certificate types an operator needs for a machine. */
export function RequiredCertificatesInput({ value, onChange, suggestions }: Props) {
  const { t } = useTranslation();
  const listId = useId();
  const [draft, setDraft] = useState('');

  const commit = () => {
    onChange(addCertificate(value, draft));
    setDraft('');
  };

  return (
    <div>
      <div className="flex flex-wrap items-center gap-1.5 rounded-lg border border-border bg-surface-primary px-2 py-1.5">
        {value.map((c) => (
          <span
            key={c}
            className="inline-flex items-center gap-1 rounded-full bg-oe-blue-subtle px-2 py-0.5 text-xs text-oe-blue"
          >
            {c}
            <button
              type="button"
              aria-label={t('equipment.required_certs_remove', {
                defaultValue: 'Remove {{name}}',
                name: c,
              })}
              onClick={() => onChange(value.filter((x) => x !== c))}
            >
              <X size={12} />
            </button>
          </span>
        ))}
        <input
          type="text"
          list={listId}
          value={draft}
          maxLength={128}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ',') {
              e.preventDefault();
              commit();
            } else if (e.key === 'Backspace' && draft === '' && value.length > 0) {
              onChange(value.slice(0, -1));
            }
          }}
          onBlur={commit}
          placeholder={t('equipment.required_certs_placeholder', {
            defaultValue: 'Add a certificate type',
          })}
          className="min-w-[10rem] flex-1 bg-transparent text-sm outline-none"
        />
        <datalist id={listId}>
          {suggestions.map((s) => (
            <option key={s} value={s} />
          ))}
        </datalist>
      </div>
      <p className="mt-1 text-xs text-content-tertiary">
        {t('equipment.required_certs_hint', {
          defaultValue:
            'The dispatch board warns when an operator without these certificates is paired with this machine.',
        })}
      </p>
    </div>
  );
}
