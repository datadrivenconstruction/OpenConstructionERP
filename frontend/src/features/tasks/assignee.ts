// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * How a task's assignee travels to the API.
 *
 * A user pick is the task's ``responsible_id``, which my-tasks and the
 * assignment notification follow. A contact pick goes by id
 * (``assignee_contact_id``) and the server decides what it links: the
 * contact's platform user, if it has one, becomes ``responsible_id``, and the
 * contact's name is kept either way. A typed name stays a plain name in
 * ``metadata.assignee_name``.
 *
 * The update route merges metadata key by key, so a key left out of a patch
 * keeps its old value. A user or a typed name therefore sends
 * ``assignee_contact_id: null`` and its own ``assignee_name`` (``null`` for a
 * user), or switching away from a contact would leave the contact behind.
 */

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export interface AssigneeForm {
  assigned_to: string;
  assignee_user_id: string;
  assignee_contact_id: string;
}

export type AssigneeFields =
  | { assignee_contact_id: string }
  | {
      responsible_id: string | null;
      assignee_contact_id: null;
      metadata: { assignee_name: string | null };
    };

export function assigneeFields(form: AssigneeForm): AssigneeFields {
  const name = form.assigned_to.trim();
  if (form.assignee_contact_id && name) return { assignee_contact_id: form.assignee_contact_id };
  // A pasted user id still links the user, as the plain text field did.
  const userId = form.assignee_user_id || (UUID_RE.test(name) ? name : '');
  if (userId) {
    return { responsible_id: userId, assignee_contact_id: null, metadata: { assignee_name: null } };
  }
  return { responsible_id: null, assignee_contact_id: null, metadata: { assignee_name: name || null } };
}
