// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The assistant's tools, named in the reader's language.
 *
 * One list for both chat surfaces: the dock's compact "Looked up: Risk
 * register" rows and the full page's tool cards. Every known tool has its own
 * literal key, so the i18n gates see each one; a tool this list does not know
 * yet (a newer backend) falls back to its name made readable instead of
 * printing `search_foo_bar` at the reader.
 *
 * Tools named `propose_*` only PREPARE a change: nothing reaches the project
 * until a person applies the proposal card they return. The legacy
 * `create_boq_item` wrote directly; it is gone from the backend and kept here
 * only so old conversations still read correctly.
 */
import type { TFunction } from 'i18next';

/** True for a tool that prepares a change for a person to approve. */
export function isProposalTool(name: string): boolean {
  return name.startsWith('propose_');
}

/** `search_bim_elements` -> `Search bim elements`, for tools not listed below. */
export function readableToolName(name: string): string {
  const words = name.replace(/[_-]+/g, ' ').trim();
  if (!words) return name;
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** The name of a tool, or of what it looks up, in the reader's language. */
export function toolLabel(name: string, t: TFunction): string {
  switch (name) {
    // Lookups: named after what they read.
    case 'get_all_projects':
      return String(t('erp_chat.tool.get_all_projects', { defaultValue: 'Your projects' }));
    case 'get_project_summary':
      return String(t('erp_chat.tool.get_project_summary', { defaultValue: 'Project summary' }));
    case 'get_boq_items':
      return String(t('erp_chat.tool.get_boq_items', { defaultValue: 'BOQ positions' }));
    case 'get_schedule':
      return String(t('erp_chat.tool.get_schedule', { defaultValue: 'Schedule' }));
    case 'get_validation_results':
      return String(t('erp_chat.tool.get_validation_results', { defaultValue: 'Validation results' }));
    case 'get_risk_register':
      return String(t('erp_chat.tool.get_risk_register', { defaultValue: 'Risk register' }));
    case 'get_cost_model':
      return String(t('erp_chat.tool.get_cost_model', { defaultValue: 'Cost model' }));
    case 'compare_projects':
      return String(t('erp_chat.tool.compare_projects', { defaultValue: 'Project comparison' }));
    case 'run_validation':
      return String(t('erp_chat.tool.run_validation', { defaultValue: 'Validation check' }));
    case 'search_cwicr_database':
      return String(t('erp_chat.tool.search_cwicr_database', { defaultValue: 'CWICR cost database' }));
    case 'search_anything':
      return String(t('erp_chat.tool.search_anything', { defaultValue: 'All project records' }));
    case 'search_bim_elements':
      return String(t('erp_chat.tool.search_bim_elements', { defaultValue: 'BIM elements' }));
    case 'search_boq_positions':
      return String(t('erp_chat.tool.search_boq_positions', { defaultValue: 'BOQ position search' }));
    case 'search_correspondence':
      return String(t('erp_chat.tool.search_correspondence', { defaultValue: 'Correspondence' }));
    case 'search_documents':
      return String(t('erp_chat.tool.search_documents', { defaultValue: 'Documents' }));
    case 'search_rfis':
      return String(t('erp_chat.tool.search_rfis', { defaultValue: 'RFIs' }));
    case 'search_risks':
      return String(t('erp_chat.tool.search_risks', { defaultValue: 'Risks' }));
    case 'search_submittals':
      return String(t('erp_chat.tool.search_submittals', { defaultValue: 'Submittals' }));
    case 'search_tasks':
      return String(t('erp_chat.tool.search_tasks', { defaultValue: 'Tasks' }));
    // Proposals: named after the change they prepare.
    case 'propose_add_boq_position':
      return String(t('erp_chat.tool.propose_add_boq_position', { defaultValue: 'Add a BOQ position' }));
    case 'propose_update_boq_position':
      return String(t('erp_chat.tool.propose_update_boq_position', { defaultValue: 'Change a BOQ position' }));
    case 'propose_create_task':
      return String(t('erp_chat.tool.propose_create_task', { defaultValue: 'Create a task' }));
    case 'propose_create_rfi':
      return String(t('erp_chat.tool.propose_create_rfi', { defaultValue: 'Raise an RFI' }));
    case 'propose_create_risk':
      return String(t('erp_chat.tool.propose_create_risk', { defaultValue: 'Log a risk' }));
    case 'propose_create_punch_item':
      return String(t('erp_chat.tool.propose_create_punch_item', { defaultValue: 'Add a punch item' }));
    case 'propose_update_schedule_progress':
      return String(
        t('erp_chat.tool.propose_update_schedule_progress', { defaultValue: 'Update schedule progress' }),
      );
    // Legacy direct write, kept for conversations recorded before proposals.
    case 'create_boq_item':
      return String(t('erp_chat.tool.create_boq_item', { defaultValue: 'BOQ position created' }));
    default:
      return readableToolName(name);
  }
}

/**
 * The reader-facing reason a tool gave for refusing, when it gave one. A
 * refused proposal carries `{error, message, i18n_key}` in `data`: `message`
 * is written for the person (the `summary` next to it is written for the
 * model and tells it to call the tool again).
 */
export function toolRefusalText(data: unknown, t: TFunction): string | null {
  if (typeof data !== 'object' || data === null || Array.isArray(data)) return null;
  const record = data as Record<string, unknown>;
  const message = typeof record.message === 'string' && record.message.length > 0 ? record.message : null;
  const key = typeof record.i18n_key === 'string' && record.i18n_key.length > 0 ? record.i18n_key : null;
  if (key) return String(t(key, { defaultValue: message ?? '' })) || message;
  return message;
}
