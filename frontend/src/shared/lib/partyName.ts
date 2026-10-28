// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Decide what a person column says, from the pair the API sends.
 *
 * Person columns across the product are free text, and three things
 * legitimately land in them: a name somebody typed, a contact id, and a user
 * id. Seeders and field integrations write ids, on-screen pickers write ids,
 * and a screen that prints the column as it stands shows
 * "3f2b8c1e-9a44-..." where a name belongs. The API resolves what it can and
 * sends a `<field>_name` beside the raw value; this module turns that pair
 * into the one of three things a reader can be told.
 *
 * The three states matter and must not be collapsed into two. An id that
 * resolved to nothing is NOT nobody: the record has an owner we merely cannot
 * name, and telling a site manager it is unassigned invites a second
 * assignment. Callers print the unresolved state as unknown, never as empty.
 *
 * This started inside the punch list, the one register somebody had thought
 * about, and every other screen printing the same kind of column had no rule
 * at all. A rule written once per caller is only ever tested at the caller
 * that was already right, so it lives here.
 */

/** What a stored id looks like, so a typed-in name is never mistaken for one. */
const PARTY_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export type PartyName =
  /** Nobody is named on the record. */
  | { kind: 'none' }
  /** Someone is named, and this is their name. */
  | { kind: 'named'; name: string }
  /** An id is stored that neither a contact nor a user answers to. */
  | { kind: 'unresolved' };

/**
 * Decide what a person field says.
 *
 * @param raw - The stored column value: a name, an id, or nothing.
 * @param resolved - The name the API found for that id, when it found one.
 */
export function resolvePartyName(
  raw: string | null | undefined,
  resolved?: string | null,
): PartyName {
  const name = resolved?.trim();
  if (name) return { kind: 'named', name };
  const value = raw?.trim();
  if (!value) return { kind: 'none' };
  // Anything that is not an id is what someone typed, and what they typed is
  // the answer - an email address and a surname are both usable as they are.
  return PARTY_ID.test(value) ? { kind: 'unresolved' } : { kind: 'named', name: value };
}
