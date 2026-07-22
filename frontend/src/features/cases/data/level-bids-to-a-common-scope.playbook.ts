// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Level bids to a common scope".
//
// Normalise structurally different bids - filling scope gaps and pricing
// qualifications - so every offer sits on the same basis before you compare the
// bottom lines. Content strings are key plus inline English default, only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "level-bids-to-a-common-scope",
  order: 1007,
  category: "tendering",
  companyTypes: ["general-contractor", "cost-consultant", "project-manager"],
  icon: "Scale",
  titleKey: "cases.level_bids_to_a_common_scope.title",
  titleDefault: "Level bids to a common scope",
  descKey: "cases.level_bids_to_a_common_scope.desc",
  descDefault:
    "Normalise structurally different bids - filling the scope gaps and pricing the qualifications - so every offer sits on the same basis before you compare the bottom lines and pick the real lowest.",
  longDescKey: "cases.level_bids_to_a_common_scope.longdesc",
  longDescDefault:
    "The lowest headline bid is rarely the cheapest job. One firm excluded the scaffold, another qualified the ground, a third missed a whole section. Leveling puts them all on a like-for-like footing so the number you award is the number you actually pay.",
  estMinutes: 12,
  steps: [
    {
      id: "collect",
      icon: "FolderOpen",
      inputs: [
        { labelKey: "cases.level_bids_to_a_common_scope.step.collect.in.bids", label: "Returned bids" },
        { labelKey: "cases.level_bids_to_a_common_scope.step.collect.in.quals", label: "Qualifications" },
      ],
      outputs: [
        { labelKey: "cases.level_bids_to_a_common_scope.step.collect.out.set", label: "Bid set assembled" },
      ],
      titleKey: "cases.level_bids_to_a_common_scope.step.collect.title",
      titleDefault: "Collect the bids",
      whatKey: "cases.level_bids_to_a_common_scope.step.collect.what",
      whatDefault:
        "Gather every returned bid with the covering letter, the priced schedule and the qualifications each firm attached, so nothing that conditions a price is left in an inbox.",
      whyKey: "cases.level_bids_to_a_common_scope.step.collect.why",
      whyDefault:
        "The qualifications are where the real differences hide. A bid read without its conditions is a number without a meaning, and half the leveling work is just finding them.",
      moduleLabel: "Bid Management",
      moduleLabelKey: "nav.bid_management",
      to: "/bid-management",
    },
    {
      id: "gaps",
      icon: "GitCompare",
      inputs: [
        { labelKey: "cases.level_bids_to_a_common_scope.step.gaps.in.set", label: "Bid set" },
        { labelKey: "cases.level_bids_to_a_common_scope.step.gaps.in.scope", label: "Common scope" },
      ],
      outputs: [
        { labelKey: "cases.level_bids_to_a_common_scope.step.gaps.out.gaps", label: "Scope gaps flagged" },
      ],
      titleKey: "cases.level_bids_to_a_common_scope.step.gaps.title",
      titleDefault: "Map each bid to the scope",
      whatKey: "cases.level_bids_to_a_common_scope.step.gaps.what",
      whatDefault:
        "Set each bid against the common scope and flag what is missing, what is extra and where a firm has priced something different from what was asked.",
      whyKey: "cases.level_bids_to_a_common_scope.step.gaps.why",
      whyDefault:
        "A gap you spot now is a negotiation; a gap you miss becomes a variation the day after award. Mapping to a single scope is what turns apples and oranges back into apples.",
      moduleLabel: "Bid Management",
      moduleLabelKey: "nav.bid_management",
      to: "/bid-management",
    },
    {
      id: "adjust",
      icon: "Scale",
      inputs: [
        { labelKey: "cases.level_bids_to_a_common_scope.step.adjust.in.gaps", label: "Scope gaps" },
      ],
      outputs: [
        { labelKey: "cases.level_bids_to_a_common_scope.step.adjust.out.levelled", label: "Levelled bids" },
      ],
      titleKey: "cases.level_bids_to_a_common_scope.step.adjust.title",
      titleDefault: "Adjust to one basis",
      whatKey: "cases.level_bids_to_a_common_scope.step.adjust.what",
      whatDefault:
        "Price the gaps and the qualifications into each bid as adjustments, so every offer is restated as what it would cost to deliver the full common scope.",
      whyKey: "cases.level_bids_to_a_common_scope.step.adjust.why",
      whyDefault:
        "Adjusting rather than disqualifying keeps a strong contractor in the race even if their bid was scrappy. It is the fairest and the sharpest way to find the true lowest cost.",
      moduleLabel: "Bid Management",
      moduleLabelKey: "nav.bid_management",
      to: "/bid-management",
    },
    {
      id: "compare",
      icon: "FileBarChart",
      inputs: [
        { labelKey: "cases.level_bids_to_a_common_scope.step.compare.in.levelled", label: "Levelled bids" },
        { labelKey: "cases.level_bids_to_a_common_scope.step.compare.in.budget", label: "Budget baseline" },
      ],
      outputs: [
        { labelKey: "cases.level_bids_to_a_common_scope.step.compare.out.recommend", label: "Award recommendation" },
      ],
      titleKey: "cases.level_bids_to_a_common_scope.step.compare.title",
      titleDefault: "Compare and recommend",
      whatKey: "cases.level_bids_to_a_common_scope.step.compare.what",
      whatDefault:
        "Compare the levelled bids against each other and the budget, then write the recommendation on the offer that is genuinely lowest for the full scope, not just cheapest on paper.",
      whyKey: "cases.level_bids_to_a_common_scope.step.compare.why",
      whyDefault:
        "A recommendation built on levelled numbers survives challenge. It shows the client you compared like for like and awarded on value rather than on whoever forgot the most.",
      moduleLabel: "Tendering",
      moduleLabelKey: "tendering.title",
      to: "/tendering",
    },
  ],
};

export default playbook;
