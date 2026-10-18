// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Sentences for the stable problem keys of the cost structure, code list and
// allocation endpoints. Each key has its own literal `t()` call so the locale
// gates see it; an unknown key falls back to a generic sentence instead of
// showing the raw key.

import type { TFunction } from 'i18next';

type Params = Record<string, unknown>;

function str(value: unknown): string {
  return value === null || value === undefined ? '' : String(value);
}

/** Translate one problem key with its parameters. */
export function problemMessage(t: TFunction, problem: string, params: Params = {}): string {
  switch (problem) {
    // Rows of an uploaded code list.
    case 'code_missing':
      return t('costmodel.problem.code_missing', { defaultValue: 'The row has no code.' });
    case 'code_invalid':
      return t('costmodel.problem.code_invalid', {
        defaultValue: 'The code contains characters a code cannot have.',
      });
    case 'code_too_long':
      return t('costmodel.problem.code_too_long', { defaultValue: 'The code is too long.' });
    case 'title_too_long':
      return t('costmodel.problem.title_too_long', { defaultValue: 'The title is too long.' });
    case 'duplicate_code':
      return t('costmodel.problem.duplicate_code', {
        defaultValue: 'This code already appears on row {{first_row}}.',
        first_row: str(params.first_row),
      });
    case 'parent_unknown':
      return t('costmodel.problem.parent_unknown', {
        defaultValue: 'The parent code {{parent}} is not in the list.',
        parent: str(params.parent),
      });
    case 'parent_self':
      return t('costmodel.problem.parent_self', { defaultValue: 'A code cannot be its own parent.' });
    case 'parent_cycle':
      return t('costmodel.problem.parent_cycle', {
        defaultValue: 'The parents of this code loop back to it.',
      });
    case 'too_many_rows':
      return t('costmodel.problem.too_many_rows', {
        defaultValue: 'The file has more than {{max}} rows.',
        max: str(params.max),
      });
    // The uploaded file as a whole.
    case 'empty_file':
      return t('costmodel.problem.empty_file', { defaultValue: 'The file is empty.' });
    case 'missing_code_column':
      return t('costmodel.problem.missing_code_column', {
        defaultValue: 'The file has no column named code.',
      });
    case 'unreadable_file':
      return t('costmodel.problem.unreadable_file', { defaultValue: 'The file could not be read.' });
    case 'unsupported_file_type':
      return t('costmodel.problem.unsupported_file_type', {
        defaultValue: 'Upload a CSV or XLSX file.',
      });
    case 'file_too_large':
      return t('costmodel.problem.file_too_large', { defaultValue: 'The file is too large.' });
    case 'key_taken':
      return t('costmodel.problem.key_taken', {
        defaultValue: 'A code list with this key already exists.',
      });
    case 'key_invalid':
      return t('costmodel.problem.key_invalid', {
        defaultValue: 'Use lowercase letters, digits, dashes or underscores for the key.',
      });
    case 'name_missing':
      return t('costmodel.problem.name_missing', { defaultValue: 'Give the code list a name.' });
    // Structure and code lists.
    case 'structure_standard_mismatch':
      return t('costmodel.problem.structure_standard_mismatch', {
        defaultValue:
          'The cost structure is built on {{standard}}, so it cannot take codes of {{requested}}.',
        standard: str(params.standard),
        requested: str(params.requested),
      });
    case 'code_list_unknown':
      return t('costmodel.problem.code_list_unknown', { defaultValue: 'This code list does not exist.' });
    case 'code_list_in_use':
      return t('costmodel.problem.code_list_in_use', {
        defaultValue: 'Accounts of this project still use the code list, so it cannot be deleted.',
      });
    // Allocations.
    case 'unknown_mode':
      return t('costmodel.problem.unknown_mode', { defaultValue: 'Choose percent or quantity.' });
    case 'no_shares':
      return t('costmodel.problem.no_shares', { defaultValue: 'Add at least one share.' });
    case 'share_not_positive':
      return t('costmodel.problem.share_not_positive', {
        defaultValue: 'Every share must be greater than zero.',
      });
    case 'share_too_precise':
      return t('costmodel.problem.share_too_precise', {
        defaultValue: 'Too many decimals in a share. Allowed: {{max}}.',
        max: str(params.max),
      });
    case 'too_many_shares':
      return t('costmodel.problem.too_many_shares', {
        defaultValue: 'Too many shares for one position. Allowed: {{max}}.',
        max: str(params.max),
      });
    case 'quantity_split_without_quantity':
      return t('costmodel.problem.quantity_split_without_quantity', {
        defaultValue: 'The position has no quantity, so it cannot be split by quantity.',
      });
    case 'shares_do_not_add_up':
      return t('costmodel.problem.shares_do_not_add_up', {
        defaultValue: 'The shares add up to {{total}} instead of {{expected}}.',
        total: str(params.total),
        expected: str(params.expected),
      });
    case 'duplicate_target':
      return t('costmodel.problem.duplicate_target', {
        defaultValue: 'The same cost line or account appears twice.',
      });
    case 'target_missing':
      return t('costmodel.problem.target_missing', {
        defaultValue: 'A share points at a cost line or account that no longer exists.',
      });
    case 'target_not_in_project':
      return t('costmodel.problem.target_not_in_project', {
        defaultValue: 'A share points at a cost line or account of another project.',
      });
    case 'account_not_postable':
      return t('costmodel.problem.account_not_postable', {
        defaultValue:
          'A share points at a heading or a closed account, which takes no postings. Choose an account at the lowest level.',
      });
    case 'line_of_other_bill':
      return t('costmodel.problem.line_of_other_bill', {
        defaultValue: 'A share points at a cost line that belongs to another bill.',
      });
    // Putting rows on cost lines down the chain.
    case 'override_reason_required':
      return t('costmodel.problem.override_reason_required', {
        defaultValue: 'This row takes another cost line from what it changes or bills. Say why it goes on this one.',
      });
    case 'override_not_allowed':
      return t('costmodel.problem.override_not_allowed', {
        defaultValue: 'This row follows the line it comes from. Change the cost line there instead.',
      });
    case 'nothing_to_inherit':
      return t('costmodel.problem.nothing_to_inherit', {
        defaultValue: 'Nothing above this row names a cost line yet, so it has nothing to take over.',
      });
    case 'cost_line_required':
      return t('costmodel.problem.cost_line_required', { defaultValue: 'Choose a cost line.' });
    case 'cost_line_not_found':
      return t('costmodel.problem.cost_line_not_found', {
        defaultValue: 'That cost line is not in this project.',
      });
    case 'target_not_found':
      return t('costmodel.problem.target_not_found', {
        defaultValue: 'This row is no longer in the project. Reload the page.',
      });
    case 'contract_closed':
      return t('costmodel.problem.contract_closed', {
        defaultValue: 'This contract is closed, so no schedule line can be added to it.',
      });
    case 'contract_line_not_in_project':
      return t('costmodel.problem.contract_line_not_in_project', {
        defaultValue: 'The contract line is not on a contract of this project.',
      });
    case 'cost_line_conflicts_with_contract_line':
      return t('costmodel.problem.cost_line_conflicts_with_contract_line', {
        defaultValue: 'The line names a contract line and a different cost line. Keep one of them.',
      });
    case 'not_a_supplier_invoice':
      return t('costmodel.problem.not_a_supplier_invoice', {
        defaultValue: 'Only a supplier invoice can be recorded as a direct cost.',
      });
    case 'invoice_has_contract':
      return t('costmodel.problem.invoice_has_contract', {
        defaultValue: 'This invoice already belongs to a contract or an order.',
      });
    case 'not_costed':
      // Same sentence the drawer shows for a position without money.
      return t('boq.cost_allocation.not_costed', {
        defaultValue: 'This position carries no money yet, so there is nothing to allocate.',
      });
    default:
      return t('costmodel.problem.unknown', {
        defaultValue: 'The request could not be completed.',
      });
  }
}
