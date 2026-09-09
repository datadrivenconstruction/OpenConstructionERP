// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Administer a variation under NZS 3910" (NZ).
//
// The New Zealand standard conditions of contract for building and civil
// engineering construction, and specifically what the 2023 revision did to the
// role that instructs and values a variation: the single Engineer to the
// Contract became a Contract Administrator acting for the Principal and an
// Independent Certifier deciding the matters that have to be decided
// impartially. A variation administered as though one person still held both
// hats is the commonest way a good entitlement is lost on this form. Content
// strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "administer-a-variation-under-nzs-3910",
  order: 1420,
  region: "NZ",
  category: "commercial",
  companyTypes: ["general-contractor", "cost-consultant", "project-manager", "subcontractor"],
  roles: ["contract-administrator", "quantity-surveyor", "commercial-manager", "project-manager"],
  icon: "GitBranch",
  titleKey: "cases.administer_a_variation_under_nzs_3910.title",
  titleDefault: "Administer a variation under NZS 3910",
  descKey: "cases.administer_a_variation_under_nzs_3910.desc",
  descDefault:
    "Record which edition of NZS 3910 the job runs on and who holds which role under it, check who may instruct, raise the instruction, value the work in the order of preference the contract sets, keep the notice and the records behind it, and read the effect on the programme and the contract sum.",
  longDescKey: "cases.administer_a_variation_under_nzs_3910.longdesc",
  longDescDefault:
    "NZS 3910 is the standard form most New Zealand building and civil work is built under, and the 2023 revision changed the thing that matters most about administering it. For thirty years one person, the Engineer to the Contract, both ran the contract for the Principal and decided disputes between the Principal and the Contractor, which everybody knew was uncomfortable and everybody lived with. The 2023 edition splits that in two: a Contract Administrator who acts for the Principal, and an Independent Certifier who makes the determinations that have to be made impartially. On a variation this decides who instructs, who values and who determines when the two sides disagree, so the first question on any job is which edition it is written on. The second is whether the notice went out inside the period the contract allows, because on this form an entitlement that was real can still be lost by being raised late.",
  estMinutes: 15,
  steps: [
    {
      id: "form",
      icon: "BookOpen",
      inputs: [
        {
          labelKey: "cases.administer_a_variation_under_nzs_3910.step.form.in.contract",
          label: "Executed contract",
        },
        {
          labelKey: "cases.administer_a_variation_under_nzs_3910.step.form.in.special",
          label: "Special conditions",
        },
      ],
      outputs: [
        {
          labelKey: "cases.administer_a_variation_under_nzs_3910.step.form.out.edition",
          label: "Edition and form on record",
        },
        {
          labelKey: "cases.administer_a_variation_under_nzs_3910.step.form.out.roles",
          label: "Who holds which role",
        },
      ],
      titleKey: "cases.administer_a_variation_under_nzs_3910.step.form.title",
      titleDefault: "Record the edition and who holds which role",
      whatKey: "cases.administer_a_variation_under_nzs_3910.step.form.what",
      whatDefault:
        "Record which form the job is built on and which edition of it: NZS 3910 for a build to the Principal's design, NZS 3916 where the Contractor also designs, NZS 3917 for a term contract. Then name the people. On the 2023 edition of NZS 3910 that is a Contract Administrator and an Independent Certifier; on the 2013 edition it is a single Engineer to the Contract. Record the special conditions that change either, because they usually do.",
      whyKey: "cases.administer_a_variation_under_nzs_3910.step.form.why",
      whyDefault:
        "Every step below depends on this answer and none of them announce it. A notice addressed to the Engineer on a contract that has no Engineer, or a valuation determined by the person acting for the Principal when the contract reserves that to the Independent Certifier, is defective on its face, and it is defective in a way that is only noticed once somebody has a reason to look.",
      moduleLabel: "Contracts",
      moduleLabelKey: "nav.contracts",
      to: "/projects/:projectId/contracts",
    },
    {
      id: "authority",
      icon: "UserCheck",
      inputs: [
        {
          labelKey: "cases.administer_a_variation_under_nzs_3910.step.authority.in.roles",
          label: "Who holds which role",
        },
        {
          labelKey: "cases.administer_a_variation_under_nzs_3910.step.authority.in.limits",
          label: "Delegated limits",
        },
      ],
      outputs: [
        {
          labelKey: "cases.administer_a_variation_under_nzs_3910.step.authority.out.route",
          label: "Instruction route settled",
        },
        {
          labelKey: "cases.administer_a_variation_under_nzs_3910.step.authority.out.threshold",
          label: "Value that needs the Principal",
        },
      ],
      titleKey: "cases.administer_a_variation_under_nzs_3910.step.authority.title",
      titleDefault: "Settle who may instruct a variation and up to what value",
      whatKey: "cases.administer_a_variation_under_nzs_3910.step.authority.what",
      whatDefault:
        "Build the approval route the contract and the Principal's own delegations actually create: who may issue a variation instruction, what value the Contract Administrator may instruct without going back to the Principal, and which decisions the Independent Certifier makes rather than either of them. Put site staff and the Contractor's representative on the same route so nobody is guessing.",
      whyKey: "cases.administer_a_variation_under_nzs_3910.step.authority.why",
      whyDefault:
        "Work carried out on the word of somebody with no authority to instruct it is work the Contractor has done at its own risk, and the argument that follows is never about whether the work was needed. It is always about who said so. Naming the route in advance costs an afternoon and settles a class of dispute that otherwise arrives at the final account.",
      moduleLabel: "Approval routes",
      moduleLabelKey: "approvalRoutes.title",
      to: "/governance?tab=approvals",
    },
    {
      id: "instruct",
      icon: "FileSignature",
      inputs: [
        {
          labelKey: "cases.administer_a_variation_under_nzs_3910.step.instruct.in.change",
          label: "Change to the works",
        },
        {
          labelKey: "cases.administer_a_variation_under_nzs_3910.step.instruct.in.route",
          label: "Instruction route settled",
        },
      ],
      outputs: [
        {
          labelKey: "cases.administer_a_variation_under_nzs_3910.step.instruct.out.instruction",
          label: "Variation instruction issued",
        },
        {
          labelKey: "cases.administer_a_variation_under_nzs_3910.step.instruct.out.scope",
          label: "Scope of the change described",
        },
      ],
      titleKey: "cases.administer_a_variation_under_nzs_3910.step.instruct.title",
      titleDefault: "Issue the instruction before the work is built",
      whatKey: "cases.administer_a_variation_under_nzs_3910.step.instruct.what",
      whatDefault:
        "Raise the variation as an instruction that describes the change in the works, references the drawing or the specification clause it comes from, and states whether the Contractor is to proceed or to price first. Where the Contractor believes it has already been given an instruction in substance, record that as a claim for a variation rather than waiting for a document that may never come.",
      whyKey: "cases.administer_a_variation_under_nzs_3910.step.instruct.why",
      whyDefault:
        "A variation is a change the contract allows the Principal to make, and the mechanism is the instruction. Work built first and documented afterwards leaves the Contractor arguing that a conversation was an instruction, which is a much weaker case than a piece of paper, and it leaves the Principal paying for work whose scope nobody wrote down while it was still describable.",
      moduleLabel: "Change Orders",
      moduleLabelKey: "nav.change_orders",
      to: "/changeorders",
    },
    {
      id: "value",
      icon: "Calculator",
      inputs: [
        {
          labelKey: "cases.administer_a_variation_under_nzs_3910.step.value.in.instruction",
          label: "Variation instruction issued",
        },
        {
          labelKey: "cases.administer_a_variation_under_nzs_3910.step.value.in.rates",
          label: "Contract rates and schedule",
        },
      ],
      outputs: [
        {
          labelKey: "cases.administer_a_variation_under_nzs_3910.step.value.out.valuation",
          label: "Variation valued",
        },
        {
          labelKey: "cases.administer_a_variation_under_nzs_3910.step.value.out.basis",
          label: "Basis of valuation stated",
        },
      ],
      titleKey: "cases.administer_a_variation_under_nzs_3910.step.value.title",
      titleDefault: "Value it in the order the contract sets, not by negotiation",
      whatKey: "cases.administer_a_variation_under_nzs_3910.step.value.what",
      whatDefault:
        "Work down the contract's order of preference rather than starting at the end of it. Use the contract rates where the varied work is of similar character and carried out under similar conditions. Where it is similar but the conditions differ, derive a rate from the contract rate and say what you adjusted. Only where neither holds do you build a reasonable price from cost with the margins the contract allows, and then the build-up is part of the valuation rather than backup for it.",
      whyKey: "cases.administer_a_variation_under_nzs_3910.step.value.why",
      whyDefault:
        "The order of preference exists so that neither side gets to re-price the job through the variation account. A Contractor that goes straight to cost plus on work the schedule already prices is asking for a better rate than it tendered; a Principal that forces a contract rate onto work being done in genuinely different conditions is taking a discount it never negotiated. Stating which step of the order was used is what makes the valuation reviewable.",
      moduleLabel: "Variations",
      moduleLabelKey: "nav.variations",
      to: "/projects/:projectId/variations",
    },
    {
      id: "notice",
      icon: "ClipboardList",
      inputs: [
        {
          labelKey: "cases.administer_a_variation_under_nzs_3910.step.notice.in.event",
          label: "Event and the date it arose",
        },
        {
          labelKey: "cases.administer_a_variation_under_nzs_3910.step.notice.in.records",
          label: "Site records for the period",
        },
      ],
      outputs: [
        {
          labelKey: "cases.administer_a_variation_under_nzs_3910.step.notice.out.notice",
          label: "Notice given inside the period",
        },
        {
          labelKey: "cases.administer_a_variation_under_nzs_3910.step.notice.out.pack",
          label: "Evidence attached to the claim",
        },
      ],
      titleKey: "cases.administer_a_variation_under_nzs_3910.step.notice.title",
      titleDefault: "Give the notice inside the period and keep what proves it",
      whatKey: "cases.administer_a_variation_under_nzs_3910.step.notice.what",
      whatDefault:
        "Log the date the circumstances arose, give the notice the contract requires within the working days it allows, and attach the records that support it as they are made: the labour and plant on the work, the photographs, the diary entries, the correspondence that shows when each side knew. Keep time and cost as separate claims where the contract treats them separately.",
      whyKey: "cases.administer_a_variation_under_nzs_3910.step.notice.why",
      whyDefault:
        "NZS 3910 is a notice-driven contract. An entitlement that is real on the merits can still fail because it was raised outside the period, and the 2023 edition leans harder on early warning, so silence while a problem develops is itself a position. Records assembled at the end of a job describe what somebody remembers; records kept in the week the work happened describe what happened.",
      moduleLabel: "Claims Evidence",
      moduleLabelKey: "nav.claims_evidence",
      to: "/projects/:projectId/claims-evidence",
    },
    {
      id: "time",
      icon: "GanttChartSquare",
      inputs: [
        {
          labelKey: "cases.administer_a_variation_under_nzs_3910.step.time.in.instruction",
          label: "Variation instruction issued",
        },
        {
          labelKey: "cases.administer_a_variation_under_nzs_3910.step.time.in.programme",
          label: "Accepted programme",
        },
      ],
      outputs: [
        {
          labelKey: "cases.administer_a_variation_under_nzs_3910.step.time.out.effect",
          label: "Effect on the critical path",
        },
        {
          labelKey: "cases.administer_a_variation_under_nzs_3910.step.time.out.eot",
          label: "Extension of time claimed",
        },
      ],
      titleKey: "cases.administer_a_variation_under_nzs_3910.step.time.title",
      titleDefault: "Read the programme effect before the date passes",
      whatKey: "cases.administer_a_variation_under_nzs_3910.step.time.what",
      whatDefault:
        "Put the varied work into the programme and read what it does to the critical path, then claim or determine the extension of time on that basis. Where the variation absorbs float rather than moving the completion date, record that too, because the next event will land on a job with less room than the programme shows.",
      whyKey: "cases.administer_a_variation_under_nzs_3910.step.time.why",
      whyDefault:
        "Cost and time are separate entitlements under this form and they are lost separately. A Contractor paid for a variation and never granted the days it took is a Contractor heading into liquidated damages for a delay the Principal instructed. Reading the effect while the programme is still current is the difference between a demonstrated extension and an argument about what would have happened.",
      moduleLabel: "4D Schedule",
      moduleLabelKey: "nav.schedule",
      to: "/schedule",
    },
    {
      id: "register",
      icon: "FileBarChart",
      inputs: [
        {
          labelKey: "cases.administer_a_variation_under_nzs_3910.step.register.in.valued",
          label: "Variations valued to date",
        },
        {
          labelKey: "cases.administer_a_variation_under_nzs_3910.step.register.in.sum",
          label: "Original contract sum",
        },
      ],
      outputs: [
        {
          labelKey: "cases.administer_a_variation_under_nzs_3910.step.register.out.register",
          label: "Variation register both sides read",
        },
        {
          labelKey: "cases.administer_a_variation_under_nzs_3910.step.register.out.forecast",
          label: "Forecast final contract sum",
        },
      ],
      titleKey: "cases.administer_a_variation_under_nzs_3910.step.register.title",
      titleDefault: "Keep one register both sides are reading",
      whatKey: "cases.administer_a_variation_under_nzs_3910.step.register.what",
      whatDefault:
        "Publish the register: every variation with its instruction, its status, the amount claimed, the amount determined and the days granted, rolled up to a forecast final contract sum. Show the ones still unpriced as well as the settled ones, with a figure against them rather than a blank.",
      whyKey: "cases.administer_a_variation_under_nzs_3910.step.register.why",
      whyDefault:
        "The final account argument on this form is almost never about a single variation. It is about forty of them that two organisations were tracking in two spreadsheets that never agreed, and about the ten nobody priced because they were still open. One register that both sides read each month turns the final account into an arithmetic exercise instead of a negotiation.",
      moduleLabel: "Reports",
      moduleLabelKey: "nav.reports",
      to: "/reports",
    },
  ],
};

export default playbook;
