// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Validation for the `autocomplete` attribute value.
 *
 * Why this exists rather than trusting the string a caller wrote. The HTML
 * spec defines a small closed grammar for this attribute, and a browser that
 * cannot parse the value does not ignore the attribute, it treats the field as
 * `on` and falls back to exactly the heuristics the attribute was written to
 * suppress. So a typo here is worse than writing nothing: it reads as a fix in
 * review and behaves as the bug in the browser.
 *
 * The trap that motivated this. `section-name` looks like the obvious value for
 * a field holding the name of a BOQ section, and `section-*` really is part of
 * the grammar, but it is a PREFIX that groups fields into a named form section.
 * On its own it names a group and no field, so the value is malformed and the
 * browser discards it. Issue #407 was a saved credit card being offered over a
 * chapter name; a value like that would have left it offering the card.
 *
 * @see https://html.spec.whatwg.org/multipage/form-control-infrastructure.html#autofill
 */

/** Field names that may appear last in an autofill detail token list. */
const FIELD_NAMES = new Set([
  'name',
  'honorific-prefix',
  'given-name',
  'additional-name',
  'family-name',
  'honorific-suffix',
  'nickname',
  'username',
  'new-password',
  'current-password',
  'one-time-code',
  'organization-title',
  'organization',
  'street-address',
  'address-line1',
  'address-line2',
  'address-line3',
  'address-level4',
  'address-level3',
  'address-level2',
  'address-level1',
  'country',
  'country-name',
  'postal-code',
  'cc-name',
  'cc-given-name',
  'cc-additional-name',
  'cc-family-name',
  'cc-number',
  'cc-exp',
  'cc-exp-month',
  'cc-exp-year',
  'cc-csc',
  'cc-type',
  'transaction-currency',
  'transaction-amount',
  'language',
  'bday',
  'bday-day',
  'bday-month',
  'bday-year',
  'sex',
  'url',
  'photo',
]);

/**
 * Field names that accept a contact-kind qualifier (`home`, `work`, ...).
 * Splitting these out is what makes `work email` valid and `work country`
 * invalid, which a flat allowlist of words cannot express.
 */
const CONTACT_FIELD_NAMES = new Set([
  'tel',
  'tel-country-code',
  'tel-national',
  'tel-area-code',
  'tel-local',
  'tel-local-prefix',
  'tel-local-suffix',
  'tel-extension',
  'email',
  'impp',
]);

const ADDRESS_KINDS = new Set(['shipping', 'billing']);
const CONTACT_KINDS = new Set(['home', 'work', 'mobile', 'fax', 'pager']);

/** Every field name the grammar accepts, contact or not. */
export const AUTOCOMPLETE_FIELD_NAMES: readonly string[] = [
  ...FIELD_NAMES,
  ...CONTACT_FIELD_NAMES,
].sort();

/**
 * True when `value` is something a browser will actually parse.
 *
 * Accepts `on`, `off`, and the detail-token grammar: an optional `section-*`
 * prefix, an optional `shipping`/`billing`, an optional contact kind, the field
 * name, and an optional trailing `webauthn`.
 */
export function isValidAutocomplete(value: string): boolean {
  const tokens = value.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (tokens.length === 0) return false;

  if (tokens.length === 1 && (tokens[0] === 'on' || tokens[0] === 'off')) {
    return true;
  }
  // `on` and `off` are only meaningful alone; combined with anything else the
  // whole value is malformed.
  if (tokens.includes('on') || tokens.includes('off')) return false;

  let i = 0;
  // Optional section grouping. `section-` with nothing after the hyphen names
  // no section and is malformed.
  const first = tokens[i];
  if (first !== undefined && first.startsWith('section-')) {
    if (first.length === 'section-'.length) return false;
    i += 1;
  }
  if (tokens[i] !== undefined && ADDRESS_KINDS.has(tokens[i] as string)) i += 1;

  let contactKindSeen = false;
  if (tokens[i] !== undefined && CONTACT_KINDS.has(tokens[i] as string)) {
    contactKindSeen = true;
    i += 1;
  }

  const field = tokens[i];
  if (field === undefined) return false; // a prefix and no field: the #407 trap
  if (contactKindSeen) {
    if (!CONTACT_FIELD_NAMES.has(field)) return false;
  } else if (!FIELD_NAMES.has(field) && !CONTACT_FIELD_NAMES.has(field)) {
    return false;
  }
  i += 1;

  if (tokens[i] === 'webauthn') i += 1;

  return i === tokens.length;
}

/**
 * The default for a field that is nobody's name, address or card.
 *
 * `off` alone is not a guarantee. Browsers routinely override it on a field
 * their heuristics have decided is a payment or address field, which is what
 * #407 hit. What actually settles it is identifying the field: a stable `name`
 * and `id` plus an accessible name, which `Input` now supplies. Treat this
 * constant as one half of that pair, never as the whole fix.
 */
export const AUTOCOMPLETE_OFF = 'off';
