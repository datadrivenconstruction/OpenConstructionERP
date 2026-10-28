#!/usr/bin/env python3
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A payment application is a claim for money, never a piece of software.

On the subcontractor payment portal and the cost value reconciliation screen,
the English word "application" means a formal claim for work done in a period,
the same sense as applying for planning permission.

That sentence used to end "this product has no software-application meaning:
every English string containing the word is the claim sense", and it was true
when it was written. It is not true now. The funding module asks for grants,
where an application is a request for money nobody has awarded yet rather than
a claim for money already earned, and the settings screen has an application
server. What settles which sense is meant is the screen, not the word, which is
the rule the scope below is built on.

Seventeen locales had translated it as a phone app anyway. Spanish said
"Aplicaciones de pago", Croatian "Primjene placanja", French "application de
paiement" while the rest of the same file said "demande de paiement". In three
languages the whole payment portal read that way, and Bengali managed the
correct native word in five keys and a transliterated loanword in seven others,
so one namespace disagreed with itself.

This exists because that class of fix does not stay fixed. A later batch pass
translating the English word out of context reintroduces it, and nothing
notices: the key is present, the value is not empty, it is not the English
string, and it is in the right script. Every check we run passes on a fluent
wrong noun.

The scope is derived, and that is the whole point of this file
------------------------------------------------------------
The first version of this check watched fourteen keys written out by hand, all
of them under `payportal.` and `cvr.`. It went green at 524fb03b8 and stayed
green, and at that same commit two hundred and thirty strings across seventeen
locales still said "app", because the defect had also settled in
`subcontractors.`, `howto.`, `portal.`, `info.`, `contracts.`,
`notifications.`, `homeportal.` and `payment_clock.`, and a key that is not on
the list is not examined at all. "Clean" was a fact about the list, not about
the locales.

The docstring of that version said fifty three English strings carry this
sense. The list underneath it guarded fourteen. A file that states its own
scope and then implements a smaller one will keep its own promise and still be
wrong, so the scope is no longer something anyone maintains: `english_scope()`
takes every key whose English is about a payment application. Add such a string
anywhere in the product and it is guarded the moment it exists.

Deriving it took four tries, and each earlier scope was too small in a way the
scope itself could not reveal:

  fourteen     a list written by hand
  fifty two    every key whose English text contains the phrase
  sixty three  plus keys named for it that never spell it out, because
               `cvr.col_application` is simply "Application" and
               `payment_clock.field_application_date` is "Application date"
  a hundred    plus the case catalogue, whose English is not in en.ts at all
  and four

The last widening is the one worth remembering. This product's English lives in
two places, not one: `en.ts`, and the two hundred odd `*.playbook.ts` files that
carry the case catalogue as `titleDefault`, `descDefault` and `longDescDefault`
beside their keys. A check that reads `en.ts` alone is structurally blind to
about twelve hundred English strings, and no amount of improving its pattern
would ever have found them. So this reads both, and any future check over
English strings should ask itself the same question first: where does the
English actually live.

Widening the scope was only half of it. A derived scope still asks each value
a question in a fixed list of spellings, and French spells the software noun
exactly as English does, so twelve French strings sat inside the scope and
answered "no" to every root the check knew. See LOCALE_ROOTS for why the
answer to "which spelling means software" has to be stored per language.

`payportal.back_to_app` is excluded by name. It means go back to this product,
which really is the software, and it is the one string on that screen where the
app reading is correct. A sweep that went by the word rather than the meaning
would have broken it.

