import { useTranslation } from 'react-i18next';
import type { ProjectWorks } from './api';

/**​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
 * Whether the project's client is a public buyer. Where a country's law on
 * retention follows the client (France: the public procurement code for a
 * public buyer, loi 71-584 for private works), new contracts on the project
 * start from that law's terms. "Not recorded" is a real answer, not a
 * default: the server then keeps the country's neutral figures.
 */
export function ProjectWorksField({
  id,
  value,
  onChange,
  disabled = false,
  showHint = true,
}: {
  id: string;
  value: ProjectWorks | null | undefined;
  onChange: (next: ProjectWorks | null) => void;
  disabled?: boolean;
  showHint?: boolean;
}) {
  const { t } = useTranslation();
  const hintId = `${id}-hint`;
  return (
    <div>
      <label htmlFor={id} className="oe-label">
        {t('projects.works.label', { defaultValue: 'Public or private client' })}
      </label>
      <select
        id={id}
        value={value ?? ''}
        disabled={disabled}
        aria-describedby={showHint ? hintId : undefined}
        onChange={(e) => {
          const next = e.target.value;
          onChange(next === 'public' || next === 'private' ? next : null);
        }}
        className="oe-select oe-input-lg"
      >
        <option value="">{t('projects.works.unknown', { defaultValue: 'Not recorded' })}</option>
        <option value="public">{t('projects.works.public', { defaultValue: 'Public buyer (public procurement)' })}</option>
        <option value="private">{t('projects.works.private', { defaultValue: 'Private client' })}</option>
      </select>
      {showHint && (
        <p id={hintId} className="mt-1.5 text-xs text-content-tertiary">
          {t('projects.works.hint', {
            defaultValue:
              "Where a country's retention law depends on the client, as in France, new contracts start from that law's terms. Subcontracts always follow private-works law.",
          })}
        </p>
      )}
    </div>
  );
}
