// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// How-it-works catalog — Commercial + Procurement & change domains.
// See ../types.ts for the shape + key convention, and
// ../catalog/overview-estimating.ts for a fully-worked example.

import type { ModuleExplanation } from '../types';

export const commercialProcurementModules: ModuleExplanation[] = [
  /* ── Commercial ───────────────────────────────────────────────────────── */
  {
    id: 'crm',
    route: '/crm',
    icon: 'Handshake',
    category: 'commercial',
    keywords: 'leads deals opportunities pipeline sales kanban clients win loss',
    titleKey: 'howto.crm.title',
    titleDefault: 'CRM',
    summaryKey: 'howto.crm.summary',
    summaryDefault: 'Track leads, clients and deals across a drag-and-drop sales pipeline.',
    whatKey: 'howto.crm.what',
    whatDefault:
      'CRM is where new work comes from. It holds your leads, the companies behind them and the deals you are chasing, laid out as a Kanban pipeline so you can see every opportunity and its stage at a glance. People and companies are shared with Contacts, and a won deal links to its delivery project and flows on to bid packages and contracts.',
    how: [
      { key: 'howto.crm.how.1', default: 'Capture an inbound enquiry as a lead, qualify it, then convert the good ones into deals.' },
      { key: 'howto.crm.how.2', default: 'Drag a deal card from column to column to move its stage - qualification, proposal, negotiation and on - in a single click.' },
      { key: 'howto.crm.how.3', default: 'Open a deal to log a call, meeting or note, attach the contact and link the delivery project.' },
      { key: 'howto.crm.how.4', default: 'Close a deal as won or lost with a reason; a won deal hands off to Bid Management and Contracts.' },
      { key: 'howto.crm.how.5', default: 'Use the Insights tab to read pipeline value, weighted forecast and win-loss reasons.' },
    ],
    tips: [
      { key: 'howto.crm.tip.1', default: 'Won and lost stages are not drag targets - open the deal and use the Win or Lose buttons so a reason is always recorded.' },
      { key: 'howto.crm.tip.2', default: 'People live in Contacts, not here - attach an existing contact to a deal rather than retyping their details.' },
    ],
    whenKey: 'howto.crm.when',
    whenDefault: 'Use it from first enquiry to signed work, to keep every opportunity moving and nothing slipping through the cracks.',
  },
  {
    id: 'contracts',
    route: '/contracts',
    icon: 'FileSignature',
    category: 'commercial',
    keywords: 'head contract schedule of values progress claims certificate retention final account counterparty',
    titleKey: 'howto.contracts.title',
    titleDefault: 'Contracts',
    summaryKey: 'howto.contracts.summary',
    summaryDefault: 'Run the contract end to end: value, schedule of values, progress claims and final account.',
    whatKey: 'howto.contracts.what',
    whatDefault:
      'Contracts holds each commercial agreement on the project - with the client or with a subcontractor - and keeps its sum honest from signing to settlement. Every contract carries a type, a schedule of values, retention rules and a lifecycle. You bill the work through progress claims and close it out in the final account.',
    how: [
      { key: 'howto.contracts.how.1', default: 'Create a contract, pick its type and counterparty, and the engine wires up the matching schedule of values and retention.' },
      { key: 'howto.contracts.how.2', default: 'Sign it through the compliance gate, then suspend, resume, close or terminate it as the work progresses.' },
      { key: 'howto.contracts.how.3', default: 'Raise progress claims against the schedule of values and move each one through submit, approve, certify and paid.' },
      { key: 'howto.contracts.how.4', default: 'Watch the headline figures - value, paid to date, retention held and outstanding - update as claims are certified.' },
      { key: 'howto.contracts.how.5', default: 'Settle closed contracts in the Final Accounts tab once they are completed or terminated.' },
    ],
    tips: [
      { key: 'howto.contracts.tip.1', default: 'Variations adjust the contract sum mid-flight and approved claims push their net due into Finance, so what you signed and what you owe never drift apart.' },
      { key: 'howto.contracts.tip.2', default: 'Certify and Mark paid are reserved for managers - editors can submit and approve, but the final money steps are gated.' },
    ],
    whenKey: 'howto.contracts.when',
    whenDefault: 'Use it once an award is agreed, to bill and govern the deal through to the final account.',
  },
  {
    id: 'subcontractors',
    route: '/subcontractors',
    icon: 'Users',
    category: 'commercial',
    keywords: 'subcontract packages supply chain prequalification insurance certificate lien waiver retention ratings',
    titleKey: 'howto.subcontractors.title',
    titleDefault: 'Subcontractors',
    summaryKey: 'howto.subcontractors.summary',
    summaryDefault: 'Manage the firms doing the work: prequalification, scopes, payments and ratings.',
    whatKey: 'howto.subcontractors.what',
    whatDefault:
      'Subcontractors is your supply-chain register. It holds each firm with its insurance and certificate status, subcontract scopes, payment applications, retention and performance ratings. Prequalification and lien waivers gate who can be invited to bid and who can be paid, so an expired certificate or a missing waiver stops the award before it happens.',
    how: [
      { key: 'howto.subcontractors.how.1', default: 'Add a subcontractor and record its trade, insurance and certificate details.' },
      { key: 'howto.subcontractors.how.2', default: 'Run prequalification so only firms that are actually qualified can be invited to bid packages.' },
      { key: 'howto.subcontractors.how.3', default: 'Open a firm to manage its scope, payment applications, retention and lien waivers across the tabs.' },
      { key: 'howto.subcontractors.how.4', default: 'Rate performance over time so past delivery feeds your next award decision.' },
    ],
    tips: [
      { key: 'howto.subcontractors.tip.1', default: 'Keep insurance and prequalification current - the gates here decide who Bid Management can invite and who Contracts can pay.' },
    ],
    whenKey: 'howto.subcontractors.when',
    whenDefault: 'Use it before issuing bid packages and throughout delivery to keep the supply chain qualified and paid correctly.',
  },
  {
    id: 'bid-management',
    route: '/bid-management',
    icon: 'FileText',
    category: 'commercial',
    keywords: 'bids tenders packages invitations submissions q and a bid leveling award subcontractor',
    titleKey: 'howto.bid-management.title',
    titleDefault: 'Bid Management',
    summaryKey: 'howto.bid-management.summary',
    summaryDefault: 'Bundle scope into packages, invite subcontractors and level their bids before you award.',
    whatKey: 'howto.bid-management.what',
    whatDefault:
      'Bid Management runs the buy-side tender for subcontract work. You bundle scope into bid packages, invite prequalified subcontractors, collect their priced submissions, handle questions and answers, and level the bids side by side before you award. The award flows straight into Contracts.',
    how: [
      { key: 'howto.bid-management.how.1', default: 'Create a bid package and define the scope you want priced.' },
      { key: 'howto.bid-management.how.2', default: 'Invite prequalified subcontractors from your register, then track who has responded.' },
      { key: 'howto.bid-management.how.3', default: 'Collect priced submissions and answer bidder questions in the Q and A tab.' },
      { key: 'howto.bid-management.how.4', default: 'Level the bids like for like in one view, then award the winner - the award hands off to Contracts.' },
    ],
    tips: [
      { key: 'howto.bid-management.tip.1', default: 'Reach for Tendering instead when you want a formal BOQ-driven tender that writes agreed rates back and raises a purchase order.' },
    ],
    whenKey: 'howto.bid-management.when',
    whenDefault: 'Use it to package and competitively price subcontract scopes before letting them.',
  },
  {
    id: 'tendering',
    route: '/tendering',
    icon: 'FileText',
    category: 'commercial',
    keywords: 'tender package boq issue collect compare offers award rates purchase order leveling addenda',
    titleKey: 'howto.tendering.title',
    titleDefault: 'Tendering',
    summaryKey: 'howto.tendering.summary',
    summaryDefault: 'Take a priced BOQ to market: issue packages, compare offers and award a winner.',
    whatKey: 'howto.tendering.what',
    whatDefault:
      'Tendering builds bid packages straight from a project BOQ, issues them to subcontractors and compares the offers side by side. A tender moves through Draft, Issued, Collecting, Evaluating and Awarded. Awarding a winner writes the agreed rates back to the BOQ and drafts a purchase order in Procurement - the BOQ link is what sets this apart from the subcontractor-package flow in Bid Management.',
    how: [
      { key: 'howto.tendering.how.1', default: 'Pick a project and create a tender package from its BOQ.' },
      { key: 'howto.tendering.how.2', default: 'Issue the package to subcontractors and publish any addenda as the tender period runs.' },
      { key: 'howto.tendering.how.3', default: 'Collect offers, then use the leveling matrix to compare bids line by line on a level basis.' },
      { key: 'howto.tendering.how.4', default: 'Award the winner; the agreed rates flow back to the BOQ and a draft purchase order appears in Procurement.' },
    ],
    tips: [
      { key: 'howto.tendering.tip.1', default: 'Use addenda to issue changes mid-tender so every bidder prices the same scope.' },
    ],
    whenKey: 'howto.tendering.when',
    whenDefault: 'Use it when your priced BOQ needs to go to market and the awarded rates should feed straight back into the estimate and procurement.',
  },

  /* ── Procurement & change ─────────────────────────────────────────────── */
  {
    id: 'variations',
    route: '/variations',
    icon: 'GitCompare',
    category: 'procurement',
    keywords: 'variation notice request order daywork extension of time eot final account scope change claim',
    titleKey: 'howto.variations.title',
    titleDefault: 'Variations',
    summaryKey: 'howto.variations.summary',
    summaryDefault: 'Track changes to scope and price during the works, from notice to agreed order.',
    whatKey: 'howto.variations.what',
    whatDefault:
      'Variations follows a change event during the works: from an early notice, through a priced variation request, to an agreed variation order, with daywork sheets and extension-of-time claims running alongside. On approval the order carries its cost and time impact into the contract final account and rolls up into Finance, so nothing agreed on site is lost at settlement.',
    how: [
      { key: 'howto.variations.how.1', default: 'Raise a variation notice as soon as a change is spotted, to put it on record early.' },
      { key: 'howto.variations.how.2', default: 'Turn it into a priced variation request with the cost and schedule impact set out.' },
      { key: 'howto.variations.how.3', default: 'Agree it as a variation order; record daywork sheets and extension-of-time claims where they apply.' },
      { key: 'howto.variations.how.4', default: 'On approval the order feeds the contract final account and the figure rolls up into Finance.' },
    ],
    tips: [
      { key: 'howto.variations.tip.1', default: 'Raise the notice before the work starts - settling changes early is what keeps them from becoming disputes.' },
      { key: 'howto.variations.tip.2', default: 'A variation is the contractual sibling of a Management of Change item; jump between the two to keep the change-to-cost trail connected.' },
    ],
    whenKey: 'howto.variations.when',
    whenDefault: 'Use it whenever the agreed scope or price changes mid-contract and the impact must be priced and settled.',
  },
  {
    id: 'moc',
    route: '/moc',
    icon: 'Workflow',
    category: 'procurement',
    keywords: 'management of change deviation review approval assessment cost schedule safety quality risk register',
    titleKey: 'howto.moc.title',
    titleDefault: 'Management of Change',
    summaryKey: 'howto.moc.summary',
    summaryDefault: 'Capture, assess and approve a deviation before anyone acts on it.',
    whatKey: 'howto.moc.what',
    whatDefault:
      'Management of Change is the gate that stops a deviation from the agreed design, scope or process from happening informally. Every proposed change is captured with a category and risk level, assessed for its cost, schedule, safety and quality impact, and routed through review and approval before work changes - so there are no surprises at the next valuation.',
    how: [
      { key: 'howto.moc.how.1', default: 'Raise a change request, set its category and risk, and record the headline cost and schedule impact.' },
      { key: 'howto.moc.how.2', default: 'Add impact assessment lines per area so the full effect, not just the headline, is on record.' },
      { key: 'howto.moc.how.3', default: 'Move it to reviewed once it has been technically checked and is ready for a decision.' },
      { key: 'howto.moc.how.4', default: 'Accept or decline it - a declined request is final - then mark it implemented once the change is carried out.' },
    ],
    tips: [
      { key: 'howto.moc.tip.1', default: 'The status flow is enforced for you, so the page only ever offers the transitions that are legal right now.' },
      { key: 'howto.moc.tip.2', default: 'Approved changes flow on to Variations and Change Orders, where the priced commercial instruction lives.' },
    ],
    whenKey: 'howto.moc.when',
    whenDefault: 'Use it as the first gate for any proposed change, before it turns into a priced variation or change order.',
  },
  {
    id: 'supplier-catalogs',
    route: '/supplier-catalogs',
    icon: 'ShoppingCart',
    category: 'procurement',
    keywords: 'vendors suppliers priced catalog items price comparison warehouse stock reference library sku',
    titleKey: 'howto.supplier-catalogs.title',
    titleDefault: 'Supplier Catalogs',
    summaryKey: 'howto.supplier-catalogs.summary',
    summaryDefault: 'The vendor and item reference library you buy from: suppliers, priced catalogs and stock.',
    whatKey: 'howto.supplier-catalogs.what',
    whatDefault:
      'Supplier Catalogs is your reference library of vendors, priced catalog items and warehouse stock. It is where you keep who you can buy from and at what price, and compare prices across suppliers. Live purchasing - raising requisitions, issuing purchase orders and matching invoices - happens in the Procurement module.',
    how: [
      { key: 'howto.supplier-catalogs.how.1', default: 'Add vendors to build your list of approved suppliers.' },
      { key: 'howto.supplier-catalogs.how.2', default: 'Maintain each supplier priced catalog of items so prices are ready when you buy.' },
      { key: 'howto.supplier-catalogs.how.3', default: 'Compare prices for the same item across suppliers to find the best buy.' },
      { key: 'howto.supplier-catalogs.how.4', default: 'Track warehouse stock so you know what is already on hand before you order more.' },
    ],
    tips: [
      { key: 'howto.supplier-catalogs.tip.1', default: 'This page is reference data only - to actually order, open Procurement and raise a purchase order against a vendor here.' },
    ],
    whenKey: 'howto.supplier-catalogs.when',
    whenDefault: 'Use it to set up and maintain the suppliers and prices that Procurement draws on.',
  },
  {
    id: 'procurement',
    route: '/procurement',
    icon: 'ShoppingCart',
    category: 'procurement',
    keywords: 'purchase orders po goods receipt invoice committed spend three-way match payable budget vendor',
    titleKey: 'howto.procurement.title',
    titleDefault: 'Procurement',
    summaryKey: 'howto.procurement.summary',
    summaryDefault: 'Raise purchase orders, receive deliveries and turn them into invoices and payables.',
    whatKey: 'howto.procurement.what',
    whatDefault:
      'Procurement is where you buy the materials and work. Raise a purchase order to commit budget with a vendor, record a goods receipt when the delivery arrives, then create an invoice from the PO to push the amount into Finance as a payable. PO totals roll up into the project budget as committed spend, so you see what you have committed before the invoice lands.',
    how: [
      { key: 'howto.procurement.how.1', default: 'Open a project, then raise a purchase order against a vendor to commit budget.' },
      { key: 'howto.procurement.how.2', default: 'Record a goods receipt when the delivery arrives to confirm what was actually received.' },
      { key: 'howto.procurement.how.3', default: 'Create an invoice from the PO to push the amount into Finance as a payable.' },
      { key: 'howto.procurement.how.4', default: 'Watch PO totals appear in the project budget as committed, then become actual once the invoice is paid.' },
    ],
    tips: [
      { key: 'howto.procurement.tip.1', default: 'Vendors and prices come from Supplier Catalogs - keep that library current so your purchase orders price themselves.' },
      { key: 'howto.procurement.tip.2', default: 'Awarding a tender drafts a purchase order here automatically, so the buy follows the award without re-keying.' },
    ],
    whenKey: 'howto.procurement.when',
    whenDefault: 'Use it to buy the work and materials and to see committed spend long before the invoice arrives.',
  },
  {
    id: 'changeorders',
    route: '/changeorders',
    icon: 'FileSignature',
    category: 'procurement',
    keywords: 'change order scope change cost delta schedule impact approval chain budget commitment executed line items',
    titleKey: 'howto.changeorders.title',
    titleDefault: 'Change Orders',
    summaryKey: 'howto.changeorders.summary',
    summaryDefault: 'Formal change orders against a contract, with the cost and schedule impact priced for you.',
    whatKey: 'howto.changeorders.what',
    whatDefault:
      'Change Orders captures each scope change against a contract with its line items, original versus new quantities and rates, and computes the cost delta and schedule impact for you. You route it through Draft, Submitted, Approved and Executed - optionally via a named approval chain - and an approved order is applied to the project budget as a revised commitment.',
    how: [
      { key: 'howto.changeorders.how.1', default: 'Create a change order on a project and add its line items with original versus new quantities and rates.' },
      { key: 'howto.changeorders.how.2', default: 'Let the system compute the cost delta and schedule impact instead of working them out by hand.' },
      { key: 'howto.changeorders.how.3', default: 'Route it through Draft, Submitted, Approved and Executed, sending it down a named approval chain where one is set.' },
      { key: 'howto.changeorders.how.4', default: 'On approval the order is applied to the project budget as a revised commitment; export the register to CSV when you need it.' },
    ],
    tips: [
      { key: 'howto.changeorders.tip.1', default: 'An approved Management of Change item is the upstream decision a change order commits - keep the trail one click away in either direction.' },
      { key: 'howto.changeorders.tip.2', default: 'Use the AI Draft action to turn a short description into a starting change order you then check and price.' },
    ],
    whenKey: 'howto.changeorders.when',
    whenDefault: 'Use it to price and authorise a scope change against a contract before the revised work is committed.',
  },
];
