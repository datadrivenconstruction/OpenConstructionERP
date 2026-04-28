/**
 * Inline SVG flags — no external CDN dependency.
 * Each flag is a minimal but recognizable SVG at small sizes (16–40px).
 */

const FLAGS: Record<string, string> = {
  // GB — Union Jack
  gb: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 60 30"><clipPath id="s"><path d="M0 0v30h60V0z"/></clipPath><clipPath id="t"><path d="M30 15h30v15zv15H0zH0V0zV0h30z"/></clipPath><g clip-path="url(#s)"><path d="M0 0v30h60V0z" fill="#012169"/><path d="M0 0l60 30m0-30L0 30" stroke="#fff" stroke-width="6"/><path d="M0 0l60 30m0-30L0 30" clip-path="url(#t)" stroke="#C8102E" stroke-width="4"/><path d="M30 0v30M0 15h60" stroke="#fff" stroke-width="10"/><path d="M30 0v30M0 15h60" stroke="#C8102E" stroke-width="6"/></g></svg>`,

  // DE — Germany
  de: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 5 3"><rect width="5" height="1" fill="#000"/><rect y="1" width="5" height="1" fill="#D00"/><rect y="2" width="5" height="1" fill="#FFCE00"/></svg>`,

  // FR — France
  fr: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 3 2"><rect width="1" height="2" fill="#002395"/><rect x="1" width="1" height="2" fill="#fff"/><rect x="2" width="1" height="2" fill="#ED2939"/></svg>`,

  // ES — Spain
  es: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 6 4"><rect width="6" height="4" fill="#AA151B"/><rect y="1" width="6" height="2" fill="#F1BF00"/></svg>`,

  // BR — Brazil
  br: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 14"><rect width="20" height="14" fill="#009B3A"/><path d="M10 1.5l8.5 5.5L10 12.5 1.5 7z" fill="#FEDF00"/><circle cx="10" cy="7" r="3" fill="#002776"/><path d="M7.5 6.8a3 3 0 0 0 5 0" fill="none" stroke="#fff" stroke-width=".3"/></svg>`,

  // RU — Russia
  ru: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 9 6"><rect width="9" height="2" fill="#fff"/><rect y="2" width="9" height="2" fill="#0039A6"/><rect y="4" width="9" height="2" fill="#D52B1E"/></svg>`,

  // CN — China
  cn: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 20"><rect width="30" height="20" fill="#DE2910"/><g fill="#FFDE00" transform="translate(5,4)"><polygon points="0,-3 .87,.87 -2.43,-1.13 2.43,-1.13 -.87,.87" transform="scale(.9)"/></g><g fill="#FFDE00" transform="translate(10,1.5)"><polygon points="0,-1.5 .44,.44 -1.21,-.56 1.21,-.56 -.44,.44" transform="scale(.5)"/></g><g fill="#FFDE00" transform="translate(12,3.5)"><polygon points="0,-1.5 .44,.44 -1.21,-.56 1.21,-.56 -.44,.44" transform="scale(.5)"/></g><g fill="#FFDE00" transform="translate(12,6.5)"><polygon points="0,-1.5 .44,.44 -1.21,-.56 1.21,-.56 -.44,.44" transform="scale(.5)"/></g><g fill="#FFDE00" transform="translate(10,8.5)"><polygon points="0,-1.5 .44,.44 -1.21,-.56 1.21,-.56 -.44,.44" transform="scale(.5)"/></g></svg>`,

  // SA — Saudi Arabia
  sa: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 6 4"><rect width="6" height="4" fill="#006C35"/><rect x="1.5" y="1" width="3" height="1" rx=".2" fill="#fff" opacity=".9"/><rect x="2.5" y="2.2" width="1" height=".6" rx=".1" fill="#fff" opacity=".9"/></svg>`,

  // IN — India
  in: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 6 4"><rect width="6" height="1.33" fill="#FF9933"/><rect y="1.33" width="6" height="1.34" fill="#fff"/><rect y="2.67" width="6" height="1.33" fill="#138808"/><circle cx="3" cy="2" r=".55" fill="none" stroke="#000080" stroke-width=".12"/><circle cx="3" cy="2" r=".07" fill="#000080"/></svg>`,

  // TR — Turkey
  tr: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 20"><rect width="30" height="20" fill="#E30A17"/><circle cx="10.5" cy="10" r="5" fill="#fff"/><circle cx="12" cy="10" r="4" fill="#E30A17"/><polygon points="16,10 13.5,8.5 14.5,10 13.5,11.5" fill="#fff"/></svg>`,

  // IT — Italy
  it: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 3 2"><rect width="1" height="2" fill="#009246"/><rect x="1" width="1" height="2" fill="#fff"/><rect x="2" width="1" height="2" fill="#CE2B37"/></svg>`,

  // NL — Netherlands
  nl: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 9 6"><rect width="9" height="2" fill="#AE1C28"/><rect y="2" width="9" height="2" fill="#fff"/><rect y="4" width="9" height="2" fill="#21468B"/></svg>`,

  // PL — Poland
  pl: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 8 5"><rect width="8" height="2.5" fill="#fff"/><rect y="2.5" width="8" height="2.5" fill="#DC143C"/></svg>`,

  // CZ — Czech Republic
  cz: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 6 4"><rect width="6" height="2" fill="#fff"/><rect y="2" width="6" height="2" fill="#D7141A"/><polygon points="0,0 3,2 0,4" fill="#11457E"/></svg>`,

  // JP — Japan
  jp: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 20"><rect width="30" height="20" fill="#fff"/><circle cx="15" cy="10" r="6" fill="#BC002D"/></svg>`,

  // KR — South Korea
  kr: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 20"><rect width="30" height="20" fill="#fff"/><circle cx="15" cy="10" r="5" fill="#C60C30"/><path d="M15 5a5 5 0 0 1 0 10 2.5 2.5 0 0 1 0-5 2.5 2.5 0 0 0 0-5z" fill="#003478"/></svg>`,

  // SE — Sweden
  se: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 10"><rect width="16" height="10" fill="#006AA7"/><rect x="5" width="2" height="10" fill="#FECC00"/><rect y="4" width="16" height="2" fill="#FECC00"/></svg>`,

  // NO — Norway
  no: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 22 16"><rect width="22" height="16" fill="#BA0C2F"/><rect x="6" width="4" height="16" fill="#fff"/><rect y="6" width="22" height="4" fill="#fff"/><rect x="7" width="2" height="16" fill="#00205B"/><rect y="7" width="22" height="2" fill="#00205B"/></svg>`,

  // DK — Denmark
  dk: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 37 28"><rect width="37" height="28" fill="#C8102E"/><rect x="12" width="4" height="28" fill="#fff"/><rect y="12" width="37" height="4" fill="#fff"/></svg>`,

  // FI — Finland
  fi: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 18 11"><rect width="18" height="11" fill="#fff"/><rect x="5" width="3" height="11" fill="#003580"/><rect y="4" width="18" height="3" fill="#003580"/></svg>`,

  // BG — Bulgaria
  bg: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 5 3"><rect width="5" height="1" fill="#fff"/><rect y="1" width="5" height="1" fill="#00966E"/><rect y="2" width="5" height="1" fill="#D62612"/></svg>`,

  // US — United States
  us: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 19 10"><rect width="19" height="10" fill="#B22234"/><g fill="#fff"><rect y=".77" width="19" height=".77"/><rect y="2.31" width="19" height=".77"/><rect y="3.85" width="19" height=".77"/><rect y="5.38" width="19" height=".77"/><rect y="6.92" width="19" height=".77"/><rect y="8.46" width="19" height=".77"/></g><rect width="7.6" height="5.38" fill="#3C3B6E"/><g fill="#fff" font-size="1" font-family="serif"><text x="1" y="1.2">★</text><text x="2.5" y="1.2">★</text><text x="4" y="1.2">★</text><text x="5.5" y="1.2">★</text><text x="1.7" y="2.4">★</text><text x="3.2" y="2.4">★</text><text x="4.7" y="2.4">★</text><text x="1" y="3.6">★</text><text x="2.5" y="3.6">★</text><text x="4" y="3.6">★</text><text x="5.5" y="3.6">★</text><text x="1.7" y="4.8">★</text><text x="3.2" y="4.8">★</text><text x="4.7" y="4.8">★</text></g></svg>`,

  // CA — Canada
  ca: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 10"><rect width="5" height="10" fill="#FF0000"/><rect x="5" width="10" height="10" fill="#fff"/><rect x="15" width="5" height="10" fill="#FF0000"/><path d="M10 2l.5 1.5H9.5L10 2zm-1.5 2l1.5.5-1 1.5H8l.5-2zm3 0L10 4.5l1 1.5h1l-.5-2zM10 7l-.5-1.5h1L10 7z" fill="#FF0000"/></svg>`,

  // AE — UAE
  ae: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 12 6"><rect y="0" width="12" height="2" fill="#00732F"/><rect y="2" width="12" height="2" fill="#fff"/><rect y="4" width="12" height="2" fill="#000"/><rect width="3" height="6" fill="#FF0000"/></svg>`,
};

/** Fallback emoji map for unknown codes. Covers everything that lands in
 *  REGION_MAP (`useCostDatabaseStore.ts`), including the 19 cost-database
 *  countries added in v2.6.23 — without these the new entries rendered
 *  as a blank slot in the onboarding wizard and Import database page. */
const EMOJI_FALLBACK: Record<string, string> = {
  gb: '🇬🇧', de: '🇩🇪', fr: '🇫🇷', es: '🇪🇸', br: '🇧🇷',
  ru: '🇷🇺', cn: '🇨🇳', sa: '🇸🇦', in: '🇮🇳', tr: '🇹🇷',
  it: '🇮🇹', nl: '🇳🇱', pl: '🇵🇱', cz: '🇨🇿', jp: '🇯🇵',
  kr: '🇰🇷', se: '🇸🇪', no: '🇳🇴', dk: '🇩🇰', fi: '🇫🇮',
  us: '🇺🇸', ca: '🇨🇦', ae: '🇦🇪', bg: '🇧🇬',
  // v2.6.23 — flags for the 19 newly-shipped CWICR cost-database regions
  au: '🇦🇺', hr: '🇭🇷', id: '🇮🇩', mx: '🇲🇽', ng: '🇳🇬',
  nz: '🇳🇿', ro: '🇷🇴', th: '🇹🇭', vn: '🇻🇳', za: '🇿🇦',
};

/** Region-key prefixes that don't match an ISO code directly.
 *  Keeps CountryFlag callable with raw region keys ("DE_BERLIN",
 *  "AR_DUBAI", "ENG_TORONTO") without making each call site re-map first.
 *  Mirrors REGION_MAP in useCostDatabaseStore.ts; kept inline so this
 *  shared UI component has no feature-store dependency. */
const REGION_PREFIX_TO_ISO: Record<string, string> = {
  usa: 'us', uk: 'gb', eng: 'ca', sp: 'es', pt: 'br',
  ar: 'ae', zh: 'cn', hi: 'in', cs: 'cz', ja: 'jp',
  ko: 'kr', sv: 'se', vi: 'vn',
};

/** Resolve a 2-letter ISO key from any of: bare ISO code ("de"),
 *  region key with underscore ("DE_BERLIN" → "de"), region key with
 *  non-ISO prefix ("USA_USD" → "us", "ENG_TORONTO" → "ca"). */
function resolveIso(code: string): string | null {
  const lc = code.toLowerCase();
  if (FLAGS[lc] || EMOJI_FALLBACK[lc]) return lc;
  // region-key shape: split on first "_" and try the prefix.
  const underscore = lc.indexOf('_');
  if (underscore > 0) {
    const prefix = lc.slice(0, underscore);
    if (FLAGS[prefix] || EMOJI_FALLBACK[prefix]) return prefix;
    const mapped = REGION_PREFIX_TO_ISO[prefix];
    if (mapped) return mapped;
  }
  // Bare non-ISO prefix (no underscore — e.g. someone passes "USA").
  const mapped = REGION_PREFIX_TO_ISO[lc];
  if (mapped) return mapped;
  return null;
}

interface CountryFlagProps {
  code: string;
  size?: number;
  className?: string;
}

export function CountryFlag({ code, size = 16, className = '' }: CountryFlagProps) {
  const iso = resolveIso(code);
  if (!iso) return null;
  const svg = FLAGS[iso];

  if (!svg) {
    const emoji = EMOJI_FALLBACK[iso];
    if (emoji) {
      return <span className={className} role="img" aria-label={iso} style={{ fontSize: size * 0.7 }}>{emoji}</span>;
    }
    return null;
  }

  const height = Math.round(size * 0.7);
  const encoded = `data:image/svg+xml,${encodeURIComponent(svg)}`;

  return (
    <img
      src={encoded}
      width={size}
      height={height}
      alt=""
      className={`rounded-[2px] shrink-0 ${className}`}
      loading="lazy"
    />
  );
}
