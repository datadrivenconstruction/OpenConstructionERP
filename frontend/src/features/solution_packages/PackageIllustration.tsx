// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * One line drawing per solution package, drawn here so every card shares one
 * stroke weight, one grid and the theme's own colours (currentColor plus the
 * accent), in light and dark alike.
 */
import type { ReactNode } from 'react';

const ART: Record<string, ReactNode> = {
  estimate_quote: (
    <>
      <rect x="34" y="14" width="40" height="52" rx="3" />
      <path d="M42 26h24M42 34h24M42 42h14M42 50h18" />
      <rect x="70" y="40" width="20" height="26" rx="2" className="oe-pk-accent" />
      <path d="M74 46h12M74 53h4M82 53h4M74 60h4M82 60h4" className="oe-pk-accent" />
    </>
  ),
  trades: (
    <>
      <path d="M30 62l26-26" />
      <path d="M52 32l8-8 10 10-8 8z" className="oe-pk-accent" />
      <path d="M64 62l20-20M80 38a6 6 0 1 0 8 8" />
      <path d="M26 66h68" />
    </>
  ),
  takeoff: (
    <>
      <rect x="26" y="16" width="56" height="44" rx="2" />
      <path d="M34 50V26h20v12h18v12z" className="oe-pk-accent" />
      <path d="M26 68h56M26 64v8M82 64v8" />
    </>
  ),
  tender_procurement: (
    <>
      <rect x="24" y="22" width="30" height="38" rx="2" />
      <path d="M30 32h18M30 40h18M30 48h10" />
      <path d="M62 42l10-10 8 8-10 10z" className="oe-pk-accent" />
      <path d="M68 46l-12 12M84 62H62" />
    </>
  ),
  site_field: (
    <>
      <path d="M32 50a28 20 0 0 1 56 0z" className="oe-pk-accent" />
      <path d="M28 50h64M60 30v-8M52 32l2-8M68 32l-2-8" />
      <path d="M36 62h48" />
    </>
  ),
  project_controls: (
    <>
      <path d="M26 64h68M26 64V18" />
      <path d="M32 56l14-12 12 6 14-18 14 8" className="oe-pk-accent" />
      <path d="M34 26h16M34 32h10" />
    </>
  ),
  subcontractor: (
    <>
      <path d="M24 44l12-10h12l8 6 8-6h12l12 10" />
      <path d="M40 44l12 10c3 2 6 2 8 0l12-10" className="oe-pk-accent" />
      <path d="M48 58l4 4M56 60l2 2" />
    </>
  ),
  service_maintenance: (
    <>
      <circle cx="60" cy="40" r="16" />
      <circle cx="60" cy="40" r="6" className="oe-pk-accent" />
      <path d="M60 18v6M60 56v6M38 40h6M76 40h6M45 25l4 4M71 51l4 4M45 55l4-4M71 29l4-4" />
    </>
  ),
  developer_owner: (
    <>
      <path d="M28 66V34l14-8v40M42 66V22l18-8v52M60 66V30h22v36" />
      <path d="M48 30h6M48 40h6M48 50h6M66 38h10M66 48h10" className="oe-pk-accent" />
      <path d="M22 66h76" />
    </>
  ),
  real_estate_gcc: (
    <>
      <path d="M34 66V20h26v46M60 66V36h24v30" />
      <path d="M40 28h4M50 28h4M40 38h4M50 38h4M40 48h4M50 48h4" />
      <circle cx="72" cy="46" r="5" className="oe-pk-accent" />
      <path d="M72 51v9M72 56h4" className="oe-pk-accent" />
      <path d="M22 66h76" />
    </>
  ),
  supply_chain: (
    <>
      <path d="M24 30h36v26H24zM60 38h14l10 10v8H60" />
      <circle cx="34" cy="60" r="5" />
      <circle cx="74" cy="60" r="5" />
      <rect x="86" y="18" width="14" height="14" rx="1" className="oe-pk-accent" />
      <path d="M90 22h2v2h-2zM95 27h2v2h-2zM30 38h24M30 46h24" className="oe-pk-accent" />
    </>
  ),
  bim_model: (
    <>
      <path d="M60 16l24 12v26L60 66 36 54V28z" />
      <path d="M36 28l24 12 24-12M60 40v26" className="oe-pk-accent" />
    </>
  ),
};

export function PackageIllustration({ id, className }: { id: string; className?: string }) {
  return (
    <svg
      viewBox="0 0 120 80"
      role="presentation"
      aria-hidden="true"
      className={className}
      fill="none"
      stroke="currentColor"
      strokeWidth={2.2}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <rect x="1" y="1" width="118" height="78" rx="12" className="fill-current opacity-[0.06]" stroke="none" />
      <g className="[&_.oe-pk-accent]:stroke-oe-blue">{ART[id] ?? ART.estimate_quote}</g>
    </svg>
  );
}
