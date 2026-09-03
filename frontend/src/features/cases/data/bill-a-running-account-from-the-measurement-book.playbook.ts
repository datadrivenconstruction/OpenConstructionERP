// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Bill a running account from the measurement book" (IN).
//
// Indian public works are paid on running account bills, and a running account
// bill is not a valuation of progress. It is arithmetic on a record: the
// up-to-date quantity of every item measured to date, less the quantity paid
// in the previous bill, priced at the contract rates. The record it works from
// is the measurement book, kept on site, written as the work is measured and
// signed by both sides.
//
// Two properties of that record decide whether the bill goes through. It is
// cumulative, so an error in one bill travels into every bill after it until
// somebody re-measures. And it has to be written before the work is covered
// up: excavation depth, reinforcement, buried services and anything inside a
// wall can only be measured once, and after that the argument is about
// recollection rather than about a record.
//
// Measurement follows the standard method, which is the subject of its own
// case; this one is about the discipline around it, from measuring to money.
// Content strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "bill-a-running-account-from-the-measurement-book",
  order: 1185,
  region: "IN",
  category: "site",
  companyTypes: ["general-contractor", "subcontractor", "project-manager", "developer-client"],
  roles: ["quantity-surveyor", "site-manager", "commercial-manager", "foreman"],
  icon: "ClipboardList",
  titleKey: "cases.bill_a_running_account_from_the_measurement_book.title",
  titleDefault: "Bill a running account from the measurement book",
  descKey: "cases.bill_a_running_account_from_the_measurement_book.desc",
  descDefault:
    "Measure the work before it is covered up, get the record checked and signed on site, turn the up-to-date quantities into a running account bill against the previous one, and start the payment clock the contract sets.",
  longDescKey: "cases.bill_a_running_account_from_the_measurement_book.longdesc",
  longDescDefault:
    "A running account bill is cumulative, which is the property that makes it efficient and the property that makes an error in it permanent. Every bill states the quantity of each item measured to date and pays the difference against what the last bill paid, so a quantity entered short in the third bill is short in the tenth as well, and is corrected only when someone goes back and re-measures work that is now behind plaster. That is why the discipline sits at the measuring end rather than at the billing end. Measure hidden work before it is closed, record it where both parties sign, and keep the previous and up-to-date figures visible on the bill itself so that any dispute is about a single item in a single period rather than about a total that has been rolling forward for a year.",
  estMinutes: 22,
  steps: [
    {
      id: "measure",
      icon: "Ruler",
      inputs: [
        {
          labelKey: "cases.bill_a_running_account_from_the_measurement_book.step.measure.in.work",
          label: "Work done since the last bill",
        },
        {
          labelKey: "cases.bill_a_running_account_from_the_measurement_book.step.measure.in.previous",
          label: "Quantities paid last time",
        },
      ],
      outputs: [
        {
          labelKey: "cases.bill_a_running_account_from_the_measurement_book.step.measure.out.uptodate",
          label: "Up-to-date quantity per item",
        },
        {
          labelKey: "cases.bill_a_running_account_from_the_measurement_book.step.measure.out.hidden",
          label: "Hidden work recorded before covering",
        },
      ],
      titleKey: "cases.bill_a_running_account_from_the_measurement_book.step.measure.title",
      titleDefault: "Record the measurement while the work can still be seen",
      whatKey: "cases.bill_a_running_account_from_the_measurement_book.step.measure.what",
      whatDefault:
        "Measure the executed work item by item, on the standard method, and enter the up-to-date quantity beside the quantity carried from the previous bill. Take the measurements for excavation, reinforcement, concealed services and anything about to be covered before that happens, and note the date each was taken.",
      whyKey: "cases.bill_a_running_account_from_the_measurement_book.step.measure.why",
      whyDefault:
        "Covered work cannot be re-measured, only argued about. A measurement written on the day, against a dated entry, is worth more than any later reconstruction, and it is what makes the difference between a quantity that is checked and a quantity that is conceded or refused.",
      moduleLabel: "Quantity Takeoff",
      moduleLabelKey: "nav.quantities",
      to: "/quantities",
    },
    {
      id: "verify",
      icon: "ClipboardCheck",
      inputs: [
        {
          labelKey: "cases.bill_a_running_account_from_the_measurement_book.step.verify.in.measured",
          label: "The measured work",
        },
        {
          labelKey: "cases.bill_a_running_account_from_the_measurement_book.step.verify.in.itp",
          label: "The inspection and test plan",
        },
      ],
      outputs: [
        {
          labelKey: "cases.bill_a_running_account_from_the_measurement_book.step.verify.out.passed",
          label: "Work that passed its checks",
        },
        {
          labelKey: "cases.bill_a_running_account_from_the_measurement_book.step.verify.out.held",
          label: "Work held back from the bill",
        },
      ],
      titleKey: "cases.bill_a_running_account_from_the_measurement_book.step.verify.title",
      titleDefault: "Bill only what has passed its inspection",
      whatKey: "cases.bill_a_running_account_from_the_measurement_book.step.verify.what",
      whatDefault:
        "Check the measured quantities against the inspection records for the same work and hold back anything whose check is outstanding or failed, listing it so it can be picked up in the next bill rather than lost.",
      whyKey: "cases.bill_a_running_account_from_the_measurement_book.step.verify.why",
      whyDefault:
        "Measured and accepted are different states, and a bill that treats them as one is returned by the engineer with everything in it queried, including the parts that were fine. Separating them costs one column and saves a cycle.",
      moduleLabel: "Inspections",
      moduleLabelKey: "nav.inspections",
      to: "/projects/:projectId/inspections",
    },
    {
      id: "bill",
      icon: "Receipt",
      inputs: [
        {
          labelKey: "cases.bill_a_running_account_from_the_measurement_book.step.bill.in.quantities",
          label: "Up-to-date and previous quantities",
        },
        {
          labelKey: "cases.bill_a_running_account_from_the_measurement_book.step.bill.in.rates",
          label: "The contract rates",
        },
      ],
      outputs: [
        {
          labelKey: "cases.bill_a_running_account_from_the_measurement_book.step.bill.out.bill",
          label: "The running account bill",
        },
        {
          labelKey: "cases.bill_a_running_account_from_the_measurement_book.step.bill.out.recoveries",
          label: "Advances and retention recovered",
        },
      ],
      titleKey: "cases.bill_a_running_account_from_the_measurement_book.step.bill.title",
      titleDefault: "Turn the record into a bill that shows its own working",
      whatKey: "cases.bill_a_running_account_from_the_measurement_book.step.bill.what",
      whatDefault:
        "Build the bill from the up-to-date quantities at contract rates, show what the previous bill paid, and carry the recoveries: the instalment of any mobilisation advance, the retention deducted this period, and anything paid earlier against materials brought to site and now built in.",
      whyKey: "cases.bill_a_running_account_from_the_measurement_book.step.bill.why",
      whyDefault:
        "Recoveries against advances are the part most often missed, and missing them twice turns into a payment the department claws back from a later bill without warning. Putting them on the face of the bill keeps both sides looking at the same running position.",
      moduleLabel: "Finance",
      moduleLabelKey: "nav.finance",
      to: "/projects/:projectId/finance",
    },
    {
      id: "sign",
      icon: "Signature",
      inputs: [
        {
          labelKey: "cases.bill_a_running_account_from_the_measurement_book.step.sign.in.bill",
          label: "The bill and its measurements",
        },
      ],
      outputs: [
        {
          labelKey: "cases.bill_a_running_account_from_the_measurement_book.step.sign.out.signed",
          label: "A record signed by both sides",
        },
      ],
      titleKey: "cases.bill_a_running_account_from_the_measurement_book.step.sign.title",
      titleDefault: "Get the record signed by the people who checked it",
      whatKey: "cases.bill_a_running_account_from_the_measurement_book.step.sign.what",
      whatDefault:
        "Route the measurement record and the bill for signature by the contractor's representative and the engineer who checked the work, and keep the signed version with the bill it belongs to.",
      whyKey: "cases.bill_a_running_account_from_the_measurement_book.step.sign.why",
      whyDefault:
        "A signed measurement closes an item for good. An unsigned one stays open, travels forward through every later bill, and is reopened at final settlement when nobody remembers the work, which is the single most common reason an Indian final bill takes longer to agree than the job took to build.",
      moduleLabel: "E-Signatures",
      moduleLabelKey: "signing.title",
      to: "/signing",
    },
    {
      id: "clock",
      icon: "Clock",
      inputs: [
        {
          labelKey: "cases.bill_a_running_account_from_the_measurement_book.step.clock.in.submitted",
          label: "The date the bill was submitted",
        },
      ],
      outputs: [
        {
          labelKey: "cases.bill_a_running_account_from_the_measurement_book.step.clock.out.due",
          label: "When the payment falls due",
        },
        {
          labelKey: "cases.bill_a_running_account_from_the_measurement_book.step.clock.out.overdue",
          label: "What has gone past its date",
        },
      ],
      titleKey: "cases.bill_a_running_account_from_the_measurement_book.step.clock.title",
      titleDefault: "Start the clock the contract sets and watch it",
      whatKey: "cases.bill_a_running_account_from_the_measurement_book.step.clock.what",
      whatDefault:
        "Record the submission date and the period the contract allows for certification and for payment, and let the module show what is running and what is late.",
      whyKey: "cases.bill_a_running_account_from_the_measurement_book.step.clock.why",
      whyDefault:
        "Interest on delayed payment, where the contract provides for it, runs from a date that has to be proved. Tracking the date on every bill turns a claim you would rather not make into one you could make, which is usually enough for the conversation to go differently.",
      moduleLabel: "Payment Clock",
      moduleLabelKey: "nav.payment_clock",
      to: "/payment-clock",
    },
  ],
};

export default playbook;
