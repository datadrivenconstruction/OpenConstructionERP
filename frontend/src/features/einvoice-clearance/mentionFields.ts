/**
 * How the optional invoice-mention fields are drawn.
 *
 * The backend names which fields a country offers (`optional_document_fields`,
 * `profile_setting_fields`); this only says what kind of input each name is.
 * A name not listed here is plain text, so a country can add a field without a
 * change here.
 */
export type MentionInput =
  | { kind: 'text' }
  | { kind: 'checkbox' }
  | { kind: 'select'; options: readonly string[] };

export const DOCUMENT_MENTION_INPUTS: Record<string, MentionInput> = {
  transaction_scope: { kind: 'select', options: ['b2b_domestic', 'b2c', 'cross_border', 'export'] },
  operation_category: { kind: 'select', options: ['goods', 'services', 'both'] },
  delivery_differs: { kind: 'checkbox' },
};

export const SETTING_INPUTS: Record<string, MentionInput> = {
  vat_on_debits_option: { kind: 'checkbox' },
};

export function documentInput(field: string): MentionInput {
  return DOCUMENT_MENTION_INPUTS[field] ?? { kind: 'text' };
}
