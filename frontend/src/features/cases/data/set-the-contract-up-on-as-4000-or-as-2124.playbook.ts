// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Set the contract up on AS 4000 or AS 2124" (AU).
//
// The two Australian Standard general conditions still in daily use, and the
// Annexure that turns either of them into this job. AS 2124-1992 is the older
// form and remains common on civil and government work; AS 4000-1997 is its
// successor and reads more evenly between the parties. Almost every figure that
// decides a later argument, the security, the liquidated damages, the defects
// liability period, the times for claims, lives in the Annexure rather than in
// the printed conditions. Content strings are key plus inline English default
// and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "set-the-contract-up-on-as-4000-or-as-2124",
  order: 1624,
  region: "AU",
  category: "commercial",
  companyTypes: ["general-contractor", "developer-client", "project-manager", "cost-consultant"],
  roles: ["contract-administrator", "commercial-manager", "quantity-surveyor", "project-manager"],
  stage: "procure",
  icon: "FileSignature",
  titleKey: "cases.set_the_contract_up_on_as_4000_or_as_2124.title",
  titleDefault: "Set the contract up on AS 4000 or AS 2124",
  descKey: "cases.set_the_contract_up_on_as_4000_or_as_2124.desc",
  descDefault:
    "Pick the general conditions and record the Annexure that fills them in, settle the security and its reduction, name the Superintendent and what they may decide, load the dates the liquidated damages hang on, allocate the risks the Annexure allocates and execute the thing everyone will be working from.",
  longDescKey: "cases.set_the_contract_up_on_as_4000_or_as_2124.longdesc",
  longDescDefault:
    "AS 2124-1992 and AS 4000-1997 are the two Australian Standard general conditions a contract administrator meets most often, and they are not interchangeable. AS 2124 is the older form and survives on civil and government work where a principal has amended it for thirty years; AS 4000 replaced it with a more balanced allocation and a tidier claims procedure. Whichever is used, the printed conditions are only half the contract. The Annexure carries the parties, the dates, the percentages and the periods, and it is where a job is won or lost in the first week: an Annexure left with the standard defaults on a project the defaults were never written for produces arguments that no amount of good site management can undo.",
  estMinutes: 16,
  steps: [
    {
      id: "form",
      icon: "BookOpen",
      inputs: [
        { labelKey: "cases.set_the_contract_up_on_as_4000_or_as_2124.step.form.in.award", label: "Award decision" },
        { labelKey: "cases.set_the_contract_up_on_as_4000_or_as_2124.step.form.in.amendments", label: "Principal's amendments" },
      ],
      outputs: [
        { labelKey: "cases.set_the_contract_up_on_as_4000_or_as_2124.step.form.out.form", label: "General conditions chosen" },
        { labelKey: "cases.set_the_contract_up_on_as_4000_or_as_2124.step.form.out.annexure", label: "Annexure recorded" },
      ],
      titleKey: "cases.set_the_contract_up_on_as_4000_or_as_2124.step.form.title",
      titleDefault: "Record which form it is and what the Annexure says",
      whatKey: "cases.set_the_contract_up_on_as_4000_or_as_2124.step.form.what",
      whatDefault:
        "Create the contract record naming the form, AS 4000-1997 or AS 2124-1992, the contract sum and whether it is lump sum or schedule of rates, and enter the Annexure values that the rest of the job runs on. Record the principal's amendments as amendments rather than folding them into the printed clause, so anyone reading later can see what was changed from the standard.",
      whyKey: "cases.set_the_contract_up_on_as_4000_or_as_2124.step.form.why",
      whyDefault:
        "The commonest cause of an argument on an Australian Standard contract is two people reading two different documents, one the printed form and one the amended version. A contract record that names the form, carries the Annexure and lists the departures is what makes a clause reference a fact rather than an opinion.",
      moduleLabel: "Contracts",
      moduleLabelKey: "nav.contracts",
      to: "/projects/:projectId/contracts",
    },
    {
      id: "security",
      icon: "ShieldCheck",
      inputs: [
        { labelKey: "cases.set_the_contract_up_on_as_4000_or_as_2124.step.security.in.annexure", label: "Annexure recorded" },
        { labelKey: "cases.set_the_contract_up_on_as_4000_or_as_2124.step.security.in.guarantees", label: "Bank guarantees offered" },
      ],
      outputs: [
        { labelKey: "cases.set_the_contract_up_on_as_4000_or_as_2124.step.security.out.security", label: "Security terms on record" },
        { labelKey: "cases.set_the_contract_up_on_as_4000_or_as_2124.step.security.out.release", label: "When each half is released" },
      ],
      titleKey: "cases.set_the_contract_up_on_as_4000_or_as_2124.step.security.title",
      titleDefault: "Settle the security and the day it reduces",
      whatKey: "cases.set_the_contract_up_on_as_4000_or_as_2124.step.security.what",
      whatDefault:
        "Record what security the contract takes, cash retention held from each progress payment or unconditional undertakings from a bank, the percentage and the limit, and the two events that release it: the reduction at practical completion and the release at the end of the defects liability period. Note who holds the guarantees and where.",
      whyKey: "cases.set_the_contract_up_on_as_4000_or_as_2124.step.security.why",
      whyDefault:
        "Security is the cheapest money on the job to lose track of, because nobody chases it until long after the site has closed and the people who knew the arrangement have moved on. A reduction that should have happened at practical completion and did not is working capital sitting in somebody else's account for a year.",
      moduleLabel: "Contracts",
      moduleLabelKey: "nav.contracts",
      to: "/projects/:projectId/contracts",
    },
    {
      id: "superintendent",
      icon: "UserCheck",
      inputs: [
        { labelKey: "cases.set_the_contract_up_on_as_4000_or_as_2124.step.superintendent.in.form", label: "General conditions chosen" },
        { labelKey: "cases.set_the_contract_up_on_as_4000_or_as_2124.step.superintendent.in.delegation", label: "Delegations from the principal" },
      ],
      outputs: [
        { labelKey: "cases.set_the_contract_up_on_as_4000_or_as_2124.step.superintendent.out.named", label: "Superintendent named" },
        { labelKey: "cases.set_the_contract_up_on_as_4000_or_as_2124.step.superintendent.out.limits", label: "What each decision needs" },
      ],
      titleKey: "cases.set_the_contract_up_on_as_4000_or_as_2124.step.superintendent.title",
      titleDefault: "Name the Superintendent and map what they may decide",
      whatKey: "cases.set_the_contract_up_on_as_4000_or_as_2124.step.superintendent.what",
      whatDefault:
        "Name the Superintendent and the Superintendent's Representative, and build the approval route that says which decisions they make alone, which need the principal, and what value threshold moves a direction from one to the other. Certificates, directions to vary and extensions of time all sit on that map.",
      whyKey: "cases.set_the_contract_up_on_as_4000_or_as_2124.step.superintendent.why",
      whyDefault:
        "Both forms require the Superintendent to act honestly and, for the functions where they are certifying rather than acting as the principal's agent, reasonably and independently. A route that records who decided what and on what authority protects the certifier as much as the contractor, because a direction given by someone without the authority to give it is an argument waiting for the final account.",
      moduleLabel: "Approval routes",
      moduleLabelKey: "approvalRoutes.title",
      to: "/governance?tab=approvals",
    },
    {
      id: "dates",
      icon: "CalendarClock",
      inputs: [
        { labelKey: "cases.set_the_contract_up_on_as_4000_or_as_2124.step.dates.in.annexure", label: "Annexure recorded" },
        { labelKey: "cases.set_the_contract_up_on_as_4000_or_as_2124.step.dates.in.programme", label: "Construction programme" },
      ],
      outputs: [
        { labelKey: "cases.set_the_contract_up_on_as_4000_or_as_2124.step.dates.out.watched", label: "Contract dates under watch" },
        { labelKey: "cases.set_the_contract_up_on_as_4000_or_as_2124.step.dates.out.damages", label: "Liquidated damages rate on record" },
      ],
      titleKey: "cases.set_the_contract_up_on_as_4000_or_as_2124.step.dates.title",
      titleDefault: "Load the dates the damages hang on",
      whatKey: "cases.set_the_contract_up_on_as_4000_or_as_2124.step.dates.what",
      whatDefault:
        "Put the date for practical completion, the separable portions if the contract has them, the liquidated damages rate and any limit on it, and the length of the defects liability period under watch, together with the time the Annexure allows for a claim to be made. Let each one warn before it lands.",
      whyKey: "cases.set_the_contract_up_on_as_4000_or_as_2124.step.dates.why",
      whyDefault:
        "Liquidated damages run per day from a date, and the defects liability period ends on a date, and both are worked out from Annexure entries that nobody rereads once the job starts. A claim window that closed while the site was busy is an entitlement gone, and no notice is served on you when it happens.",
      moduleLabel: "Deadlines",
      moduleLabelKey: "deadlines.title",
      to: "/deadlines",
    },
    {
      id: "risk",
      icon: "ShieldAlert",
      inputs: [
        { labelKey: "cases.set_the_contract_up_on_as_4000_or_as_2124.step.risk.in.annexure", label: "Annexure recorded" },
        { labelKey: "cases.set_the_contract_up_on_as_4000_or_as_2124.step.risk.in.site", label: "Site information provided" },
      ],
      outputs: [
        { labelKey: "cases.set_the_contract_up_on_as_4000_or_as_2124.step.risk.out.allocated", label: "Risks allocated on the register" },
        { labelKey: "cases.set_the_contract_up_on_as_4000_or_as_2124.step.risk.out.insurance", label: "Insurances and who effects them" },
      ],
      titleKey: "cases.set_the_contract_up_on_as_4000_or_as_2124.step.risk.title",
      titleDefault: "Write down who carries what",
      whatKey: "cases.set_the_contract_up_on_as_4000_or_as_2124.step.risk.what",
      whatDefault:
        "Take the allocations out of the conditions and the Annexure and put them on the risk register in words a site manager can act on: latent conditions and what counts as one, who effects the works insurance and the public liability cover and for how much, the excepted risks, and where the contract has been amended to move a risk from the standard position.",
      whyKey: "cases.set_the_contract_up_on_as_4000_or_as_2124.step.risk.why",
      whyDefault:
        "Latent conditions are the clause most often amended away in Australian practice, and a contractor who assumed the standard position and priced accordingly finds out the day the excavator hits rock. A risk that lives only in clause 25 of a document in a drawer is a risk nobody manages.",
      moduleLabel: "Risk Register",
      moduleLabelKey: "nav.risk_register",
      to: "/risks",
    },
    {
      id: "execute",
      icon: "Signature",
      inputs: [
        { labelKey: "cases.set_the_contract_up_on_as_4000_or_as_2124.step.execute.in.final", label: "Final contract documents" },
        { labelKey: "cases.set_the_contract_up_on_as_4000_or_as_2124.step.execute.in.signatories", label: "Authorised signatories" },
      ],
      outputs: [
        { labelKey: "cases.set_the_contract_up_on_as_4000_or_as_2124.step.execute.out.signed", label: "Executed contract" },
        { labelKey: "cases.set_the_contract_up_on_as_4000_or_as_2124.step.execute.out.copies", label: "One version everyone reads" },
      ],
      titleKey: "cases.set_the_contract_up_on_as_4000_or_as_2124.step.execute.title",
      titleDefault: "Execute it and make it the version everyone reads",
      whatKey: "cases.set_the_contract_up_on_as_4000_or_as_2124.step.execute.what",
      whatDefault:
        "Send the complete set for execution, conditions, Annexure, amendments, drawings and specification listed as contract documents in the order of precedence the contract sets, and keep the executed version as the one the site, the estimator and the accounts all work from.",
      whyKey: "cases.set_the_contract_up_on_as_4000_or_as_2124.step.execute.why",
      whyDefault:
        "Work starting before execution is normal in Australia and it is also how a job runs for six months on a draft nobody signed. The order of precedence matters as much as the signature, because it decides which document wins when the drawing and the specification disagree, and they always disagree eventually.",
      moduleLabel: "E-Signatures",
      moduleLabelKey: "signing.title",
      to: "/signing",
    },
  ],
};

export default playbook;
