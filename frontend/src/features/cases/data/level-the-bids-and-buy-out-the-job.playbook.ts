// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Level the bids and buy out the job" (US).
//
// The objection is "our spreadsheet process has worked for years", and it has.
// The answer is not migration. Subcontractor bids arrive as spreadsheets and
// PDFs on bid day and always will, so the case takes them in that form and
// spends its effort on the part a spreadsheet is genuinely bad at: holding
// several bids against one scope and carrying the chosen one into a commitment
// without retyping it.
//
// The US-specific weight is bid day itself, and the leveling sheet that comes
// out of it. Scope gaps between bidders are priced rather than argued, and the
// award has to survive the buyout that follows it. Terminology is en-US
// throughout: bidders, leveling, scope gaps, buyout, commitment. Content
// strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "level-the-bids-and-buy-out-the-job",
  order: 1064,
  region: "US",
  category: "tendering",
  companyTypes: ["general-contractor", "cost-consultant", "project-manager"],
  roles: ["estimator", "procurement-buyer", "commercial-manager", "project-manager"],
  icon: "Scale",
  titleKey: "cases.level_the_bids_and_buy_out_the_job.title",
  titleDefault: "Level the bids and buy out the job",
  descKey: "cases.level_the_bids_and_buy_out_the_job.desc",
  descDefault:
    "Invite bidders against a written scope, take their spreadsheets in the form they send them, level everyone onto one scope so the numbers can be compared, award on a recommendation that prices the gaps, and carry the winner into a commitment without retyping it.",
  longDescKey: "cases.level_the_bids_and_buy_out_the_job.longdesc",
  longDescDefault:
    "Bid day works on spreadsheets because spreadsheets are what arrive, and no estimator is going to ask fourteen subcontractors to learn a portal the week of a bid. So this case does not replace the spreadsheet, it takes it as input. What it replaces is the part that fails quietly: three bids that look comparable because they are all one number, where one excluded the hoisting, one carried the permit and one priced a different specification section, and the cheapest turns out to be the most expensive by the time it is bought out. Leveling makes the exclusions visible while there is still time to price them, and the award carries into the subcontract as the same document rather than as a fresh transcription with fresh typos.",
  estMinutes: 22,
  steps: [
    {
      id: "invite",
      icon: "Send",
      inputs: [
        { labelKey: "cases.level_the_bids_and_buy_out_the_job.step.invite.in.scope", label: "Scope of work per trade package" },
        { labelKey: "cases.level_the_bids_and_buy_out_the_job.step.invite.in.bidders", label: "Bidder list with contacts" },
      ],
      outputs: [
        { labelKey: "cases.level_the_bids_and_buy_out_the_job.step.invite.out.sent", label: "Invitations sent and tracked" },
        { labelKey: "cases.level_the_bids_and_buy_out_the_job.step.invite.out.questions", label: "Questions answered to everyone at once" },
      ],
      titleKey: "cases.level_the_bids_and_buy_out_the_job.step.invite.title",
      titleDefault: "Invite against a scope, not against a drawing set",
      whatKey: "cases.level_the_bids_and_buy_out_the_job.step.invite.what",
      whatDefault:
        "Write the scope for each trade package, listing what is included and what is explicitly excluded, and invite the bidders against it. Answer questions in one place so every bidder gets the same answer at the same time.",
      whyKey: "cases.level_the_bids_and_buy_out_the_job.step.invite.why",
      whyDefault:
        "Bidders left to infer the scope from a drawing set will each infer a slightly different one, and the differences do not show up until leveling, when there is no time to resolve them. A written scope is what makes the bids comparable later, and it costs an hour now instead of a change order in the fall.",
      moduleLabel: "Bid Management",
      moduleLabelKey: "nav.bid_management",
      to: "/bid-management",
    },
    {
      id: "receive",
      icon: "FileSpreadsheet",
      inputs: [
        { labelKey: "cases.level_the_bids_and_buy_out_the_job.step.receive.in.sheets", label: "Bid spreadsheets as they arrive" },
        { labelKey: "cases.level_the_bids_and_buy_out_the_job.step.receive.in.quals", label: "Qualifications and exclusions" },
      ],
      outputs: [
        { labelKey: "cases.level_the_bids_and_buy_out_the_job.step.receive.out.loaded", label: "Bids loaded without retyping" },
        { labelKey: "cases.level_the_bids_and_buy_out_the_job.step.receive.out.log", label: "Time of receipt on record" },
      ],
      titleKey: "cases.level_the_bids_and_buy_out_the_job.step.receive.title",
      titleDefault: "Take the bids in the form the subs actually send them",
      whatKey: "cases.level_the_bids_and_buy_out_the_job.step.receive.what",
      whatDefault:
        "Import each bid from the spreadsheet it arrived in and attach the qualification letter with it, so the exclusions travel alongside the number rather than living in somebody's inbox.",
      whyKey: "cases.level_the_bids_and_buy_out_the_job.step.receive.why",
      whyDefault:
        "Asking bidders to change how they submit is how a process dies on the day it matters most. Meeting them where they are costs nothing on bid day and still gets the numbers into one place, which is the only part that was ever hard.",
      moduleLabel: "Bid Management",
      moduleLabelKey: "nav.bid_management",
      to: "/bid-management",
    },
    {
      id: "level",
      icon: "Scale",
      inputs: [
        { labelKey: "cases.level_the_bids_and_buy_out_the_job.step.level.in.bids", label: "All bids for one package" },
        { labelKey: "cases.level_the_bids_and_buy_out_the_job.step.level.in.scope", label: "The scope they were invited against" },
      ],
      outputs: [
        { labelKey: "cases.level_the_bids_and_buy_out_the_job.step.level.out.matrix", label: "Bids side by side on one scope" },
        { labelKey: "cases.level_the_bids_and_buy_out_the_job.step.level.out.gaps", label: "Scope gaps priced, not argued" },
      ],
      titleKey: "cases.level_the_bids_and_buy_out_the_job.step.level.title",
      titleDefault: "Level everyone onto the same scope",
      whatKey: "cases.level_the_bids_and_buy_out_the_job.step.level.what",
      whatDefault:
        "Set the bids side by side against the invited scope, mark what each one excluded, and carry a price for every gap so the comparison is between complete scopes rather than between headline numbers.",
      whyKey: "cases.level_the_bids_and_buy_out_the_job.step.level.why",
      whyDefault:
        "The low bid is frequently the one that left the most out, and that is not dishonesty, it is two readings of the same drawings. Pricing the gaps is what turns three incomparable numbers into a decision, and it is the step a spreadsheet handles worst because the exclusions live in a letter and the numbers live in cells.",
      moduleLabel: "Tenders",
      moduleLabelKey: "tenders.title",
      to: "/tenders",
    },
    {
      id: "award",
      icon: "Gavel",
      inputs: [
        { labelKey: "cases.level_the_bids_and_buy_out_the_job.step.award.in.levelled", label: "The levelled comparison" },
        { labelKey: "cases.level_the_bids_and_buy_out_the_job.step.award.in.checks", label: "References, capacity, bonding" },
      ],
      outputs: [
        { labelKey: "cases.level_the_bids_and_buy_out_the_job.step.award.out.recommendation", label: "Award recommendation with reasons" },
        { labelKey: "cases.level_the_bids_and_buy_out_the_job.step.award.out.record", label: "Why the others were not chosen" },
      ],
      titleKey: "cases.level_the_bids_and_buy_out_the_job.step.award.title",
      titleDefault: "Recommend an award somebody can audit",
      whatKey: "cases.level_the_bids_and_buy_out_the_job.step.award.what",
      whatDefault:
        "Produce the recommendation from the levelled comparison, stating the adjusted total for each bidder and the reason the selected one was chosen, alongside capacity and bonding checks where the package warrants them.",
      whyKey: "cases.level_the_bids_and_buy_out_the_job.step.award.why",
      whyDefault:
        "On public and institutional work the reasoning gets read by somebody who was not in the room, sometimes months later. Writing it down while the comparison is in front of you takes minutes; reconstructing it from memory after a protest takes days and convinces nobody.",
      moduleLabel: "Tenders",
      moduleLabelKey: "tenders.title",
      to: "/tenders",
    },
    {
      id: "buyout",
      icon: "Package",
      inputs: [
        { labelKey: "cases.level_the_bids_and_buy_out_the_job.step.buyout.in.selected", label: "The selected bid and its scope" },
        { labelKey: "cases.level_the_bids_and_buy_out_the_job.step.buyout.in.terms", label: "Contract terms and retainage" },
      ],
      outputs: [
        { labelKey: "cases.level_the_bids_and_buy_out_the_job.step.buyout.out.commitment", label: "Subcontract or purchase order issued" },
        { labelKey: "cases.level_the_bids_and_buy_out_the_job.step.buyout.out.delta", label: "Buyout gain or loss against the estimate" },
      ],
      titleKey: "cases.level_the_bids_and_buy_out_the_job.step.buyout.title",
      titleDefault: "Buy it out without retyping it",
      whatKey: "cases.level_the_bids_and_buy_out_the_job.step.buyout.what",
      whatDefault:
        "Turn the selected bid into a commitment, carrying the levelled scope and the priced gaps into the subcontract, and compare the committed value against the estimate line it came from.",
      whyKey: "cases.level_the_bids_and_buy_out_the_job.step.buyout.why",
      whyDefault:
        "The scope that was levelled is the scope that has to be bought, and a subcontract retyped from the bid letter quietly drops the exclusions that leveling just made visible. Comparing the commitment to the estimate also tells you the buyout result per package while you can still act on it, instead of at the end of the job when it is only history.",
      moduleLabel: "Procurement",
      moduleLabelKey: "procurement.title",
      to: "/procurement",
    },
  ],
};

export default playbook;
