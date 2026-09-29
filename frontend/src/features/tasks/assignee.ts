// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * How a task's assignee travels to the API.
 *
 * A user pick is the task's ``responsible_id``, which my-tasks and the
 * assignment notification follow. A contact pick and a typed name are not
 * users, so they stay out of that column: the name goes to
 * ``metadata.assignee_name`` and a contact also leaves its id in
 * ``metadata.assignee_contact_id``.
 *
 * The update route merges metadata key by key, so a key left out of a patch
 * keeps its old value. Both assignee keys are therefore always sent, as
 * ``null`` when unused, or switching from a contact to a user would leave the
 * contact's name behind.
 */

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export interface AssigneeForm {
  assigned_to: string;
  assignee_user_id: string;
  assignee_contact_id: string;
}

export interface AssigneeFields {
  responsible_id: string | null;
  metadata: { assignee_name: string | null; assignee_contact_id: string | null };
}

export function assigneeFields(form: AssigneeForm): AssigneeFields {
  const name = form.assigned_to.trim();
  // A pasted user id still links the user, as the plain text field did.
  const userId = form.assignee_user_id || (UUID_RE.test(name) ? name : '');
  if (userId) {
    return { responsible_id: userId, metadata: { assignee_name: null, assignee_contact_id: null } };
  }
  return {
    responsible_id: null,
    metadata: {
      assignee_name: name || null,
      assignee_contact_id: name && form.assignee_contact_id ? form.assignee_contact_id : null,
    },
  };
}