The scope has been narrowed once, and only once, against the direction of
everything above. A key named merely for an application used to enter the scope
from anywhere, which was right while the claim was the only sense in the
product. With the funding module it stopped being right, and the check reported
four Filipino grant strings for saying aplikasyon, which is that language's
ordinary word for a formal application and is what the same file uses for a
building permit. Filipino keeps the two apart the way this check asks: its
payment portal says paghahabol, a claim. So the bare word in a key name is
evidence only on a payment screen now, the same condition the third signal
already carried. It took the scope from 114 keys to 110 and removed nothing but
those four. Narrowing a scope is how a check of this kind goes quietly useless,
so it is worth saying what was not done: the funding namespace is not excluded,
and English there that says payment application is still the claim and is still
checked.
"""

from __future__ import annotations

import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCALES = os.path.join(REPO, "frontend", "src", "app", "locales")
# The product's English lives in two places. This is the second one.
PLAYBOOKS = os.path.join(REPO, "frontend", "src", "features", "cases", "data")
Q = '"'

# Roots meaning a software application, or "a use of", in the languages we ship.
# English is not among them: "Payment applications" is the correct English.
APP_ROOTS = (
    "aplicac",
    "aplicaç",
    "aplikac",
    "aplikas",
    "aplicaci",
    "applicaz",
    "anwendung",
    "toepassing",
    "primjen",
    "приложен",
    "аппликац",
    "تطبيق",
    "অ্যাপ্লিকেশন",
    "แอปพลิเคชัน",
    "アプリ",
    "应用程序",
    "앱",
)

# French spells the software noun exactly as English does, so "applicatio"
# cannot go in the shared list above: it would fire on every locale that has
# left an English phrase untranslated, which is a different defect and belongs
# to check_i18n_leak_baseline.py. Which spelling means software is a question
# about one language, so the answer is stored per language. The shared list has
# always been per-language really, "аппликац" is Russian and "앱" is Korean,
# they were merely unambiguous enough to apply everywhere.
#
# The root stops at the noun on purpose. French keeps the verb for the honest
# sense: "Brut appliqué" is gross applied and "Appliquer la retenue" is apply
# the retention, both correct and both untouched, because neither carries the
# -ation ending. Romanian and Italian sit in the same position, "Brut aplicat"
# and "Lordo applicato", and neither language was ever observed saying the noun,
# so neither gets a root here. A root that has never been seen to fire is a
# guess about a language rather than a finding in it.
LOCALE_ROOTS = {
    "fr": ("applicatio",),
}

# A value inside double braces is a variable name, not prose. i18next never
# shows it to anyone, and payment_app_submitted.body carries
# {{application_number}} in all forty odd languages, so matching it would report
# every locale we ship as broken.
PLACEHOLDER = re.compile(r"\{\{[^}]*\}\}")

# What makes an English string one of ours. The claim goes by several names
# across contract traditions and all of them are the same document.
CLAIM_SENSE = re.compile(
    r"payment application|application for payment|payment app\b|progress claim",
    re.I,
)

# Keys named for the claim whose English never spells it out. cvr.col_application
# is the single word "Application"; no text pattern will ever reach it.
#
# Two patterns, because the two halves of the old one carried different weights.
# `payapp` and `payment_app` name the claim wherever they appear and need no
# context to be read. The bare word does not, and that only became visible when
# the product grew a second sense of it.
KEY_NAMED_CLAIM = re.compile(r"payapp|payment_app", re.I)
# The bare word in a key name is evidence only where the screen settles what it
# means, which is the same rule BARE_APPLICATION already lives by below.
#
# A grant application is not a payment application. One asks for money that has
# not been awarded, the other claims money already earned, and the funding
# module is full of the first: `funding.new_application`, `funding.tab_appli-
# cations`, `funding.obligation_kind.application_deadline`. Every language
# translates those with its own word for a request, Antrag, demande, solicitud,
# candidatura, zayavka, and the check reported four Filipino strings for using
# aplikasyon, which is the ordinary Filipino word for a formal application and
# is what that file also uses for a building permit. Filipino separates the two
# senses correctly, in the way the check was built to require: the payment
# portal says paghahabol, a claim, and `cvr.col_application` says it too.
#
# Narrowing the signal rather than naming the module is deliberate. A funding
# string that genuinely says "payment application" in English is still caught by
# CLAIM_SENSE, so what moved out of scope is a word in a key name, not a
# namespace, and nothing about this depends on the funding module existing.
KEY_NAMED_BARE = re.compile(r"application", re.I)

# On these screens the bare word is unambiguous. "Applications", "Gross applied"
# and "App #" are all the claim, and outside a payment screen none of them would
# be. The namespace is what settles the word's sense, so it is what puts the key
# in scope. This is the third signal and it exists because the first two were
# both green while ten strings still said "app": the English said "Applications"
# with no qualifier, and the key was called k_count.
PAYMENT_SCREENS = (
    "cvr.",
    "payportal.",
    "payment_clock.",
    "subcontractors.",
    "contracts_claim.",
)
BARE_APPLICATION = re.compile(r"\bapplications?\b|\bapplied\b|\bapp\s*#", re.I)

PAIR = re.compile(Q + r"([A-Za-z0-9_.]+)" + Q + r"\s*:\s*" + Q + r'([^"]*)' + Q)

# A playbook default is a double-quoted JS string that may span lines and may
# contain escaped quotes.
BS = chr(92)
STR = Q + "((?:[^" + Q + BS + BS + "]|" + BS + BS + ".)*)" + Q
DEFAULT_PAIRS = (
    ("titleKey", "titleDefault"),
    ("descKey", "descDefault"),
    ("longDescKey", "longDescDefault"),
)

# back_to_app is the one place the software reading is the correct one.
EXCLUDED_BY_DESIGN = ("payportal.back_to_app",)


def english_source(locales_dir: str, playbooks_dir: str | None) -> dict[str, str]:
    """Every English string in the product, from both places it lives.

    `en.ts` holds the interface. The case catalogue holds its own English
    beside each key as a `...Default`, so a reader of `en.ts` alone sees only
    part of the product.
    """
    out: dict[str, str] = {}
    path = os.path.join(locales_dir, "en.ts")
    if os.path.exists(path):
        with open(path, encoding="utf-8", errors="replace") as fh:
            out.update(PAIR.findall(fh.read()))
    if playbooks_dir and os.path.isdir(playbooks_dir):
        for name in sorted(os.listdir(playbooks_dir)):
            if not name.endswith(".ts"):
                continue
            with open(os.path.join(playbooks_dir, name), encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            for key_field, default_field in DEFAULT_PAIRS:
                for m in re.finditer(
                    key_field + r"\s*:\s*" + STR + r"[\s\S]{0,400}?" + default_field + r"\s*:\s*\n?\s*" + STR,
                    text,
                ):
                    out.setdefault(m.group(1), m.group(2))
    return out


def english_scope(locales_dir: str, playbooks_dir: str | None = None) -> set[str]:
    """Every key whose English is about a payment application.

    Two signals, because either alone misses cases the other catches. The text
    signal misses a key called `cvr.col_application` whose English is the single
    word "Application". The name signal misses a sentence about progress claims
    in a key called `subcontractors.intro_body`.

    The name signal comes in two strengths. A key named payapp or payment_app
    is the claim anywhere; a key named merely for an application is the claim
    only on a payment screen, because elsewhere in this product the word now
    also means asking for a grant. See KEY_NAMED_BARE.
    """
    src = english_source(locales_dir, playbooks_dir)
    by_text = {k for k, v in src.items() if CLAIM_SENSE.search(v)}
    by_name = {
        k for k in src if KEY_NAMED_CLAIM.search(k) or (KEY_NAMED_BARE.search(k) and k.startswith(PAYMENT_SCREENS))
    }
    by_screen = {k for k, v in src.items() if k.startswith(PAYMENT_SCREENS) and BARE_APPLICATION.search(v)}
    return (by_text | by_name | by_screen) - set(EXCLUDED_BY_DESIGN)


def value(text: str, key: str) -> str | None:
    m = re.search(Q + re.escape(key) + Q + r"\s*:\s*" + Q + r'([^"]*)' + Q, text)
    return m.group(1) if m else None


def check(locales_dir: str, playbooks_dir: str | None = None) -> list[str]:
    scope = english_scope(locales_dir, playbooks_dir)
    problems: list[str] = []
    for name in sorted(os.listdir(locales_dir)):
        if not name.endswith(".ts") or name in ("en.ts", "en-US.ts"):
            continue
        loc = name[:-3]
        with open(os.path.join(locales_dir, name), encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        roots = APP_ROOTS + LOCALE_ROOTS.get(loc, ())
        for key in sorted(scope):
            v = value(text, key)
            if not v:
                continue
            prose = PLACEHOLDER.sub(" ", v).lower()
            hit = next((r for r in roots if r in prose), None)
            if hit:
                problems.append(f"{loc}: {key} = {v}    (contains {hit!r})")
    return problems


def _write(path: str, text: str) -> None:
    """Write a selftest fixture. Only here so the handle closes deterministically."""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def selftest() -> int:
    """Prove it fires, and prove the scope is not a list anyone maintains."""
    import tempfile

    english = (
        '  "cvr.payment_applications": "Payment applications",\n'
        '  "payportal.back_to_app": "Back to the app",\n'
        # This one is deliberately in a namespace the hand-written list never
        # covered. If the scope ever goes back to being enumerated, this is the
        # case that catches it.
        '  "subcontractors.no_payment_apps": "No payment applications under this agreement.",\n'
    )
    with tempfile.TemporaryDirectory() as tmp:
        _write(os.path.join(tmp, "en.ts"), english)
        _write(
            os.path.join(tmp, "xx.ts"),
            '  "cvr.payment_applications": "Aplicaciones de pago",\n'
            '  "payportal.back_to_app": "Volver a la aplicacion",\n'
            '  "subcontractors.no_payment_apps": "Sin aplicaciones de pago.",\n',
        )
        found = check(tmp)
        if len(found) != 2:
            print("selftest FAILED: expected two reports, got:", found)
            return 1
        if not any("subcontractors.no_payment_apps" in f for f in found):
            print("selftest FAILED: scope did not reach outside payportal and cvr")
            return 1
        # The excluded key must not be reported even though it carries the root.
        if any("back_to_app" in f for f in found):
            print("selftest FAILED: reported the key that is correct by design")
            return 1
        _write(
            os.path.join(tmp, "xx.ts"),
            '  "cvr.payment_applications": "Solicitudes de pago",\n'
            '  "subcontractors.no_payment_apps": "Sin solicitudes de pago.",\n',
        )
        if check(tmp):
            print("selftest FAILED: still reporting after the values were corrected")
            return 1
        # An English string that is not about the claim must not be pulled in.
        _write(
            os.path.join(tmp, "en.ts"),
            '  "settings.mobile": "Download the mobile application",\n',
        )
        _write(
            os.path.join(tmp, "xx.ts"),
            '  "settings.mobile": "Descargue la aplicacion movil",\n',
        )
        if check(tmp):
            print("selftest FAILED: guarded a string that is genuinely about software")
            return 1
        # Asking for a grant is not claiming for work done, and a key named for
        # an application away from a payment screen is the first, not the
        # second. Filipino writes both with aplikasyon, the way English writes
        # both with application, and marking that wrong would be marking the
        # language wrong.
        _write(
            os.path.join(tmp, "en.ts"),
            '  "funding.new_application": "New application",\n',
        )
        _write(
            os.path.join(tmp, "xx.ts"),
            '  "funding.new_application": "Bagong aplikasyon",\n',
        )
        if check(tmp):
            print("selftest FAILED: reported a grant application as a payment application")
            return 1
        # The same key name on a payment screen is the claim again, so the
        # narrowing above has to be the screen and not the word. Without this
        # the check could be switched off entirely and still pass the case
        # before it.
        _write(
            os.path.join(tmp, "en.ts"),
            '  "cvr.new_application": "New application",\n',
        )
        _write(
            os.path.join(tmp, "xx.ts"),
            '  "cvr.new_application": "Bagong aplikasyon",\n',
        )
        if len(check(tmp)) != 1:
            print("selftest FAILED: a key named for an application on a payment screen stopped being checked")
            return 1
        # And the funding namespace is not excluded, only the weaker of the two
        # name signals is. English that says payment application is the claim
        # wherever it is written, so this must still fire.
        _write(
            os.path.join(tmp, "en.ts"),
            '  "funding.retention_note": "Deduct retention on the next payment application",\n',
        )
        _write(
            os.path.join(tmp, "xx.ts"),
            '  "funding.retention_note": "Deduzca la retencion en la proxima aplicacion de pago",\n',
        )
        if len(check(tmp)) != 1:
            print("selftest FAILED: the claim sense stopped being checked inside the funding namespace")
            return 1

    # A key whose English exists only in a playbook, never in en.ts. This is the
    # case no pattern over en.ts could ever reach, and the reason this check
    # reads two sources instead of one.
    with tempfile.TemporaryDirectory() as tmp:
        loc, books = os.path.join(tmp, "l"), os.path.join(tmp, "p")
        os.makedirs(loc)
        os.makedirs(books)
        _write(
            os.path.join(loc, "en.ts"),
            '  "unrelated.key": "Nothing to do with money",\n',
        )
        _write(
            os.path.join(books, "a.playbook.ts"),
            '  descKey: "cases.bill_the_month.desc",\n'
            '  descDefault: "Raise the progress claim and send it for certification.",\n',
        )
        _write(
            os.path.join(loc, "xx.ts"),
            '  "cases.bill_the_month.desc": "Crea la aplicacion de pago del mes.",\n',
        )
        if check(loc):
            print("selftest FAILED: found a playbook key without being given playbooks")
            return 1
        found = check(loc, books)
        if len(found) != 1 or "cases.bill_the_month.desc" not in found[0]:
            print("selftest FAILED: playbook English is not in scope, got:", found)
            return 1
    # French, where the software noun is spelled exactly as in English, so
    # the root is scoped to the one language and has to be proved four ways.
    with tempfile.TemporaryDirectory() as tmp:
        _write(
            os.path.join(tmp, "en.ts"),
            '  "cvr.no_payapps": "No payment applications yet",\n'
            '  "cvr.rollup_gross": "Gross applied",\n'
            '  "notifications.subcontractors.payment_app_submitted.body":'
            ' "Application {{application_number}} submitted.",\n',
        )
        broken = (
            '  "cvr.no_payapps": "Aucune application de paiement pour le moment",\n'
            '  "cvr.rollup_gross": "Brut applique",\n'
            '  "notifications.subcontractors.payment_app_submitted.body":'
            ' "Demande {{application_number}} deposee.",\n'
        )
        _write(os.path.join(tmp, "fr.ts"), broken)
        found = check(tmp)
        if len(found) != 1 or "cvr.no_payapps" not in found[0]:
            print("selftest FAILED: the French noun was not caught, got:", found)
            return 1
        if any("rollup_gross" in f for f in found):
            print("selftest FAILED: condemned the participle, correct French")
            return 1
        if any("payment_app_submitted" in f for f in found):
            print("selftest FAILED: matched a variable name inside double braces")
            return 1
        # The same bytes under another language must stay quiet: an English
        # phrase left untranslated is a leak, not a mistranslation, and the
        # leak baseline owns it.
        os.remove(os.path.join(tmp, "fr.ts"))
        _write(os.path.join(tmp, "yy.ts"), broken)
        if check(tmp):
            print("selftest FAILED: a French-scoped root fired on another language")
            return 1

    print(
        "selftest ok: fires outside payportal and cvr, reaches keys whose English "
        "lives only in a playbook, ignores back_to_app, catches the French noun "
        "without touching the French verb or a variable name, leaves genuine "
        "software strings alone, leaves a grant application alone while still "
        "checking the same key name on a payment screen and the claim sense "
        "inside the funding namespace, goes quiet once corrected"
    )
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    scope = english_scope(LOCALES, PLAYBOOKS)
    problems = check(LOCALES, PLAYBOOKS)
    if not problems:
        print(
            f"All {len(scope)} payment application strings read as a claim for "
            f"money, in every locale that defines them."
        )
        return 0
    print(
        f"{len(problems)} payment application strings read as software, "
        f"out of {len(scope)} English strings that carry this sense:\n"
    )
    for line in problems:
        print("  " + line)
    print(
        "\nThe word here means a claim for work done, not an app. Each of these "
        "files already carries the right noun on the payment portal.\n"
        f"Correct by design and never reported: {', '.join(EXCLUDED_BY_DESIGN)}."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
