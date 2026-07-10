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

  // CN — China (large star + 4 smaller stars, all proper 5-point polygons)
  cn: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 20"><rect width="30" height="20" fill="#DE2910"/><defs><polygon id="cn-b" points="0,-3 0.674,-0.927 2.853,-0.927 1.09,0.354 1.763,2.427 0,1.146 -1.763,2.427 -1.09,0.354 -2.853,-0.927 -0.674,-0.927" fill="#FFDE00"/><polygon id="cn-s" points="0,-1 0.225,-0.309 0.951,-0.309 0.363,0.118 0.588,0.809 0,0.382 -0.588,0.809 -0.363,0.118 -0.951,-0.309 -0.225,-0.309" fill="#FFDE00"/></defs><use href="#cn-b" x="5" y="5"/><use href="#cn-s" x="10" y="2"/><use href="#cn-s" x="12" y="4"/><use href="#cn-s" x="12" y="7"/><use href="#cn-s" x="10" y="9"/></svg>`,

  // SA — Saudi Arabia (green field, stylized white shahada script + sword)
  sa: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 20"><rect width="30" height="20" fill="#006C35"/><g fill="none" stroke="#fff" stroke-width="0.8" stroke-linecap="round"><path d="M5 8 q2 -2 4 0 t4 0 t4 0 t4 0 t4 0"/><path d="M7 6.5 v1.6 M11 6.2 v1.9 M15 6.5 v1.6 M19 6.2 v1.9 M23 6.5 v1.6"/></g><g fill="#fff"><rect x="5" y="12.2" width="18" height="1.1" rx="0.5"/><path d="M5 12.75 l-2.4 -1.3 v2.6 z"/><circle cx="24" cy="12.75" r="1.3"/></g></svg>`,

  // IN — India
  in: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 6 4"><rect width="6" height="1.33" fill="#FF9933"/><rect y="1.33" width="6" height="1.34" fill="#fff"/><rect y="2.67" width="6" height="1.33" fill="#138808"/><circle cx="3" cy="2" r=".5" fill="none" stroke="#000080" stroke-width=".1"/><circle cx="3" cy="2" r=".07" fill="#000080"/><g stroke="#000080" stroke-width=".045"><line x1="3" y1="1.5" x2="3" y2="2.5"/><line x1="2.5" y1="2" x2="3.5" y2="2"/><line x1="2.65" y1="1.65" x2="3.35" y2="2.35"/><line x1="3.35" y1="1.65" x2="2.65" y2="2.35"/></g></svg>`,

  // TR — Turkey (crescent + proper 5-point star)
  tr: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 20"><rect width="30" height="20" fill="#E30A17"/><circle cx="11" cy="10" r="5" fill="#fff"/><circle cx="12.5" cy="10" r="4" fill="#E30A17"/><polygon points="17.3,7.7 17.817,9.289 19.487,9.289 18.136,10.272 18.652,11.861 17.3,10.879 15.948,11.861 16.464,10.272 15.113,9.289 16.783,9.289" fill="#fff"/></svg>`,

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

  // GR — Greece (9 blue-white stripes + white cross on blue canton)
  gr: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 27 18"><rect width="27" height="18" fill="#0D5EAF"/><g fill="#fff"><rect y="2" width="27" height="2"/><rect y="6" width="27" height="2"/><rect y="10" width="27" height="2"/><rect y="14" width="27" height="2"/></g><rect width="10" height="10" fill="#0D5EAF"/><rect x="4" width="2" height="10" fill="#fff"/><rect y="4" width="10" height="2" fill="#fff"/></svg>`,

  // US — United States (proper white star polygons, not font glyphs which
  // render as empty boxes inside an <img> data-URI without a guaranteed font)
  us: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 19 10"><defs><polygon id="us-s" points="0,-0.32 0.072,-0.099 0.304,-0.099 0.116,0.038 0.188,0.259 0,0.122 -0.188,0.259 -0.116,0.038 -0.304,-0.099 -0.072,-0.099" fill="#fff"/></defs><rect width="19" height="10" fill="#B22234"/><g fill="#fff"><rect y=".77" width="19" height=".77"/><rect y="2.31" width="19" height=".77"/><rect y="3.85" width="19" height=".77"/><rect y="5.38" width="19" height=".77"/><rect y="6.92" width="19" height=".77"/><rect y="8.46" width="19" height=".77"/></g><rect width="7.6" height="5.38" fill="#3C3B6E"/><g><use href="#us-s" x="0.76" y="0.7"/><use href="#us-s" x="2.28" y="0.7"/><use href="#us-s" x="3.8" y="0.7"/><use href="#us-s" x="5.32" y="0.7"/><use href="#us-s" x="6.84" y="0.7"/><use href="#us-s" x="1.52" y="1.6"/><use href="#us-s" x="3.04" y="1.6"/><use href="#us-s" x="4.56" y="1.6"/><use href="#us-s" x="6.08" y="1.6"/><use href="#us-s" x="0.76" y="2.5"/><use href="#us-s" x="2.28" y="2.5"/><use href="#us-s" x="3.8" y="2.5"/><use href="#us-s" x="5.32" y="2.5"/><use href="#us-s" x="6.84" y="2.5"/><use href="#us-s" x="1.52" y="3.4"/><use href="#us-s" x="3.04" y="3.4"/><use href="#us-s" x="4.56" y="3.4"/><use href="#us-s" x="6.08" y="3.4"/><use href="#us-s" x="0.76" y="4.3"/><use href="#us-s" x="2.28" y="4.3"/><use href="#us-s" x="3.8" y="4.3"/><use href="#us-s" x="5.32" y="4.3"/><use href="#us-s" x="6.84" y="4.3"/></g></svg>`,

  // CA — Canada
  ca: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 10"><rect width="5" height="10" fill="#FF0000"/><rect x="5" width="10" height="10" fill="#fff"/><rect x="15" width="5" height="10" fill="#FF0000"/><path d="M10 2l.5 1.5H9.5L10 2zm-1.5 2l1.5.5-1 1.5H8l.5-2zm3 0L10 4.5l1 1.5h1l-.5-2zM10 7l-.5-1.5h1L10 7z" fill="#FF0000"/></svg>`,

  // AE — UAE
  ae: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 12 6"><rect y="0" width="12" height="2" fill="#00732F"/><rect y="2" width="12" height="2" fill="#fff"/><rect y="4" width="12" height="2" fill="#000"/><rect width="3" height="6" fill="#FF0000"/></svg>`,

  // ── Inline SVG flags for the 10 CWICR regions whose emoji fallback
  //    is broken on Windows. Win10/Win11 have no native flag-emoji
  //    glyphs in any system font, so the regional-indicator codepoints
  //    render as literal "AU"/"NZ"/etc. text. Real SVGs guarantee a
  //    visible flag on every platform. Designs are simplified but
  //    recognisable at 14–32 px sizes.

  // AU — Australia (blue with Union Jack canton + 7-pt Commonwealth Star
  // + Southern Cross approximation)
  au: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 60 30"><rect width="60" height="30" fill="#012169"/><clipPath id="auc"><rect width="30" height="15"/></clipPath><g clip-path="url(#auc)"><path d="M0,0 L30,15 M30,0 L0,15" stroke="#fff" stroke-width="3"/><path d="M0,0 L30,15 M30,0 L0,15" stroke="#C8102E" stroke-width="1.6"/><path d="M15,0 V15 M0,7.5 H30" stroke="#fff" stroke-width="5"/><path d="M15,0 V15 M0,7.5 H30" stroke="#C8102E" stroke-width="3"/></g><polygon points="15,20.5 15.9,23.2 18.7,23.2 16.4,24.9 17.3,27.6 15,25.9 12.7,27.6 13.6,24.9 11.3,23.2 14.1,23.2" fill="#fff"/><circle cx="44" cy="7" r="1" fill="#fff"/><circle cx="51" cy="12" r="1" fill="#fff"/><circle cx="44" cy="18" r="1.1" fill="#fff"/><circle cx="48" cy="23" r="1" fill="#fff"/><circle cx="38" cy="15" r=".8" fill="#fff"/></svg>`,

  // NZ — New Zealand (blue with Union Jack canton + 4 Southern Cross stars)
  nz: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 60 30"><rect width="60" height="30" fill="#00247D"/><clipPath id="nzc"><rect width="30" height="15"/></clipPath><g clip-path="url(#nzc)"><path d="M0,0 L30,15 M30,0 L0,15" stroke="#fff" stroke-width="3"/><path d="M0,0 L30,15 M30,0 L0,15" stroke="#CC142B" stroke-width="1.6"/><path d="M15,0 V15 M0,7.5 H30" stroke="#fff" stroke-width="5"/><path d="M15,0 V15 M0,7.5 H30" stroke="#CC142B" stroke-width="3"/></g><circle cx="46" cy="8" r="1.5" fill="#fff"/><circle cx="46" cy="8" r="1" fill="#CC142B"/><circle cx="52" cy="14" r="1.5" fill="#fff"/><circle cx="52" cy="14" r="1" fill="#CC142B"/><circle cx="47" cy="23" r="1.5" fill="#fff"/><circle cx="47" cy="23" r="1" fill="#CC142B"/><circle cx="41" cy="19" r="1.3" fill="#fff"/><circle cx="41" cy="19" r=".85" fill="#CC142B"/></svg>`,

  // HR — Croatia (red-white-blue horizontal + simplified shield)
  hr: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 15"><rect width="30" height="5" fill="#FF0000"/><rect y="5" width="30" height="5" fill="#fff"/><rect y="10" width="30" height="5" fill="#171796"/><g transform="translate(13.5, 5.5)"><rect width="3" height="3" fill="#fff" stroke="#171796" stroke-width=".15"/><rect width=".75" height=".75" fill="#FF0000"/><rect x="1.5" width=".75" height=".75" fill="#FF0000"/><rect y="1.5" width=".75" height=".75" fill="#FF0000"/><rect x="1.5" y="1.5" width=".75" height=".75" fill="#FF0000"/><rect x=".75" y=".75" width=".75" height=".75" fill="#FF0000"/><rect x="2.25" y=".75" width=".75" height=".75" fill="#FF0000"/><rect x=".75" y="2.25" width=".75" height=".75" fill="#FF0000"/><rect x="2.25" y="2.25" width=".75" height=".75" fill="#FF0000"/></g></svg>`,

  // RO — Romania (blue-yellow-red vertical)
  ro: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 3 2"><rect width="1" height="2" fill="#002B7F"/><rect x="1" width="1" height="2" fill="#FCD116"/><rect x="2" width="1" height="2" fill="#CE1126"/></svg>`,

  // TH — Thailand (5 horizontal stripes red-white-blue-white-red)
  th: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 20"><rect width="30" height="20" fill="#A51931"/><rect y="3.33" width="30" height="13.33" fill="#F4F5F8"/><rect y="6.66" width="30" height="6.66" fill="#2D2A4A"/></svg>`,

  // VN — Vietnam (red with yellow 5-point star)
  vn: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 20"><rect width="30" height="20" fill="#DA251D"/><polygon points="15,5 16.76,10.4 22.41,10.4 17.83,13.7 19.59,19.1 15,15.8 10.41,19.1 12.17,13.7 7.59,10.4 13.24,10.4" fill="#FF0"/></svg>`,

  // ID — Indonesia (red top, white bottom)
  id: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 3 2"><rect width="3" height="1" fill="#FF0000"/><rect y="1" width="3" height="1" fill="#fff"/></svg>`,

  // MX — Mexico (green-white-red vertical)
  mx: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 7 4"><rect width="7" height="4" fill="#fff"/><rect width="2.33" height="4" fill="#006847"/><rect x="4.67" width="2.33" height="4" fill="#CE1126"/><circle cx="3.5" cy="2" r=".5" fill="none" stroke="#7B3F00" stroke-width=".15"/><circle cx="3.5" cy="2" r=".15" fill="#7B3F00"/></svg>`,

  // ZA — South Africa (green pall/Y with white + gold fimbriation, black hoist
  // triangle, red top + blue bottom on the fly)
  za: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 20"><rect width="30" height="10" fill="#E03C31"/><rect y="10" width="30" height="10" fill="#001489"/><path d="M0,0 L0,4 L7,10 L0,16 L0,20 L3,20 L13,12 H30 V8 H13 L3,0 Z" fill="#fff"/><path d="M0,1.6 L0,3.2 L8.7,10 L0,16.8 L0,18.4 L2.4,18.4 L12,11.2 H30 V8.8 H12 L2.4,1.6 Z" fill="#007749"/><path d="M0,-1 L12,10 L0,21 Z" fill="#FFB81C"/><path d="M0,1.6 L9,10 L0,18.4 Z" fill="#000"/></svg>`,

  // NG — Nigeria (green-white-green vertical)
  ng: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 6 3"><rect width="2" height="3" fill="#008753"/><rect x="2" width="2" height="3" fill="#fff"/><rect x="4" width="2" height="3" fill="#008753"/></svg>`,

  // MN — Mongolia (red-blue-red vertical + simplified soyombo on hoist red)
  mn: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 9 6"><rect width="3" height="6" fill="#C4272F"/><rect x="3" width="3" height="6" fill="#015197"/><rect x="6" width="3" height="6" fill="#C4272F"/><g fill="#F9CF02" transform="translate(1.5,3)"><circle r=".25"/><rect x="-.55" y="-1.4" width=".3" height="1" rx=".05"/><rect x=".25" y="-1.4" width=".3" height="1" rx=".05"/><rect x="-.55" y=".4" width=".3" height="1" rx=".05"/><rect x=".25" y=".4" width=".3" height="1" rx=".05"/><rect x="-1.05" y="-.15" width=".25" height=".3" rx=".05"/><rect x=".8" y="-.15" width=".25" height=".3" rx=".05"/></g></svg>`,

  // CIS — Commonwealth of Independent States (СНГ). Not an ISO country; a
  // provenance badge for the in-house GESN/CWICR post-Soviet norm bases.
  // Blue field + gold sun emblem (CIS colours), distinct from any national flag.
  cis: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 20"><rect width="30" height="20" fill="#2A6CC6"/><g stroke="#F4C430" stroke-width="1.1" stroke-linecap="round"><line x1="15" y1="3.9" x2="15" y2="2.3"/><line x1="15" y1="3.9" x2="15" y2="2.3" transform="rotate(45 15 10)"/><line x1="15" y1="3.9" x2="15" y2="2.3" transform="rotate(90 15 10)"/><line x1="15" y1="3.9" x2="15" y2="2.3" transform="rotate(135 15 10)"/><line x1="15" y1="3.9" x2="15" y2="2.3" transform="rotate(180 15 10)"/><line x1="15" y1="3.9" x2="15" y2="2.3" transform="rotate(225 15 10)"/><line x1="15" y1="3.9" x2="15" y2="2.3" transform="rotate(270 15 10)"/><line x1="15" y1="3.9" x2="15" y2="2.3" transform="rotate(315 15 10)"/></g><circle cx="15" cy="10" r="5" fill="none" stroke="#F4C430" stroke-width="1.2"/><circle cx="15" cy="10" r="1.9" fill="#F4C430"/></svg>`,
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
  us: '🇺🇸', ca: '🇨🇦', ae: '🇦🇪', bg: '🇧🇬', gr: '🇬🇷',
  // v2.6.23 — flags for the 19 newly-shipped CWICR cost-database regions
  au: '🇦🇺', hr: '🇭🇷', id: '🇮🇩', mx: '🇲🇽', ng: '🇳🇬',
  nz: '🇳🇿', ro: '🇷🇴', th: '🇹🇭', vn: '🇻🇳', za: '🇿🇦',
  // v3.0.4 — Mongolian locale (community contribution; PR #125)
  mn: '🇲🇳',
  // CIS provenance badge (has an SVG above; fallback only)
  cis: '🤝',
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

/** ISO codes of CIS (Commonwealth of Independent States / СНГ) members. The
 *  in-house GESN/CWICR cost bases share the post-Soviet norm lineage, so the
 *  cost-database pickers badge them with the shared CIS emblem rather than a
 *  single national flag. This is provenance, not geography — it is applied
 *  only by callers that opt in via `originFlagCode`, and never changes the
 *  plain national flag anywhere else. */
export const CIS_ISO = new Set(['ru', 'by', 'kz', 'kg', 'tj', 'am', 'az', 'uz', 'md']);

/** Map a region's country ISO to the flag code to show in a cost-base
 *  selector: the CIS emblem for post-Soviet norm bases, otherwise the ISO
 *  itself (which `CountryFlag` resolves to the national flag). */
export function originFlagCode(code: string): string {
  return CIS_ISO.has((code || '').toLowerCase()) ? 'cis' : code;
}
