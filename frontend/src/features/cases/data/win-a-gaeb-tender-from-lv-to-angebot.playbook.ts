// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Win a GAEB tender, from the LV to the Angebot" (DE).
//
// The German bid round as a Kalkulator actually runs it: the tender arrives as
// a GAEB X83, it is imported rather than retyped, every position is priced off
// a stated rate basis, the total is checked, and the offer goes back as a GAEB
// X84 Angebotsabgabe on the same OZ numbering. Content strings are key plus
// inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "win-a-gaeb-tender-from-lv-to-angebot",
  order: 1047,
  region: "DE",
  category: "tendering",
  companyTypes: ["general-contractor", "subcontractor"],
  roles: ["estimator", "quantity-surveyor", "commercial-manager"],
  icon: "Trophy",
  titleKey: "cases.win_a_gaeb_tender_from_lv_to_angebot.title",
  titleDefault: "Win a GAEB tender, from the LV to the Angebot",
  descKey: "cases.win_a_gaeb_tender_from_lv_to_angebot.desc",
  descDefault:
    "Read the client's GAEB X83 tender straight into a bill instead of retyping it, price every position, check the total, and hand the offer back as a GAEB X84 Angebotsabgabe.",
  longDescKey: "cases.win_a_gaeb_tender_from_lv_to_angebot.longdesc",
  longDescDefault:
    "In the German market the tender arrives as a GAEB DA XML file and the offer has to travel back the same way. Importing the X83 keeps the Ordnungszahl, the unit and the quantity exactly as the client issued them, so the only thing you add is your price. The X84 you return carries those same positions back with unit prices and totals, which is what lets the client read your offer into their own system instead of retyping it or setting it aside.",
  estMinutes: 12,
  steps: [
    {
      id: "receive",
      icon: "FolderInput",
      inputs: [
        { labelKey: "cases.win_a_gaeb_tender_from_lv_to_angebot.step.receive.in.file", label: "GAEB X83 file" },
        { labelKey: "cases.win_a_gaeb_tender_from_lv_to_angebot.step.receive.in.docs", label: "Tender documents" },
      ],
      outputs: [
        { labelKey: "cases.win_a_gaeb_tender_from_lv_to_angebot.step.receive.out.filed", label: "Filed tender set" },
        { labelKey: "cases.win_a_gaeb_tender_from_lv_to_angebot.step.receive.out.deadline", label: "Deadline on record" },
      ],
      titleKey: "cases.win_a_gaeb_tender_from_lv_to_angebot.step.receive.title",
      titleDefault: "File the tender documents as received",
      whatKey: "cases.win_a_gaeb_tender_from_lv_to_angebot.step.receive.what",
      whatDefault:
        "Save the GAEB X83 and the rest of the Vergabeunterlagen into the project files exactly as the client sent them, with the date they arrived, the Angebotsfrist and the Bindefrist recorded alongside, because the second one is how long your price has to stand.",
      whyKey: "cases.win_a_gaeb_tender_from_lv_to_angebot.step.receive.why",
      whyDefault:
        "Tenders get corrected and reissued during the bidding period. Keeping the file you actually priced on record is what lets you show, weeks later, which version your offer answers.",
      moduleLabel: "Documents",
      moduleLabelKey: "nav.documents",
      to: "/projects/:projectId/files",
    },
    {
      id: "import",
      icon: "Upload",
      inputs: [
        { labelKey: "cases.win_a_gaeb_tender_from_lv_to_angebot.step.import.in.file", label: "GAEB X83 file" },
        { labelKey: "cases.win_a_gaeb_tender_from_lv_to_angebot.step.import.in.project", label: "Target project" },
      ],
      outputs: [
        { labelKey: "cases.win_a_gaeb_tender_from_lv_to_angebot.step.import.out.bill", label: "Bill with LV positions" },
        { labelKey: "cases.win_a_gaeb_tender_from_lv_to_angebot.step.import.out.oz", label: "OZ and units preserved" },
      ],
      titleKey: "cases.win_a_gaeb_tender_from_lv_to_angebot.step.import.title",
      titleDefault: "Import the X83 as a new LV",
      whatKey: "cases.win_a_gaeb_tender_from_lv_to_angebot.step.import.what",
      whatDefault:
        "Open the Import tab, drop the X83 in, check the preview of the parsed positions, then import them into a new bill named after the tender. The Ordnungszahl, the unit, the quantity and the long text of every position arrive unchanged.",
      whyKey: "cases.win_a_gaeb_tender_from_lv_to_angebot.step.import.why",
      whyDefault:
        "This is the step that removes the retyping. Keying several hundred positions by hand is exactly where a transposed quantity or a dropped position turns into a loss you only notice on site.",
      moduleLabel: "GAEB Exchange",
      moduleLabelKey: "nav.gaeb_exchange",
      to: "/gaeb-exchange",
    },
    {
      id: "rates",
      icon: "Database",
      inputs: [
        { labelKey: "cases.win_a_gaeb_tender_from_lv_to_angebot.step.rates.in.positions", label: "LV positions" },
        { labelKey: "cases.win_a_gaeb_tender_from_lv_to_angebot.step.rates.in.records", label: "Own cost records" },
      ],
      outputs: [
        { labelKey: "cases.win_a_gaeb_tender_from_lv_to_angebot.step.rates.out.basis", label: "Rate basis" },
        { labelKey: "cases.win_a_gaeb_tender_from_lv_to_angebot.step.rates.out.gaps", label: "Missing rates flagged" },
      ],
      titleKey: "cases.win_a_gaeb_tender_from_lv_to_angebot.step.rates.title",
      titleDefault: "Settle the rate basis you price from",
      whatKey: "cases.win_a_gaeb_tender_from_lv_to_angebot.step.rates.what",
      whatDefault:
        "In the cost database, decide which rates this offer is built on, whether that is your own recorded costs or a maintained catalog, and add the items the LV asks for that you do not carry a price for yet.",
      whyKey: "cases.win_a_gaeb_tender_from_lv_to_angebot.step.rates.why",
      whyDefault:
        "A rate whose origin you can name is a rate you can defend if the client asks you to explain it. Fixing the basis up front also stops the same work being priced two different ways inside one offer.",
      moduleLabel: "Cost Database",
      moduleLabelKey: "costs.title",
      to: "/costs",
    },
    {
      id: "price",
      icon: "Calculator",
      inputs: [
        { labelKey: "cases.win_a_gaeb_tender_from_lv_to_angebot.step.price.in.positions", label: "Imported LV positions" },
        { labelKey: "cases.win_a_gaeb_tender_from_lv_to_angebot.step.price.in.basis", label: "Rate basis" },
      ],
      outputs: [
        { labelKey: "cases.win_a_gaeb_tender_from_lv_to_angebot.step.price.out.prices", label: "Unit prices" },
        { labelKey: "cases.win_a_gaeb_tender_from_lv_to_angebot.step.price.out.total", label: "Angebotssumme" },
      ],
      titleKey: "cases.win_a_gaeb_tender_from_lv_to_angebot.step.price.title",
      titleDefault: "Price every position and read the Langtext",
      whatKey: "cases.win_a_gaeb_tender_from_lv_to_angebot.step.price.what",
      whatDefault:
        "Work down the bill and put a unit price on every position, reading the long text as you go so a duty buried in a description is priced rather than discovered later. The bill totals each position and rolls up the Angebotssumme as you type.",
      whyKey: "cases.win_a_gaeb_tender_from_lv_to_angebot.step.price.why",
      whyDefault:
        "The long text is where the risk sits: a wording that quietly hands you the substrate, the disposal or the working hours. Catching it while you price costs minutes, catching it on site costs the margin.",
      moduleLabel: "Bill of Quantities",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "check",
      icon: "ShieldCheck",
      inputs: [
        { labelKey: "cases.win_a_gaeb_tender_from_lv_to_angebot.step.check.in.priced", label: "Priced bill" },
        { labelKey: "cases.win_a_gaeb_tender_from_lv_to_angebot.step.check.in.lv", label: "Original LV" },
      ],
      outputs: [
        { labelKey: "cases.win_a_gaeb_tender_from_lv_to_angebot.step.check.out.report", label: "Validation report" },
        { labelKey: "cases.win_a_gaeb_tender_from_lv_to_angebot.step.check.out.cleared", label: "Findings cleared" },
      ],
      titleKey: "cases.win_a_gaeb_tender_from_lv_to_angebot.step.check.title",
      titleDefault: "Check the offer before it leaves the house",
      whatKey: "cases.win_a_gaeb_tender_from_lv_to_angebot.step.check.what",
      whatDefault:
        "Run validation over the priced bill and clear what it finds: a position still standing at zero, a quantity or unit that drifted away from the LV, a structure rule the return file has to honour. Then check the Angebotssumme for plausibility against a job of this size.",
      whyKey: "cases.win_a_gaeb_tender_from_lv_to_angebot.step.check.why",
      whyDefault:
        "One unpriced position can take the whole offer out of the evaluation, and a total that is out by a decimal place is worse than losing the job. These five minutes are the cheapest insurance in the entire tender.",
      moduleLabel: "Validation",
      moduleLabelKey: "validation.title",
      to: "/validation",
    },
    {
      id: "export",
      icon: "FileOutput",
      inputs: [
        { labelKey: "cases.win_a_gaeb_tender_from_lv_to_angebot.step.export.in.priced", label: "Validated priced bill" },
        { labelKey: "cases.win_a_gaeb_tender_from_lv_to_angebot.step.export.in.bidder", label: "Bidder details" },
      ],
      outputs: [
        { labelKey: "cases.win_a_gaeb_tender_from_lv_to_angebot.step.export.out.x84", label: "GAEB X84 Hauptangebot" },
        { labelKey: "cases.win_a_gaeb_tender_from_lv_to_angebot.step.export.out.totals", label: "Offer totals" },
      ],
      titleKey: "cases.win_a_gaeb_tender_from_lv_to_angebot.step.export.title",
      titleDefault: "Export the Angebotsabgabe as X84",
      whatKey: "cases.win_a_gaeb_tender_from_lv_to_angebot.step.export.what",
      whatDefault:
        "Switch to the Export tab, pick the priced bill and choose the X84 format. What you get back is the Angebotsabgabe: your Bieter details, a unit price and a total on each position, and the offer totals, all on the same Ordnungszahl you were sent.",
      whyKey: "cases.win_a_gaeb_tender_from_lv_to_angebot.step.export.why",
      whyDefault:
        "X84 is the exchange phase the client's software expects an offer to arrive in. Returning the numbering they issued means your prices load straight into their Preisspiegel instead of being retyped or set aside.",
      moduleLabel: "GAEB Exchange",
      moduleLabelKey: "nav.gaeb_exchange",
      to: "/gaeb-exchange",
    },
    {
      id: "submit",
      icon: "Send",
      inputs: [
        { labelKey: "cases.win_a_gaeb_tender_from_lv_to_angebot.step.submit.in.x84", label: "GAEB X84 Hauptangebot" },
        { labelKey: "cases.win_a_gaeb_tender_from_lv_to_angebot.step.submit.in.forms", label: "Completed tender forms" },
      ],
      outputs: [
        { labelKey: "cases.win_a_gaeb_tender_from_lv_to_angebot.step.submit.out.angebot", label: "Submitted Angebot" },
        { labelKey: "cases.win_a_gaeb_tender_from_lv_to_angebot.step.submit.out.record", label: "Submission record" },
      ],
      titleKey: "cases.win_a_gaeb_tender_from_lv_to_angebot.step.submit.title",
      titleDefault: "Submit the Angebot and log what went out",
      whatKey: "cases.win_a_gaeb_tender_from_lv_to_angebot.step.submit.what",
      whatDefault:
        "Assemble the X84 with the completed tender forms and any Nebenangebot the tender allows into one submission. On a public VOB/A tender it goes up through the Vergabeplattform in Textform before the Angebotsfrist, not by e-mail; on a private tender send it the way the Anfrage asked. Keep the record of what went out, to whom and when.",
      whyKey: "cases.win_a_gaeb_tender_from_lv_to_angebot.step.submit.why",
      whyDefault:
        "A strong price inside an incomplete or late submission is not a price, it is an exclusion. The dated record of what you sent is also the starting point for any Nachtrag discussion once you win.",
      moduleLabel: "Transmittals",
      moduleLabelKey: "transmittals.title",
      to: "/files/transmittals",
    },
  ],
};

export default playbook;
