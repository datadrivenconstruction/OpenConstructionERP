// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Settle a period in process and get it signed" (CN).
//
// In-process settlement divides the works into periods or nodes and settles
// each one while the people who did the work are still on site. The completed
// and undisputed quantities for the period, including the changes accepted in
// it, are priced and confirmed by both parties, and the confirmed document is
// meant to be carried into the final account rather than argued again.
//
// The commercial value of that is entirely in the paper. A period settled by
// handshake is a period that gets reopened, so the case is built around
// producing a document with a fixed content, a named version of the bill behind
// it, and two signatures on the record - and around keeping those documents
// together so the final account is assembled from them. Content strings are key
// plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "settle-a-period-in-process-and-get-it-signed",
  order: 1124,
  region: "CN",
  category: "commercial",
  companyTypes: ["general-contractor", "developer-client", "cost-consultant", "project-manager"],
  roles: ["quantity-surveyor", "commercial-manager", "contract-administrator"],
  icon: "Stamp",
  titleKey: "cases.settle_a_period_in_process_and_get_it_signed.title",
  titleDefault: "Settle a period in process and get it signed",
  descKey: "cases.settle_a_period_in_process_and_get_it_signed.desc",
  descDefault:
    "Price the completed and undisputed quantities for one period including the changes accepted in it, freeze the bill as a named version, write the confirmed statement, and get both parties' signatures on the record.",
  longDescKey: "cases.settle_a_period_in_process_and_get_it_signed.longdesc",
  longDescDefault:
    "Settling as you go is the practice that stops a final account becoming an archaeology project. The reasoning is simple: the people who can say what happened in March are available in April and gone in eighteen months, and a quantity confirmed while the work is visible costs an hour to agree and a fortnight to reconstruct. What makes it hold afterwards is not the agreement, it is the document - a statement of exactly which quantities and which accepted changes were confirmed, tied to a named version of the bill so both parties can point at the same numbers, with two signatures against it. A bill legitimately keeps moving after a period is settled, because that is what later periods are for. What must not happen is a settled statement whose content changes underneath the signatures it already carries, and the fix for that is a version you can name rather than a bill you promise not to touch.",
  estMinutes: 18,
  steps: [
    {
      id: "price",
      icon: "Calculator",
      inputs: [
        { labelKey: "cases.settle_a_period_in_process_and_get_it_signed.step.price.in.completed", label: "Quantities completed in the period" },
        { labelKey: "cases.settle_a_period_in_process_and_get_it_signed.step.price.in.changes", label: "Changes accepted in the period" },
      ],
      outputs: [
        { labelKey: "cases.settle_a_period_in_process_and_get_it_signed.step.price.out.value", label: "Value of the period" },
        { labelKey: "cases.settle_a_period_in_process_and_get_it_signed.step.price.out.disputed", label: "Disputed items left out" },
      ],
      titleKey: "cases.settle_a_period_in_process_and_get_it_signed.step.price.title",
      titleDefault: "Price only what is complete and undisputed",
      whatKey: "cases.settle_a_period_in_process_and_get_it_signed.step.price.what",
      whatDefault:
        "Work the bill for the period: price the quantities that are complete, add the changes that were accepted inside it, and deliberately leave out anything still in dispute. Note what you left out and why.",
      whyKey: "cases.settle_a_period_in_process_and_get_it_signed.step.price.why",
      whyDefault:
        "The point of settling in process is to take the settled part off the table permanently, and one contested item is enough to keep a whole period open. Confirming ninety percent now and carrying ten percent forward is worth far more than agreeing everything eventually. The 2024 standard makes the settled part permanent by rule: a period statement both parties have confirmed is the basis of the completion settlement and is not measured or priced again, and the period is paid at no less than eighty percent of its settled value.",
      moduleLabel: "BOQ",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "freeze",
      icon: "GitBranch",
      inputs: [
        { labelKey: "cases.settle_a_period_in_process_and_get_it_signed.step.freeze.in.priced", label: "The period priced" },
      ],
      outputs: [
        { labelKey: "cases.settle_a_period_in_process_and_get_it_signed.step.freeze.out.version", label: "Named version of the bill" },
        { labelKey: "cases.settle_a_period_in_process_and_get_it_signed.step.freeze.out.retrievable", label: "The exact numbers, retrievable" },
      ],
      titleKey: "cases.settle_a_period_in_process_and_get_it_signed.step.freeze.title",
      titleDefault: "Take a named version at the close of the period",
      whatKey: "cases.settle_a_period_in_process_and_get_it_signed.step.freeze.what",
      whatDefault:
        "Save a version of the bill at the moment the period closes and name it for the period, so the state you are about to have signed can be retrieved exactly as it was.",
      whyKey: "cases.settle_a_period_in_process_and_get_it_signed.step.freeze.why",
      whyDefault:
        "The bill carries on moving after this, and that is correct. What the named version buys you is the ability to answer, in a year, which numbers the signatures were given against - without asking anybody to remember, and without freezing a document the project still needs to work on.",
      moduleLabel: "BOQ",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "statement",
      icon: "FileText",
      inputs: [
        { labelKey: "cases.settle_a_period_in_process_and_get_it_signed.step.statement.in.version", label: "The named version" },
        { labelKey: "cases.settle_a_period_in_process_and_get_it_signed.step.statement.in.excluded", label: "What was left out" },
      ],
      outputs: [
        { labelKey: "cases.settle_a_period_in_process_and_get_it_signed.step.statement.out.doc", label: "Confirmed period statement" },
      ],
      titleKey: "cases.settle_a_period_in_process_and_get_it_signed.step.statement.title",
      titleDefault: "Write the statement the two parties will sign",
      whatKey: "cases.settle_a_period_in_process_and_get_it_signed.step.statement.what",
      whatDefault:
        "File the period statement in the project documents: the span it covers, the confirmed quantities and value, the changes included, the items deliberately excluded, and the name of the bill version it was taken from.",
      whyKey: "cases.settle_a_period_in_process_and_get_it_signed.step.statement.why",
      whyDefault:
        "A signature is only as good as the document under it. A statement that names its own span and its own exclusions cannot later be read as covering more or less than it did, which is the single most common way an in-process settlement stops holding.",
      moduleLabel: "Documents",
      moduleLabelKey: "nav.documents",
      to: "/projects/:projectId/files",
    },
    {
      id: "sign",
      icon: "FileSignature",
      inputs: [
        { labelKey: "cases.settle_a_period_in_process_and_get_it_signed.step.sign.in.doc", label: "The period statement" },
        { labelKey: "cases.settle_a_period_in_process_and_get_it_signed.step.sign.in.parties", label: "Both parties' signatories" },
      ],
      outputs: [
        { labelKey: "cases.settle_a_period_in_process_and_get_it_signed.step.sign.out.session", label: "Signing session on the record" },
        { labelKey: "cases.settle_a_period_in_process_and_get_it_signed.step.sign.out.signed", label: "Who signed, and when" },
      ],
      titleKey: "cases.settle_a_period_in_process_and_get_it_signed.step.sign.title",
      titleDefault: "Get both signatures against the same document",
      whatKey: "cases.settle_a_period_in_process_and_get_it_signed.step.sign.what",
      whatDefault:
        "Open a signing session over the statement, name the signatory on each side, and let each of them sign. Every signature is recorded against that document reference with the time it was given.",
      whyKey: "cases.settle_a_period_in_process_and_get_it_signed.step.sign.why",
      whyDefault:
        "Two signatures on one document is the whole mechanism. Two separate approvals in two separate systems is what produces the classic dispute where each side is certain it agreed to something slightly different, and neither can show what.",
      moduleLabel: "E-Signatures",
      moduleLabelKey: "signing.title",
      to: "/signing",
    },
    {
      id: "assemble",
      icon: "FileStack",
      inputs: [
        { labelKey: "cases.settle_a_period_in_process_and_get_it_signed.step.assemble.in.signed", label: "Signed period statements" },
      ],
      outputs: [
        { labelKey: "cases.settle_a_period_in_process_and_get_it_signed.step.assemble.out.running", label: "Running settled position" },
        { labelKey: "cases.settle_a_period_in_process_and_get_it_signed.step.assemble.out.open", label: "What is still open" },
      ],
      titleKey: "cases.settle_a_period_in_process_and_get_it_signed.step.assemble.title",
      titleDefault: "Keep the settled periods together for the final account",
      whatKey: "cases.settle_a_period_in_process_and_get_it_signed.step.assemble.what",
      whatDefault:
        "Report the settled periods as a running set: what has been confirmed and signed to date, and what is still carried forward as open. Bring that set to the final account as your starting position.",
      whyKey: "cases.settle_a_period_in_process_and_get_it_signed.step.assemble.why",
      whyDefault:
        "A final account assembled from documents both parties already signed is a short meeting about the open items. A final account started from the whole bill invites a review of everything, including the parts that were settled fairly two years ago and that nobody now remembers agreeing.",
      moduleLabel: "Reports",
      moduleLabelKey: "nav.reports",
      to: "/reports",
    },
  ],
};

export default playbook;
