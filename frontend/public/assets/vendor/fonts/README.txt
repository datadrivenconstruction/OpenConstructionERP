Self-hosted web fonts for the application shell.

frontend/index.html used to preconnect to the two Google Fonts origins and
pull one stylesheet plus up to eight font files from them on every app load.
The files here are what Google was serving: each was downloaded from the URL
Google's own stylesheet named, with the User-Agent Chrome sends, so the woff2
variant is the one a current browser would have received.

Those two host names are deliberately not spelled out anywhere under this
directory. Acceptance for this change is a plain substring search for them
across the built dist, and this directory is copied into dist verbatim, so a
comment naming them would fail that search on a perfectly healthy tree. A
check that goes red on a correct state is worse than no check, because the
next person learns to ignore it. To reproduce the download, ask the Google
Fonts CSS API for the two families with a current browser User-Agent and
fetch every URL the stylesheet it returns names.

fonts.css carries the same families, subsets, weights, unicode-ranges and
font-display values as the stylesheet it replaces, with one deliberate
exception described below. The rendered result is unchanged and only the
origin moves. Self-hosting also means the desktop build renders correctly
with no network at all, and workbox precaches the files because woff2 is
already in the globPatterns in vite.config.ts.


WHERE THEY ARE USED

Neither family is the app-wide body font. --oe-font-sans in src/index.css is
a system stack and does not name either of them. Plus Jakarta Sans is applied
by LoginPage, LoginPageNext, Logo and CustomBranding; Instrument Serif is the
display headline on LoginPageNext only.


THE "CYRILLIC-EXT" FACE

Google's stylesheet declares a Plus Jakarta Sans face labelled cyrillic-ext
over U+0460-052F, U+1C80-1C8A, U+20B4, U+2DE0-2DFF, U+A640-A69F, U+FE2E-FE2F.
The file behind that declaration is 1716 bytes and holds seven codepoints:

  U+000D  U+0020  U+0041  U+00A0  U+00C1  U+0102  U+20B4

That is the hryvnia sign plus subsetter filler. There is not one Cyrillic
letter in it, and none of the other subsets carry Cyrillic either. Google
emits the face because the hryvnia sign happens to fall inside the range that
names the subset, not because the typeface supports the script.

A unicode-range is what the browser uses to decide whether to fetch a face.
So a Kazakh string containing any of Ә Ғ Қ Ң Ө Ұ Ү Һ, all of which sit in
U+0460-052F, made the browser download a font that cannot draw a single one
of them; the letters then fell through to the system stack anyway. Measured
over frontend/src/app/locales, that mis-declared range covers 51.5% of Kazakh
words, 24.3% of Mongolian and 20.7% of Kyrgyz, against 0.0% of Russian and
Bulgarian, which have no letters in the extended block and are the controls
that make those numbers readable.

The face is kept here, because UAH is a currency the app supports and the
glyph is genuinely present, but it is declared over U+20B4 alone. No Cyrillic
letter can select it, so no locale fetches a face that renders none of its
script. Do not widen this range back to the subset Google names.

To re-measure, from the repo root:

  python scripts/font_coverage_probe.py \
      --css frontend/public/assets/vendor/fonts/fonts.css \
      --fonts frontend/public/assets/vendor/fonts/webfonts \
      --locales frontend/src/app/locales

It needs fonttools and brotli, which is why it is a script you run and not a
CI gate. Point --css at a stylesheet fetched from Google to see the before.


LICENCES

Both families are licensed under the SIL Open Font License 1.1. The licence
text for each is in licenses/, taken from the google/fonts repository that
serves them.

  Plus Jakarta Sans  (c) 2020 The Plus Jakarta Sans Project Authors
  Instrument Serif   (c) 2022 The Instrument Serif Project Authors


UI FONTS FOR THE APPEARANCE STYLES

inter.css, ibm-plex-sans.css and source-sans-3.css are the optional body
fonts offered under Settings > General > Style. None is linked by default:
the boot script in index.html and src/shared/lib/appearance.ts add the one
stylesheet only after a user (or the workspace default) picks that font, so
the default system stack downloads nothing.

Each is the upright variable-weight build from the matching
@fontsource-variable package (inter 5.3.0, ibm-plex-sans 5.3.0,
source-sans-3 5.3.1), copied here rather than installed as a dependency so
the core stays offline-capable and the bundle does not grow. Subsets:
latin, latin-ext, cyrillic, cyrillic-ext (Plex has none), greek, greek-ext
(Plex has none) and vietnamese, each behind its own unicode-range, so a
reader only fetches the scripts on screen. Arabic, Hebrew, CJK, Devanagari,
Bengali and Thai are deliberately not covered and fall through to the
system stack declared after the family in src/index.css. Licences: SIL OFL
1.1, in licenses/.
