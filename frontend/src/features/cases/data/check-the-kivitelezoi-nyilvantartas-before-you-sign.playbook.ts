// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Check the kivitelezoi nyilvantartas before you sign" (HU).
//
// Who may lawfully carry out construction work in Hungary is a question with a
// register behind it. A firm that wants to build as a business has to announce
// itself to the body that keeps the vallalkozo kivitelezoi nyilvantartas, and
// the work has to be directed by a felelos muszaki vezeto who is on a register
// of their own. Both are checkable in minutes and both are usually checked
// after the inspection rather than before the contract. Content strings are key
// plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "check-the-kivitelezoi-nyilvantartas-before-you-sign",
  order: 1248,
  region: "HU",
  category: "tendering",
  companyTypes: ["general-contractor", "project-manager", "developer-client", "subcontractor"],
  roles: ["procurement-buyer", "contract-administrator", "commercial-manager", "site-manager"],
  icon: "UserCheck",
  titleKey: "cases.check_the_kivitelezoi_nyilvantartas_before_you_sign.title",
  titleDefault: "Check the kivitelezoi nyilvantartas before you sign",
  descKey: "cases.check_the_kivitelezoi_nyilvantartas_before_you_sign.desc",
  descDefault:
    "Verify that the firm is on the contractors' register and that a qualified felelos muszaki vezeto is named for the work, match the entry to the package you are letting, put both into the written subcontract and keep the check with its date.",
  longDescKey: "cases.check_the_kivitelezoi_nyilvantartas_before_you_sign.longdesc",
  longDescDefault:
    "Under Act C of 2023 on Hungarian architecture, a firm intending to carry out construction work as a business has to meet the conditions set by government decree and announce itself to the body that keeps the register of vallalkozo kivitelezok, which is operated by the Hungarian Chamber of Commerce and Industry and is public. A firm beginning the activity has five working days to get on it. Separately, Government Decree 191/2009 (IX. 15.) requires the work on site to be directed by a felelos muszaki vezeto with the qualification the work calls for, and that person has to appear on the register their own chamber keeps. Neither check takes long. Both are skipped constantly, because the firm was recommended, because they were on the last job, or because the package was let at three days' notice, and the consequences land on the party that signed rather than on the party that was not registered.",
  estMinutes: 11,
  steps: [
    {
      id: "register",
      icon: "SearchCheck",
      inputs: [
        { labelKey: "cases.check_the_kivitelezoi_nyilvantartas_before_you_sign.step.register.in.firm", label: "Firm and company number" },
        { labelKey: "cases.check_the_kivitelezoi_nyilvantartas_before_you_sign.step.register.in.package", label: "Package to be let" },
      ],
      outputs: [
        { labelKey: "cases.check_the_kivitelezoi_nyilvantartas_before_you_sign.step.register.out.entry", label: "Register entry found" },
        { labelKey: "cases.check_the_kivitelezoi_nyilvantartas_before_you_sign.step.register.out.record", label: "Check recorded on the firm" },
      ],
      titleKey: "cases.check_the_kivitelezoi_nyilvantartas_before_you_sign.step.register.title",
      titleDefault: "Find the firm on the contractors' register",
      whatKey: "cases.check_the_kivitelezoi_nyilvantartas_before_you_sign.step.register.what",
      whatDefault:
        "Look the firm up on the public register of vallalkozo kivitelezok kept by the chamber and record on their directory entry that you did, with the date and what you found: registration number, the activities they are registered for and whether the entry is current.",
      whyKey: "cases.check_the_kivitelezoi_nyilvantartas_before_you_sign.step.register.why",
      whyDefault:
        "The register is the only place the question is answered by a fact rather than by an assurance. A firm that has been building for years may still have let its entry lapse, and one that has just started has five working days to appear on it, so an absence at tender time is a question and not automatically a refusal. Recording what you found and when is how the check keeps its value later.",
      moduleLabel: "Subcontractor Directory",
      moduleLabelKey: "nav.subcontractors",
      to: "/subcontractors",
    },
    {
      id: "fmv",
      icon: "UserCheck",
      inputs: [
        { labelKey: "cases.check_the_kivitelezoi_nyilvantartas_before_you_sign.step.fmv.in.person", label: "Named felelos muszaki vezeto" },
        { labelKey: "cases.check_the_kivitelezoi_nyilvantartas_before_you_sign.step.fmv.in.work", label: "Nature of the work" },
      ],
      outputs: [
        { labelKey: "cases.check_the_kivitelezoi_nyilvantartas_before_you_sign.step.fmv.out.verified", label: "Registration verified" },
        { labelKey: "cases.check_the_kivitelezoi_nyilvantartas_before_you_sign.step.fmv.out.contact", label: "Contact on the project" },
      ],
      titleKey: "cases.check_the_kivitelezoi_nyilvantartas_before_you_sign.step.fmv.title",
      titleDefault: "Check the felelos muszaki vezeto by name",
      whatKey: "cases.check_the_kivitelezoi_nyilvantartas_before_you_sign.step.fmv.what",
      whatDefault:
        "Get the name of the person who will direct the work, check that their chamber registration covers this kind of work, and put them on the project as a contact with the role recorded rather than leaving the firm to identify them after mobilisation.",
      whyKey: "cases.check_the_kivitelezoi_nyilvantartas_before_you_sign.step.fmv.why",
      whyDefault:
        "Government Decree 191/2009 (IX. 15.) puts the direction of the works on a felelos muszaki vezeto with the right qualification, and that person signs entries in the naplo and the declarations at completion. A firm that cannot name one before the contract will name one late, or will name somebody who is covering four other sites, and the shortfall shows up as a naplo nobody is signing.",
      moduleLabel: "Contacts",
      moduleLabelKey: "contacts.title",
      to: "/contacts",
    },
    {
      id: "scope",
      icon: "Crosshair",
      inputs: [
        { labelKey: "cases.check_the_kivitelezoi_nyilvantartas_before_you_sign.step.scope.in.entry", label: "Register entry" },
        { labelKey: "cases.check_the_kivitelezoi_nyilvantartas_before_you_sign.step.scope.in.scope", label: "Package scope" },
      ],
      outputs: [
        { labelKey: "cases.check_the_kivitelezoi_nyilvantartas_before_you_sign.step.scope.out.match", label: "Scope matched to the entry" },
        { labelKey: "cases.check_the_kivitelezoi_nyilvantartas_before_you_sign.step.scope.out.gaps", label: "Work outside the entry flagged" },
      ],
      titleKey: "cases.check_the_kivitelezoi_nyilvantartas_before_you_sign.step.scope.title",
      titleDefault: "Match the entry to the work you are letting",
      whatKey: "cases.check_the_kivitelezoi_nyilvantartas_before_you_sign.step.scope.what",
      whatDefault:
        "Compare what the firm is registered for against what your package actually contains, and flag the parts that fall outside it. Decide before award whether those parts come out of the package, go to somebody else, or are covered by a specialist the firm will engage.",
      whyKey: "cases.check_the_kivitelezoi_nyilvantartas_before_you_sign.step.scope.why",
      whyDefault:
        "A registration is not a general licence, and the mismatch is usually at the edges: the groundworker who also has a small amount of structural work, the fit-out firm carrying two days of electrical. Finding it at award is a scope conversation. Finding it on site is a stoppage, and the work already done still has to be signed off by somebody.",
      moduleLabel: "Procurement",
      moduleLabelKey: "procurement.title",
      to: "/projects/:projectId/procurement",
    },
    {
      id: "contract",
      icon: "FileSignature",
      inputs: [
        { labelKey: "cases.check_the_kivitelezoi_nyilvantartas_before_you_sign.step.contract.in.verified", label: "Verified firm and person" },
        { labelKey: "cases.check_the_kivitelezoi_nyilvantartas_before_you_sign.step.contract.in.kiiras", label: "Priced tetel list" },
      ],
      outputs: [
        { labelKey: "cases.check_the_kivitelezoi_nyilvantartas_before_you_sign.step.contract.out.contract", label: "Written kivitelezesi szerzodes" },
        { labelKey: "cases.check_the_kivitelezoi_nyilvantartas_before_you_sign.step.contract.out.annexes", label: "Annexes attached" },
      ],
      titleKey: "cases.check_the_kivitelezoi_nyilvantartas_before_you_sign.step.contract.title",
      titleDefault: "Put it in the written contract, with its annexes",
      whatKey: "cases.check_the_kivitelezoi_nyilvantartas_before_you_sign.step.contract.what",
      whatDefault:
        "Write the subcontract with the content the Epkiv. requires, name the felelos muszaki vezeto in it, and attach the itemised bill and the other annexes the decree lists. Include the obligation to keep the registration current and to tell you if it changes.",
      whyKey: "cases.check_the_kivitelezoi_nyilvantartas_before_you_sign.step.contract.why",
      whyDefault:
        "Government Decree 191/2009 (IX. 15.) requires the kivitelezesi szerzodes to be in writing and says what it carries, so a package let on an email and a price is not a contract that satisfies the decree. It is also the document a payment dispute is read against, and the annexes are the half of it that decides what was in the price.",
      moduleLabel: "Contracts",
      moduleLabelKey: "nav.contracts",
      to: "/projects/:projectId/contracts",
    },
    {
      id: "chain",
      icon: "Network",
      inputs: [
        { labelKey: "cases.check_the_kivitelezoi_nyilvantartas_before_you_sign.step.chain.in.contract", label: "Signed subcontract" },
        { labelKey: "cases.check_the_kivitelezoi_nyilvantartas_before_you_sign.step.chain.in.lower", label: "Firms below them" },
      ],
      outputs: [
        { labelKey: "cases.check_the_kivitelezoi_nyilvantartas_before_you_sign.step.chain.out.chain", label: "Contractor chain on record" },
        { labelKey: "cases.check_the_kivitelezoi_nyilvantartas_before_you_sign.step.chain.out.naplo", label: "Alnaplo obligations set" },
      ],
      titleKey: "cases.check_the_kivitelezoi_nyilvantartas_before_you_sign.step.chain.title",
      titleDefault: "Keep the chain below them visible too",
      whatKey: "cases.check_the_kivitelezoi_nyilvantartas_before_you_sign.step.chain.what",
      whatDefault:
        "Record who this firm will use under it, apply the same two checks to those firms, and make the alnaplo obligation part of the package so every contractor in the chain shows up in the site record rather than only in the payment chain.",
      whyKey: "cases.check_the_kivitelezoi_nyilvantartas_before_you_sign.step.chain.why",
      whyDefault:
        "The chain is where the risk actually sits, because a firm you checked can engage one you did not, and on a Hungarian site the naplo is where that becomes visible. It also matters commercially: an unregistered firm two levels down is still working on your site, and its claim for payment lands in your chain when the firm above it fails.",
      moduleLabel: "Subcontractor Directory",
      moduleLabelKey: "nav.subcontractors",
      to: "/projects/:projectId/subcontractors",
    },
    {
      id: "check",
      icon: "ShieldCheck",
      inputs: [
        { labelKey: "cases.check_the_kivitelezoi_nyilvantartas_before_you_sign.step.check.in.package", label: "Award package" },
        { labelKey: "cases.check_the_kivitelezoi_nyilvantartas_before_you_sign.step.check.in.checks", label: "Recorded checks" },
      ],
      outputs: [
        { labelKey: "cases.check_the_kivitelezoi_nyilvantartas_before_you_sign.step.check.out.report", label: "Validation report" },
        { labelKey: "cases.check_the_kivitelezoi_nyilvantartas_before_you_sign.step.check.out.clear", label: "Cleared for award" },
      ],
      titleKey: "cases.check_the_kivitelezoi_nyilvantartas_before_you_sign.step.check.title",
      titleDefault: "Run the checks as a gate, not as a habit",
      whatKey: "cases.check_the_kivitelezoi_nyilvantartas_before_you_sign.step.check.what",
      whatDefault:
        "Before award, validate that the package has what it needs: a current register entry, a named and registered felelos muszaki vezeto, a scope that matches the entry, insurance where the contract requires it, and a written contract with its annexes attached.",
      whyKey: "cases.check_the_kivitelezoi_nyilvantartas_before_you_sign.step.check.why",
      whyDefault:
        "These checks are individually trivial and collectively the thing nobody has time for at the moment a package is awarded, which is always late and always under pressure. Making them a gate rather than a good intention is the only version that survives a busy month, and a busy month is when the risky award happens.",
      moduleLabel: "Validation",
      moduleLabelKey: "validation.title",
      to: "/validation",
    },
    {
      id: "record",
      icon: "FileStack",
      inputs: [
        { labelKey: "cases.check_the_kivitelezoi_nyilvantartas_before_you_sign.step.record.in.evidence", label: "Register and registration evidence" },
        { labelKey: "cases.check_the_kivitelezoi_nyilvantartas_before_you_sign.step.record.in.contract", label: "Signed contract set" },
      ],
      outputs: [
        { labelKey: "cases.check_the_kivitelezoi_nyilvantartas_before_you_sign.step.record.out.pack", label: "Dated evidence pack" },
        { labelKey: "cases.check_the_kivitelezoi_nyilvantartas_before_you_sign.step.record.out.review", label: "Re-check scheduled" },
      ],
      titleKey: "cases.check_the_kivitelezoi_nyilvantartas_before_you_sign.step.record.title",
      titleDefault: "Keep the check with the date you made it",
      whatKey: "cases.check_the_kivitelezoi_nyilvantartas_before_you_sign.step.record.what",
      whatDefault:
        "File what you looked at, not just the conclusion: the register entry as it read on the day, the felelos muszaki vezeto's registration, the contract and its annexes. On a long job, set a date to look again.",
      whyKey: "cases.check_the_kivitelezoi_nyilvantartas_before_you_sign.step.record.why",
      whyDefault:
        "A register entry is a fact about a day rather than a permanent state, and a firm can be removed from it while it is on your site. The dated evidence is what shows you checked before you signed rather than after somebody asked, and that distinction is the whole point of having done it.",
      moduleLabel: "Documents",
      moduleLabelKey: "nav.documents",
      to: "/projects/:projectId/files",
    },
  ],
};

export default playbook;
