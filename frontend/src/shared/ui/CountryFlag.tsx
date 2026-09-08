// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
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

  // PT — Portugal. Needed the moment pt stopped flying the Brazilian flag,
  // which it did when pt-BR arrived to carry it.
  pt: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 6 4"><rect width="6" height="4" fill="#DA291C"/><rect width="2.4" height="4" fill="#046A38"/><circle cx="2.4" cy="2" r=".78" fill="none" stroke="#FFE900" stroke-width=".26"/><rect x="2.1" y="1.66" width=".6" height=".68" rx=".1" fill="#fff" stroke="#DA291C" stroke-width=".16"/></svg>`,

  // CL — Chile
  cl: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 9 6"><rect width="9" height="6" fill="#fff"/><rect y="3" width="9" height="3" fill="#D52B1E"/><rect width="3" height="3" fill="#0039A6"/><path d="M1.5.65l.2.575.608.012-.485.368.177.583-.5-.348-.5.348.177-.583-.485-.368.608-.012z" fill="#fff"/></svg>`,

  // CO — Colombia
  co: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 6 4"><rect width="6" height="4" fill="#FCD116"/><rect y="2" width="6" height="1" fill="#003893"/><rect y="3" width="6" height="1" fill="#CE1126"/></svg>`,

  // RU — Russia
  ru: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 9 6"><rect width="9" height="2" fill="#fff"/><rect y="2" width="9" height="2" fill="#0039A6"/><rect y="4" width="9" height="2" fill="#D52B1E"/></svg>`,

  // CN — China (large star + 4 smaller stars, all proper 5-point polygons)
  cn: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 20"><rect width="30" height="20" fill="#DE2910"/><defs><polygon id="cn-b" points="0,-3 0.674,-0.927 2.853,-0.927 1.09,0.354 1.763,2.427 0,1.146 -1.763,2.427 -1.09,0.354 -2.853,-0.927 -0.674,-0.927" fill="#FFDE00"/><polygon id="cn-s" points="0,-1 0.225,-0.309 0.951,-0.309 0.363,0.118 0.588,0.809 0,0.382 -0.588,0.809 -0.363,0.118 -0.951,-0.309 -0.225,-0.309" fill="#FFDE00"/></defs><use href="#cn-b" x="5" y="5"/><use href="#cn-s" x="10" y="2"/><use href="#cn-s" x="12" y="4"/><use href="#cn-s" x="12" y="7"/><use href="#cn-s" x="10" y="9"/></svg>`,

  // SA - Saudi Arabia. The inscription is deliberately abstract: an even run
  // of strokes on a common baseline, which is what a line of script resolves
  // to at these sizes. Drawing approximate letterforms would be a wrong
  // rendering of a religious text, which is worse than not rendering it. The
  // sword below is drawn properly and points to the hoist.
  sa: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 20"><rect width="30" height="20" fill="#006C35"/><g fill="#fff"><rect x="5.20" y="6.00" width="0.62" height="2.10" rx="0.3"/><rect x="6.62" y="6.55" width="0.62" height="1.55" rx="0.3"/><rect x="8.04" y="6.00" width="0.62" height="2.10" rx="0.3"/><rect x="9.46" y="6.00" width="0.62" height="2.10" rx="0.3"/><rect x="10.88" y="6.55" width="0.62" height="1.55" rx="0.3"/><rect x="12.30" y="6.00" width="0.62" height="2.10" rx="0.3"/><rect x="13.72" y="6.00" width="0.62" height="2.10" rx="0.3"/><rect x="15.14" y="6.55" width="0.62" height="1.55" rx="0.3"/><rect x="16.56" y="6.00" width="0.62" height="2.10" rx="0.3"/><rect x="17.98" y="6.00" width="0.62" height="2.10" rx="0.3"/><rect x="19.40" y="6.55" width="0.62" height="1.55" rx="0.3"/><rect x="20.82" y="6.00" width="0.62" height="2.10" rx="0.3"/><rect x="22.24" y="6.00" width="0.62" height="2.10" rx="0.3"/><rect x="6.6" y="12.6" width="16.2" height="0.95" rx="0.47"/><path d="M6.6 13.08 3.4 11.3v3.56z"/><rect x="22.2" y="11.5" width="0.85" height="3.15" rx="0.42"/><circle cx="24.4" cy="13.08" r="1.35"/></g></svg>`,

  // IN - India. Twenty four spokes, generated. The previous chakra had four,
  // which reads as a plus sign inside a circle above about 40px.
  in: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 20"><rect width="30" height="6.667" fill="#FF9933"/><rect y="6.667" width="30" height="6.666" fill="#fff"/><rect y="13.333" width="30" height="6.667" fill="#138808"/><circle cx="15" cy="10" r="3" fill="none" stroke="#000080" stroke-width=".42"/><circle cx="15" cy="10" r=".5" fill="#000080"/><g stroke="#000080" stroke-width=".2"><line x1="15.480" y1="10.000" x2="17.760" y2="10.000"/><line x1="15.464" y1="10.124" x2="17.666" y2="10.714"/><line x1="15.416" y1="10.240" x2="17.390" y2="11.380"/><line x1="15.339" y1="10.339" x2="16.952" y2="11.952"/><line x1="15.240" y1="10.416" x2="16.380" y2="12.390"/><line x1="15.124" y1="10.464" x2="15.714" y2="12.666"/><line x1="15.000" y1="10.480" x2="15.000" y2="12.760"/><line x1="14.876" y1="10.464" x2="14.286" y2="12.666"/><line x1="14.760" y1="10.416" x2="13.620" y2="12.390"/><line x1="14.661" y1="10.339" x2="13.048" y2="11.952"/><line x1="14.584" y1="10.240" x2="12.610" y2="11.380"/><line x1="14.536" y1="10.124" x2="12.334" y2="10.714"/><line x1="14.520" y1="10.000" x2="12.240" y2="10.000"/><line x1="14.536" y1="9.876" x2="12.334" y2="9.286"/><line x1="14.584" y1="9.760" x2="12.610" y2="8.620"/><line x1="14.661" y1="9.661" x2="13.048" y2="8.048"/><line x1="14.760" y1="9.584" x2="13.620" y2="7.610"/><line x1="14.876" y1="9.536" x2="14.286" y2="7.334"/><line x1="15.000" y1="9.520" x2="15.000" y2="7.240"/><line x1="15.124" y1="9.536" x2="15.714" y2="7.334"/><line x1="15.240" y1="9.584" x2="16.380" y2="7.610"/><line x1="15.339" y1="9.661" x2="16.952" y2="8.048"/><line x1="15.416" y1="9.760" x2="17.390" y2="8.620"/><line x1="15.464" y1="9.876" x2="17.666" y2="9.286"/></g></svg>`,

  // TR — Turkey (crescent + proper 5-point star)
  tr: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 20"><rect width="30" height="20" fill="#E30A17"/><circle cx="11" cy="10" r="5" fill="#fff"/><circle cx="12.5" cy="10" r="4" fill="#E30A17"/><polygon points="17.3,7.7 17.817,9.289 19.487,9.289 18.136,10.272 18.652,11.861 17.3,10.879 15.948,11.861 16.464,10.272 15.113,9.289 16.783,9.289" fill="#fff"/></svg>`,

  // IT — Italy
  it: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 3 2"><rect width="1" height="2" fill="#009246"/><rect x="1" width="1" height="2" fill="#fff"/><rect x="2" width="1" height="2" fill="#CE2B37"/></svg>`,

  // NL — Netherlands
  nl: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 9 6"><rect width="9" height="2" fill="#AE1C28"/><rect y="2" width="9" height="2" fill="#fff"/><rect y="4" width="9" height="2" fill="#21468B"/></svg>`,

  // PL — Poland
  pl: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 8 5"><rect width="8" height="2.5" fill="#fff"/><rect y="2.5" width="8" height="2.5" fill="#DC143C"/></svg>`,


  // HU - Hungary. Added for the Hungarian pack; nothing in the table flew a
  // flag for it before, so the pack would have fallen back to a monogram.
  hu: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 6 3"><rect width="6" height="1" fill="#CE2939"/><rect y="1" width="6" height="1" fill="#fff"/><rect y="2" width="6" height="1" fill="#477050"/></svg>`,
  // CZ — Czech Republic
  cz: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 6 4"><rect width="6" height="2" fill="#fff"/><rect y="2" width="6" height="2" fill="#D7141A"/><polygon points="0,0 3,2 0,4" fill="#11457E"/></svg>`,

  // JP — Japan
  jp: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 20"><rect width="30" height="20" fill="#fff"/><circle cx="15" cy="10" r="6" fill="#BC002D"/></svg>`,

  // KR - South Korea. Taeguk plus the four trigrams, each rotated to face the
  // centre. Without them the flag was a circle floating on an empty white
  // field, which is not a flag anyone recognises.
  kr: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 36 24"><rect width="36" height="24" fill="#fff"/><circle cx="18" cy="12" r="5" fill="#CD2E3A"/><path d="M13 12a2.5 2.5 0 0 1 5 0 2.5 2.5 0 0 0 5 0 5 5 0 0 1-10 0z" fill="#0047A0"/><g fill="#000"><g transform="translate(8.4 5.6) rotate(56)"><rect x="-2.60" y="-1.82" width="5.20" height="0.85"/><rect x="-2.60" y="-0.42" width="5.20" height="0.85"/><rect x="-2.60" y="0.97" width="5.20" height="0.85"/></g><g transform="translate(27.6 5.6) rotate(-56)"><rect x="-2.60" y="-1.82" width="1.87" height="0.85"/><rect x="0.73" y="-1.82" width="1.87" height="0.85"/><rect x="-2.60" y="-0.42" width="5.20" height="0.85"/><rect x="-2.60" y="0.97" width="1.87" height="0.85"/><rect x="0.73" y="0.97" width="1.87" height="0.85"/></g><g transform="translate(8.4 18.4) rotate(-56)"><rect x="-2.60" y="-1.82" width="5.20" height="0.85"/><rect x="-2.60" y="-0.42" width="1.87" height="0.85"/><rect x="0.73" y="-0.42" width="1.87" height="0.85"/><rect x="-2.60" y="0.97" width="5.20" height="0.85"/></g><g transform="translate(27.6 18.4) rotate(56)"><rect x="-2.60" y="-1.82" width="1.87" height="0.85"/><rect x="0.73" y="-1.82" width="1.87" height="0.85"/><rect x="-2.60" y="-0.42" width="1.87" height="0.85"/><rect x="0.73" y="-0.42" width="1.87" height="0.85"/><rect x="-2.60" y="0.97" width="1.87" height="0.85"/><rect x="0.73" y="0.97" width="1.87" height="0.85"/></g></g></svg>`,

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

  // CA - Canada. Eleven points, generated symmetrically from one half so
  // the leaf cannot come out lopsided. The previous drawing was four small
  // disconnected paths and rendered as a red asterisk at every size.
  ca: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 10"><rect width="5" height="10" fill="#FF0000"/><rect x="5" width="10" height="10" fill="#fff"/><rect x="15" width="5" height="10" fill="#FF0000"/><polygon points="10.00,2.00 10.19,2.88 10.69,2.72 10.54,3.58 11.18,3.39 10.99,4.17 12.15,4.02 11.87,4.77 12.13,5.24 11.29,5.56 11.46,6.16 10.82,5.97 10.95,7.04 10.41,6.54 10.28,8.30 9.72,8.30 9.59,6.54 9.05,7.04 9.18,5.97 8.54,6.16 8.71,5.56 7.87,5.24 8.13,4.77 7.85,4.02 9.01,4.17 8.82,3.39 9.46,3.58 9.31,2.72 9.81,2.88 10.00,2.00" fill="#FF0000"/></svg>`,

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

  // EE — Estonia (blue-black-white horizontal). The Estonian locale shipped
  // with country 'ee' and no entry here, and resolveIso returns null for a
  // code in neither map, so CountryFlag rendered nothing at all: the language
  // switcher showed a name with an empty slot where every other row has a flag.
  ee: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 11 7"><rect width="11" height="2.333" fill="#0072CE"/><rect y="2.333" width="11" height="2.334" fill="#000"/><rect y="4.667" width="11" height="2.333" fill="#fff"/></svg>`,

  // BD — Bangladesh (green field, red disc offset toward the hoist so it
  // appears centred when flying)
  bd: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 18"><rect width="30" height="18" fill="#006A4E"/><circle cx="13.5" cy="9" r="5.4" fill="#F42A41"/></svg>`,

  // CIS — Commonwealth of Independent States (СНГ). Not an ISO country; a
  // provenance badge for the in-house GESN/CWICR post-Soviet norm bases.
  // Blue field + gold sun emblem (CIS colours), distinct from any national flag.
  cis: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 20"><rect width="30" height="20" fill="#2A6CC6"/><g stroke="#F4C430" stroke-width="1.1" stroke-linecap="round"><line x1="15" y1="3.9" x2="15" y2="2.3"/><line x1="15" y1="3.9" x2="15" y2="2.3" transform="rotate(45 15 10)"/><line x1="15" y1="3.9" x2="15" y2="2.3" transform="rotate(90 15 10)"/><line x1="15" y1="3.9" x2="15" y2="2.3" transform="rotate(135 15 10)"/><line x1="15" y1="3.9" x2="15" y2="2.3" transform="rotate(180 15 10)"/><line x1="15" y1="3.9" x2="15" y2="2.3" transform="rotate(225 15 10)"/><line x1="15" y1="3.9" x2="15" y2="2.3" transform="rotate(270 15 10)"/><line x1="15" y1="3.9" x2="15" y2="2.3" transform="rotate(315 15 10)"/></g><circle cx="15" cy="10" r="5" fill="none" stroke="#F4C430" stroke-width="1.2"/><circle cx="15" cy="10" r="1.9" fill="#F4C430"/></svg>`,

  // KG — Kyrgyzstan (red field, yellow sun with rays, red tunduk in the centre)
  kg: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 20"><rect width="30" height="20" fill="#E8112D"/><g stroke="#FFEF00" stroke-width="0.9" stroke-linecap="round"><line x1="15" y1="4" x2="15" y2="2.2"/><line x1="15" y1="4" x2="15" y2="2.2" transform="rotate(30 15 10)"/><line x1="15" y1="4" x2="15" y2="2.2" transform="rotate(60 15 10)"/><line x1="15" y1="4" x2="15" y2="2.2" transform="rotate(90 15 10)"/><line x1="15" y1="4" x2="15" y2="2.2" transform="rotate(120 15 10)"/><line x1="15" y1="4" x2="15" y2="2.2" transform="rotate(150 15 10)"/><line x1="15" y1="4" x2="15" y2="2.2" transform="rotate(180 15 10)"/><line x1="15" y1="4" x2="15" y2="2.2" transform="rotate(210 15 10)"/><line x1="15" y1="4" x2="15" y2="2.2" transform="rotate(240 15 10)"/><line x1="15" y1="4" x2="15" y2="2.2" transform="rotate(270 15 10)"/><line x1="15" y1="4" x2="15" y2="2.2" transform="rotate(300 15 10)"/><line x1="15" y1="4" x2="15" y2="2.2" transform="rotate(330 15 10)"/></g><circle cx="15" cy="10" r="3.6" fill="#FFEF00"/><g fill="none" stroke="#E8112D" stroke-width="0.45"><circle cx="15" cy="10" r="2.2"/><path d="M13 10 H17 M15 8 V12 M13.4 8.4 L16.6 11.6 M16.6 8.4 L13.4 11.6"/></g></svg>`,

  // KZ — Kazakhstan (sky-blue field, 32-ray gold sun, gold ornament near the hoist)
  kz: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 20"><rect width="30" height="20" fill="#00AFCA"/><g stroke="#FEC50C" stroke-width="0.6" stroke-linecap="round"><line x1="15" y1="4.5" x2="15" y2="2.6"/><line x1="15" y1="4.5" x2="15" y2="2.6" transform="rotate(22.5 15 10)"/><line x1="15" y1="4.5" x2="15" y2="2.6" transform="rotate(45 15 10)"/><line x1="15" y1="4.5" x2="15" y2="2.6" transform="rotate(67.5 15 10)"/><line x1="15" y1="4.5" x2="15" y2="2.6" transform="rotate(90 15 10)"/><line x1="15" y1="4.5" x2="15" y2="2.6" transform="rotate(112.5 15 10)"/><line x1="15" y1="4.5" x2="15" y2="2.6" transform="rotate(135 15 10)"/><line x1="15" y1="4.5" x2="15" y2="2.6" transform="rotate(157.5 15 10)"/><line x1="15" y1="4.5" x2="15" y2="2.6" transform="rotate(180 15 10)"/><line x1="15" y1="4.5" x2="15" y2="2.6" transform="rotate(202.5 15 10)"/><line x1="15" y1="4.5" x2="15" y2="2.6" transform="rotate(225 15 10)"/><line x1="15" y1="4.5" x2="15" y2="2.6" transform="rotate(247.5 15 10)"/><line x1="15" y1="4.5" x2="15" y2="2.6" transform="rotate(270 15 10)"/><line x1="15" y1="4.5" x2="15" y2="2.6" transform="rotate(292.5 15 10)"/><line x1="15" y1="4.5" x2="15" y2="2.6" transform="rotate(315 15 10)"/><line x1="15" y1="4.5" x2="15" y2="2.6" transform="rotate(337.5 15 10)"/></g><circle cx="15" cy="10" r="3.4" fill="#FEC50C"/><rect x="1.5" y="1.5" width="1.4" height="17" fill="#FEC50C"/></svg>`,

  // PH — Philippines (blue over red field, white hoist triangle with an
  // 8-ray gold sun and three gold stars at the triangle's points)
  ph: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 20"><rect width="30" height="10" fill="#0038A8"/><rect y="10" width="30" height="10" fill="#CE1126"/><polygon points="0,0 0,20 11,10" fill="#FFFFFF"/><g stroke="#FCD116" stroke-width="0.5" stroke-linecap="round"><line x1="4" y1="7.8" x2="4" y2="6.2" transform="rotate(0 4 10)"/><line x1="4" y1="7.8" x2="4" y2="6.2" transform="rotate(45 4 10)"/><line x1="4" y1="7.8" x2="4" y2="6.2" transform="rotate(90 4 10)"/><line x1="4" y1="7.8" x2="4" y2="6.2" transform="rotate(135 4 10)"/><line x1="4" y1="7.8" x2="4" y2="6.2" transform="rotate(180 4 10)"/><line x1="4" y1="7.8" x2="4" y2="6.2" transform="rotate(225 4 10)"/><line x1="4" y1="7.8" x2="4" y2="6.2" transform="rotate(270 4 10)"/><line x1="4" y1="7.8" x2="4" y2="6.2" transform="rotate(315 4 10)"/></g><circle cx="4" cy="10" r="1.7" fill="#FCD116"/><circle cx="1.3" cy="1.3" r="0.9" fill="#FCD116"/><circle cx="1.3" cy="18.7" r="0.9" fill="#FCD116"/><circle cx="9.2" cy="10" r="0.9" fill="#FCD116"/></svg>`,

  // PK — Pakistan (dark green field with white crescent + 5-point star,
  // white vertical hoist stripe 1/4 of the width)
  pk: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 20"><rect width="30" height="20" fill="#01411C"/><rect width="7.5" height="20" fill="#fff"/><circle cx="18.5" cy="10" r="5.4" fill="#fff"/><circle cx="20" cy="10" r="4.4" fill="#01411C"/><polygon points="22.3,7.3 22.79,8.82 24.39,8.82 23.1,9.76 23.59,11.28 22.3,10.34 21.01,11.28 21.5,9.76 20.21,8.82 21.81,8.82" fill="#fff"/></svg>`,

  // IR — Iran (green/white/red horizontal bands with a stylized red
  // emblem centered on the white band)
  ir: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 20"><rect width="30" height="6.67" fill="#239F40"/><rect y="6.67" width="30" height="6.66" fill="#fff"/><rect y="13.33" width="30" height="6.67" fill="#DA0000"/><g fill="#DA0000"><circle cx="15" cy="10" r="1.6"/><path d="M15 6.8 q1.6 1.6 0 3.2 q-1.6 -1.6 0 -3.2z"/><path d="M15 13.2 q1.6 -1.6 0 -3.2 q-1.6 1.6 0 3.2z"/><path d="M11.8 10 q1.6 1.6 3.2 0 q-1.6 -1.6 -3.2 0z"/><path d="M18.2 10 q-1.6 1.6 -3.2 0 q1.6 -1.6 3.2 0z"/></g></svg>`,

  // IL — Israel (white field, blue horizontal stripes near top/bottom,
  // blue Star of David centered)
  il: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 20"><rect width="30" height="20" fill="#fff"/><rect y="2.2" width="30" height="2.4" fill="#0038b8"/><rect y="15.4" width="30" height="2.4" fill="#0038b8"/><g fill="none" stroke="#0038b8" stroke-width="0.7"><polygon points="15,6 11.5,12.5 18.5,12.5"/><polygon points="15,15 11.5,8.5 18.5,8.5"/></g></svg>`,
  ua: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 20"><rect width="30" height="10" fill="#0057B7"/><rect y="10" width="30" height="10" fill="#FFD700"/></svg>`,
  // The twelve stars are drawn as dots in three rows of three, four and five.
  // At thirty by twenty a five-pointed star is a smudge, and the count is the
  // part a reader can actually recognise.
  uz: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 20"><rect width="30" height="6.8" fill="#0099B5"/><rect y="6.4" width="30" height="6.8" fill="#CE1126"/><rect y="6.8" width="30" height="6" fill="#fff"/><rect y="13.2" width="30" height="6.8" fill="#CE1126"/><rect y="13.6" width="30" height="6.4" fill="#1EB53A"/><g fill="#fff"><circle cx="4" cy="3.2" r="2"/><circle cx="10.4" cy="1.7" r="0.38"/><circle cx="11.8" cy="1.7" r="0.38"/><circle cx="13.2" cy="1.7" r="0.38"/><circle cx="9" cy="3.2" r="0.38"/><circle cx="10.4" cy="3.2" r="0.38"/><circle cx="11.8" cy="3.2" r="0.38"/><circle cx="13.2" cy="3.2" r="0.38"/><circle cx="7.6" cy="4.7" r="0.38"/><circle cx="9" cy="4.7" r="0.38"/><circle cx="10.4" cy="4.7" r="0.38"/><circle cx="11.8" cy="4.7" r="0.38"/><circle cx="13.2" cy="4.7" r="0.38"/></g><circle cx="4.8" cy="3.2" r="1.7" fill="#0099B5"/></svg>`,

  // XX - no country. `xx` is this codebase's existing code for something not
  // tied to a market (`shared/lib/regionalPack.ts`,
  // `features/onboarding/countryOffer.ts`), and the language picker needs a
  // glyph for it: plain `English` names no region, with `English (UK)` and
  // `English (US)` under it, so it must not fly either one's flag. Leaving it
  // unresolved was not an option - `resolveIso` answers null for an unknown
  // code and the component renders nothing, which is the empty slot the test
  // beside this file exists to catch. A globe rather than a national flag,
  // because the absence of a country is what the entry means.
  xx: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 20"><rect width="30" height="20" fill="#E2E8F0"/><g transform="translate(15 10)"><circle r="7.2" fill="#64748B"/><g fill="none" stroke="#F8FAFC" stroke-width="0.85"><circle r="7.2"/><ellipse rx="3.1" ry="7.2"/><path d="M-7.2 0h14.4M-6.1-3.7h12.2M-6.1 3.7h12.2"/></g></g></svg>`,
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
  // Kyrgyz locale (12.2.0)
  kg: '🇰🇬',
  // Estonian locale (has an SVG above; fallback only)
  ee: '🇪🇪',
  // Bengali locale (has an SVG above; fallback only)
  bd: '🇧🇩',
  // Kazakh locale (has an SVG above; fallback only)
  kz: '🇰🇿',
  // Filipino locale (has an SVG above; fallback only)
  ph: '🇵🇭',
  // Urdu locale (has an SVG above; fallback only)
  pk: '🇵🇰',
  // Persian/Farsi locale (has an SVG above; fallback only)
  ir: '🇮🇷',
  // Hebrew locale (has an SVG above; fallback only)
  il: '🇮🇱',
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
