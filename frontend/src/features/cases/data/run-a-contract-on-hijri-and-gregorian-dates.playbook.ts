// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Run a contract on Hijri and Gregorian dates" (SA).
//
// Two calendars run side by side on a Saudi job and they do not keep step. A
// Hijri year is about eleven days shorter than a Gregorian one, so a period
// written in Hijri months ends earlier every year than a reader working in
// Gregorian months expects, and the two Eids move through the seasons while
// Founding Day on 22 February and National Day on 23 September do not. This
// case sets the working calendar, records contract periods in the calendar
// the contract actually uses, and puts every date that can lapse in one
// place. Content strings are key plus inline English default and live only
// here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "run-a-contract-on-hijri-and-gregorian-dates",
  order: 1193,
  region: "SA",
  category: "planning",
  companyTypes: ["general-contractor", "project-manager", "developer-client", "subcontractor"],
  roles: ["planner", "project-manager", "contract-administrator"],
  stage: "plan",
  icon: "CalendarDays",
  titleKey: "cases.run_a_contract_on_hijri_and_gregorian_dates.title",
  titleDefault: "Run a contract on Hijri and Gregorian dates",
  descKey: "cases.run_a_contract_on_hijri_and_gregorian_dates.desc",
  descDefault:
    "Set the Sunday to Thursday week and the holidays that move, record the contract period in the calendar the contract is written in, plan the reduced Ramadan hours, register every expiry that is dated in Hijri, and settle a delay against dates both sides can check.",
  longDescKey: "cases.run_a_contract_on_hijri_and_gregorian_dates.longdesc",
  longDescDefault:
    "Ask two people on a Saudi project when the maintenance period ends and you will often get two answers eleven days apart, because one of them read the Hijri period in the contract as though the months were Gregorian. The Kingdom runs both calendars in earnest. Guarantee validity, licence renewals, iqama expiry and many contract durations are written in Hijri, while programmes, invoices and the two national days sit in Gregorian. The two Eids move through the Gregorian year and their exact days are confirmed by announcement rather than fixed a year ahead, and the Labour Law cuts the working day during Ramadan. None of this is difficult once it is written down in one place. All of it is expensive when each person converts in their head.",
  estMinutes: 14,
  steps: [
    {
      id: "week",
      icon: "CalendarDays",
      inputs: [
        { labelKey: "cases.run_a_contract_on_hijri_and_gregorian_dates.step.week.in.project", label: "Project and its country" },
        { labelKey: "cases.run_a_contract_on_hijri_and_gregorian_dates.step.week.in.hours", label: "Working hours agreed" },
      ],
      outputs: [
        { labelKey: "cases.run_a_contract_on_hijri_and_gregorian_dates.step.week.out.calendar", label: "Work calendar set" },
        { labelKey: "cases.run_a_contract_on_hijri_and_gregorian_dates.step.week.out.week", label: "Sunday to Thursday week" },
      ],
      titleKey: "cases.run_a_contract_on_hijri_and_gregorian_dates.step.week.title",
      titleDefault: "Set the working week the site actually keeps",
      whatKey: "cases.run_a_contract_on_hijri_and_gregorian_dates.step.week.what",
      whatDefault:
        "Set the project calendar to the Saudi working week, Sunday through Thursday with Friday and Saturday as the weekend, and record the normal working day at the Labour Law maximum of eight hours, or forty eight hours in the week, whichever standard the contract of employment adopts.",
      whyKey: "cases.run_a_contract_on_hijri_and_gregorian_dates.step.week.why",
      whyDefault:
        "A programme built on a Monday to Friday default is wrong twice a week, every week, and the error compounds silently into every float calculation and every completion date the programme produces. It also puts planned work on Fridays, which is the day it will not happen, so the first progress report reads as a delay that never occurred.",
      moduleLabel: "4D Schedule",
      moduleLabelKey: "nav.schedule",
      to: "/schedule",
    },
    {
      id: "holidays",
      icon: "CalendarCheck",
      inputs: [
        { labelKey: "cases.run_a_contract_on_hijri_and_gregorian_dates.step.holidays.in.calendar", label: "Work calendar" },
        { labelKey: "cases.run_a_contract_on_hijri_and_gregorian_dates.step.holidays.in.year", label: "Programme year" },
      ],
      outputs: [
        { labelKey: "cases.run_a_contract_on_hijri_and_gregorian_dates.step.holidays.out.fixed", label: "Fixed national days" },
        { labelKey: "cases.run_a_contract_on_hijri_and_gregorian_dates.step.holidays.out.moving", label: "Moving Eid periods" },
      ],
      titleKey: "cases.run_a_contract_on_hijri_and_gregorian_dates.step.holidays.title",
      titleDefault: "Put the holidays that move next to the ones that do not",
      whatKey: "cases.run_a_contract_on_hijri_and_gregorian_dates.step.holidays.what",
      whatDefault:
        "Load the public holidays for the programme years ahead. Founding Day on 22 February and National Day on 23 September are fixed Gregorian dates. Eid al-Fitr and Eid al-Adha are Hijri and shift about eleven days earlier each Gregorian year, and the exact days off are confirmed close to the time, so plan the window and confirm the days rather than the other way round.",
      whyKey: "cases.run_a_contract_on_hijri_and_gregorian_dates.step.holidays.why",
      whyDefault:
        "A concrete pour or a shutdown planned into an Eid week is not a scheduling inconvenience, it is a crew that is not in the country. Because the Eids move, a programme copied from a job that ran two years earlier puts them in the wrong place, and the mistake is invisible until the week arrives.",
      moduleLabel: "Advanced Schedule",
      moduleLabelKey: "nav.schedule_advanced",
      to: "/schedule-advanced",
    },
    {
      id: "period",
      icon: "Scale",
      inputs: [
        { labelKey: "cases.run_a_contract_on_hijri_and_gregorian_dates.step.period.in.contract", label: "Signed contract" },
        { labelKey: "cases.run_a_contract_on_hijri_and_gregorian_dates.step.period.in.start", label: "Commencement date" },
      ],
      outputs: [
        { labelKey: "cases.run_a_contract_on_hijri_and_gregorian_dates.step.period.out.calendar", label: "Contract calendar named" },
        { labelKey: "cases.run_a_contract_on_hijri_and_gregorian_dates.step.period.out.completion", label: "Completion date in both" },
      ],
      titleKey: "cases.run_a_contract_on_hijri_and_gregorian_dates.step.period.title",
      titleDefault: "Record the period in the calendar the contract uses",
      whatKey: "cases.run_a_contract_on_hijri_and_gregorian_dates.step.period.what",
      whatDefault:
        "Read the contract for how the period of performance is expressed, in Hijri months, in Gregorian months or in days, note which it is on the contract record, and compute the completion date from the commencement date on that basis. Show the same date in the other calendar beside it, marked as the conversion rather than as the term.",
      whyKey: "cases.run_a_contract_on_hijri_and_gregorian_dates.step.period.why",
      whyDefault:
        "This is where the disputes come from. Eighteen Hijri months and eighteen Gregorian months are more than a fortnight apart, and on a contract with liquidated damages a fortnight is a number. Naming the calendar the contract chose, once, means the completion date is computed rather than negotiated, and the conversion stays visible as a convenience for the reader instead of quietly becoming the obligation.",
      moduleLabel: "Contracts",
      moduleLabelKey: "nav.contracts",
      to: "/projects/:projectId/contracts",
    },
    {
      id: "ramadan",
      icon: "Users",
      inputs: [
        { labelKey: "cases.run_a_contract_on_hijri_and_gregorian_dates.step.ramadan.in.crews", label: "Crews and shifts" },
        { labelKey: "cases.run_a_contract_on_hijri_and_gregorian_dates.step.ramadan.in.window", label: "Ramadan window" },
      ],
      outputs: [
        { labelKey: "cases.run_a_contract_on_hijri_and_gregorian_dates.step.ramadan.out.hours", label: "Reduced hours applied" },
        { labelKey: "cases.run_a_contract_on_hijri_and_gregorian_dates.step.ramadan.out.output", label: "Output replanned" },
      ],
      titleKey: "cases.run_a_contract_on_hijri_and_gregorian_dates.step.ramadan.title",
      titleDefault: "Plan Ramadan at the hours the law allows",
      whatKey: "cases.run_a_contract_on_hijri_and_gregorian_dates.step.ramadan.what",
      whatDefault:
        "Set the crews to the Ramadan working day and replan the month's output on it. Article 98 of the Labour Law reduces actual working hours during Ramadan for Muslim workers to six a day, or thirty six a week, against the normal eight and forty eight, and most sites apply the reduced day to everyone rather than run two rotas.",
      whyKey: "cases.run_a_contract_on_hijri_and_gregorian_dates.step.ramadan.why",
      whyDefault:
        "A quarter of the working hours disappears for a month, and it is a statutory reduction rather than a productivity dip, so it belongs in the plan rather than in the excuses. A programme that carries eight hour days through Ramadan is not optimistic, it is arithmetically impossible, and the recovery plan written in the following month is paying for a decision made a year earlier.",
      moduleLabel: "Resources & Crew",
      moduleLabelKey: "nav.resources",
      to: "/projects/:projectId/resources",
    },
    {
      id: "expiries",
      icon: "CalendarClock",
      inputs: [
        { labelKey: "cases.run_a_contract_on_hijri_and_gregorian_dates.step.expiries.in.instruments", label: "Guarantees, licences, permits" },
        { labelKey: "cases.run_a_contract_on_hijri_and_gregorian_dates.step.expiries.in.staff", label: "Residence and permit dates" },
      ],
      outputs: [
        { labelKey: "cases.run_a_contract_on_hijri_and_gregorian_dates.step.expiries.out.register", label: "One expiry register" },
        { labelKey: "cases.run_a_contract_on_hijri_and_gregorian_dates.step.expiries.out.calendar", label: "Calendar noted on each" },
      ],
      titleKey: "cases.run_a_contract_on_hijri_and_gregorian_dates.step.expiries.title",
      titleDefault: "Register every expiry with the calendar it is written in",
      whatKey: "cases.run_a_contract_on_hijri_and_gregorian_dates.step.expiries.what",
      whatDefault:
        "Put the guarantees, the insurances, the classification and commercial registration certificates, the municipal permits and the residence permits of the staff on one register, each with its expiry and a note saying whether that expiry was written in Hijri or in Gregorian, and set the reminder far enough ahead to renew rather than to react.",
      whyKey: "cases.run_a_contract_on_hijri_and_gregorian_dates.step.expiries.why",
      whyDefault:
        "Almost every instrument on that list has teeth and none of them warn you. A residence permit that lapses stops a man working, a lapsed guarantee can cost the contract, and a bank guarantee written for twelve Hijri months expires eleven days before the anniversary somebody has in their diary. The register is not paperwork, it is the only place the two calendars are reconciled once instead of forty times.",
      moduleLabel: "Deadlines",
      moduleLabelKey: "deadlines.title",
      to: "/deadlines",
    },
    {
      id: "delay",
      icon: "FileSearch",
      inputs: [
        { labelKey: "cases.run_a_contract_on_hijri_and_gregorian_dates.step.delay.in.records", label: "Site records and diaries" },
        { labelKey: "cases.run_a_contract_on_hijri_and_gregorian_dates.step.delay.in.calendar", label: "Agreed work calendar" },
      ],
      outputs: [
        { labelKey: "cases.run_a_contract_on_hijri_and_gregorian_dates.step.delay.out.entitlement", label: "Delay measured in working days" },
        { labelKey: "cases.run_a_contract_on_hijri_and_gregorian_dates.step.delay.out.pack", label: "Evidence pack" },
      ],
      titleKey: "cases.run_a_contract_on_hijri_and_gregorian_dates.step.delay.title",
      titleDefault: "Measure a delay against the calendar that was agreed",
      whatKey: "cases.run_a_contract_on_hijri_and_gregorian_dates.step.delay.what",
      whatDefault:
        "When an extension of time is claimed, count the delay in working days on the project calendar, with the weekends, the national days and the Eid closures the calendar already holds, and attach the diary entries and correspondence that show what happened on each of them.",
      whyKey: "cases.run_a_contract_on_hijri_and_gregorian_dates.step.delay.why",
      whyDefault:
        "A claim counted in calendar days and answered in working days is two parties disagreeing about arithmetic while believing they disagree about the facts. Counting on the calendar both signed up to removes that argument entirely and leaves the real one, which is whether the event was the employer's risk.",
      moduleLabel: "Claims Evidence",
      moduleLabelKey: "nav.claims_evidence",
      to: "/projects/:projectId/claims-evidence",
    },
    {
      id: "report",
      icon: "LineChart",
      inputs: [
        { labelKey: "cases.run_a_contract_on_hijri_and_gregorian_dates.step.report.in.progress", label: "Progress this period" },
        { labelKey: "cases.run_a_contract_on_hijri_and_gregorian_dates.step.report.in.dates", label: "Contract and programme dates" },
      ],
      outputs: [
        { labelKey: "cases.run_a_contract_on_hijri_and_gregorian_dates.step.report.out.report", label: "Report both sides can read" },
        { labelKey: "cases.run_a_contract_on_hijri_and_gregorian_dates.step.report.out.forecast", label: "Forecast completion" },
      ],
      titleKey: "cases.run_a_contract_on_hijri_and_gregorian_dates.step.report.title",
      titleDefault: "Report dates the client reads the same way you do",
      whatKey: "cases.run_a_contract_on_hijri_and_gregorian_dates.step.report.what",
      whatDefault:
        "Publish the period report with the contract completion date, the forecast completion and the remaining float, each shown in the calendar the contract uses, and the conversion given alongside where the audience needs it.",
      whyKey: "cases.run_a_contract_on_hijri_and_gregorian_dates.step.report.why",
      whyDefault:
        "A monthly report is where a date error gets ratified. Print the completion date in one calendar for a year and both parties stop checking it, and the correction, when it comes, arrives with a claim attached. Showing the contract calendar first and the conversion second keeps the obligation and the convenience clearly apart.",
      moduleLabel: "Reports",
      moduleLabelKey: "nav.reports",
      to: "/reports",
    },
  ],
};

export default playbook;
