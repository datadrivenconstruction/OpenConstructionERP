// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Layer legend + visibility toggles.
 *
 * One row per overlay source: a colour swatch, the layer name, its count on
 * this page and a checkbox that shows / hides that layer on the sheet. This is
 * the control a site engineer reads first - "what is on this drawing, and let
 * me turn the noise off".
 *
 * A layer with nothing on this page carries a muted link to the module where
 * that kind of mark is made, so a zero reads as "none yet, add them there"
 * rather than as a broken layer. Plan pins have no link: they are dropped
 * right here with the toolbar button.
 */

import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Eye, EyeOff, Layers } from 'lucide-react';
import clsx from 'clsx';
import { LAYERS, type LayerKey } from './layers';

/** Where each kind of mark is made, for the zero-count hint. */
const SOURCE_LINKS: Partial<Record<LayerKey, { to: string; labelKey: string; defaultLabel: string }>> = {
  punch: { to: '/punchlist', labelKey: 'plan_room.layer_add_punch', defaultLabel: 'Add in the punch list' },
  markups: { to: '/markups', labelKey: 'plan_room.layer_add_markups', defaultLabel: 'Add in Markups' },
  measurements: { to: '/takeoff', labelKey: 'plan_room.layer_add_measurements', defaultLabel: 'Measure in Takeoff' },
  photos: { to: '/photos', labelKey: 'plan_room.layer_add_photos', defaultLabel: 'Upload in Photos' },
};

interface Props {
  visibility: Record<LayerKey, boolean>;
  counts: Record<LayerKey, number>;
  onToggle: (key: LayerKey) => void;
}

export function LayerPanel({ visibility, counts, onToggle }: Props) {
  const { t } = useTranslation();

  return (
    <div className="rounded-xl border border-border-light bg-surface-primary p-3">
      <h4 className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-content-tertiary">
        <Layers size={13} />
        {t('plan_room.layers', { defaultValue: 'Layers' })}
      </h4>
      <ul className="space-y-0.5">
        {LAYERS.map((layer) => {
          const on = visibility[layer.key];
          const count = counts[layer.key] ?? 0;
          const source = count === 0 ? SOURCE_LINKS[layer.key] : undefined;
          return (
            <li key={layer.key}>
              <button
                type="button"
                onClick={() => onToggle(layer.key)}
                aria-pressed={on}
                className={clsx(
                  'flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm',
                  'hover:bg-surface-secondary focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40',
                  !on && 'opacity-50',
                )}
              >
                <span
                  className="h-3 w-3 shrink-0 rounded-sm border border-black/10"
                  style={{ backgroundColor: layer.color }}
                  aria-hidden
                />
                <span className="min-w-0 flex-1 truncate text-content-secondary">
                  {t(layer.labelKey, { defaultValue: layer.defaultLabel })}
                </span>
                <span className="shrink-0 text-2xs tabular-nums text-content-quaternary">
                  {count}
                </span>
                {on ? (
                  <Eye size={14} className="shrink-0 text-content-tertiary" />
                ) : (
                  <EyeOff size={14} className="shrink-0 text-content-quaternary" />
                )}
              </button>
              {source && (
                <Link
                  to={source.to}
                  className="block pb-1 pl-7 text-2xs text-content-quaternary underline-offset-2 hover:text-oe-blue hover:underline"
                >
                  {t(source.labelKey, { defaultValue: source.defaultLabel })}
                </Link>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
