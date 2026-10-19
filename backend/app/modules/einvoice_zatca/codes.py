# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The code lists of the ZATCA KSA profile of UBL 2.1.

Taken from the XML Implementation Standard v1.2 (P1) and, where the 2023 text
and the validator disagree, from the schematron ZATCA ships in its SDK
238-R3.3.8 (``Data/Rules/schematrons/20210819_ZATCA_E-invoice_Validation_Rules.xsl``),
because that file is what the platform runs on every submission. The two cases
where it matters are noted at the code.

Namespaces, signature identifiers and algorithm URIs are here too: every one of
them is compared as an exact string by ZATCA's validator.
"""

from __future__ import annotations

from dataclasses import dataclass

# ── Namespaces ───────────────────────────────────────────────────────────────

NS_INVOICE = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
NS_CAC = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
NS_CBC = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
NS_EXT = "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2"
NS_SIG = "urn:oasis:names:specification:ubl:schema:xsd:CommonSignatureComponents-2"
NS_SAC = "urn:oasis:names:specification:ubl:schema:xsd:SignatureAggregateComponents-2"
NS_SBC = "urn:oasis:names:specification:ubl:schema:xsd:SignatureBasicComponents-2"
NS_DS = "http://www.w3.org/2000/09/xmldsig#"
NS_XADES = "http://uri.etsi.org/01903/v1.3.2#"

# ── Signature identifiers (BR-KSA-28 to 30) and algorithms (P2 §2.3) ─────────

SIGNATURE_INFORMATION_ID = "urn:oasis:names:specification:ubl:signature:1"
SIGNATURE_ID = "urn:oasis:names:specification:ubl:signature:Invoice"
SIGNATURE_METHOD = "urn:oasis:names:specification:ubl:dsig:enveloped:xades"
EXTENSION_URI = "urn:oasis:names:specification:ubl:dsig:enveloped:xades"

ALG_C14N11 = "http://www.w3.org/2006/12/xml-c14n11"
ALG_ECDSA_SHA256 = "http://www.w3.org/2001/04/xmldsig-more#ecdsa-sha256"
ALG_SHA256 = "http://www.w3.org/2001/04/xmlenc#sha256"
ALG_XPATH = "http://www.w3.org/TR/1999/REC-xpath-19991116"
SIGNED_PROPERTIES_TYPE = "http://www.w3.org/2000/09/xmldsig#SignatureProperties"

# The three transforms of the invoice reference, in the order P2 prints them.
XPATH_TRANSFORMS: tuple[str, ...] = (
    "not(//ancestor-or-self::ext:UBLExtensions)",
    "not(//ancestor-or-self::cac:Signature)",
    "not(//ancestor-or-self::cac:AdditionalDocumentReference[cbc:ID='QR'])",
)

PROFILE_ID = "reporting:1.0"
TAX_CURRENCY = "SAR"
VAT_SCHEME = "VAT"
SAUDI_ARABIA = "SA"

# ── Document types (BT-3) ────────────────────────────────────────────────────

TYPE_INVOICE = "388"
TYPE_CREDIT_NOTE = "381"
TYPE_DEBIT_NOTE = "383"
TYPE_PREPAYMENT = "386"

DOCUMENT_TYPES: dict[str, str] = {
    TYPE_INVOICE: "Tax invoice",
    TYPE_CREDIT_NOTE: "Credit note",
    TYPE_DEBIT_NOTE: "Debit note",
    TYPE_PREPAYMENT: "Prepayment invoice",
}

# The types that correct an earlier invoice and so need its number (BT-25,
# BR-KSA-56) and a reason (KSA-10, BR-KSA-17).
NOTE_TYPES: frozenset[str] = frozenset({TYPE_CREDIT_NOTE, TYPE_DEBIT_NOTE})

# ── Invoice subtype (KSA-2), seven characters ``NNPNESB`` ───────────────────

KIND_STANDARD = "01"
KIND_SIMPLIFIED = "02"


@dataclass(frozen=True)
class Subtype:
    """The seven-character KSA-2 transaction code, read as flags."""

    simplified: bool = False
    third_party: bool = False
    nominal: bool = False
    export: bool = False
    summary: bool = False
    self_billed: bool = False

    @property
    def code(self) -> str:
        flags = (self.third_party, self.nominal, self.export, self.summary, self.self_billed)
        return (KIND_SIMPLIFIED if self.simplified else KIND_STANDARD) + "".join("1" if f else "0" for f in flags)

    def problems(self) -> list[str]:
        """What BR-KSA-31 and BR-KSA-07 refuse about this combination."""
        found: list[str] = []
        if self.simplified and (self.export or self.self_billed):
            found.append("a simplified invoice cannot be an export or self-billed invoice (BR-KSA-31)")
        if self.export and self.self_billed:
            found.append("self-billing is not allowed on an export invoice (BR-KSA-07)")
        return found


def parse_subtype(code: str) -> Subtype | None:
    """The flags of a KSA-2 code, or ``None`` when it is not seven 0/1 flags after 01 or 02."""
    text = (code or "").strip()
    if len(text) != 7 or text[:2] not in (KIND_STANDARD, KIND_SIMPLIFIED) or any(c not in "01" for c in text[2:]):
        return None
    flags = [c == "1" for c in text[2:]]
    return Subtype(
        simplified=text[:2] == KIND_SIMPLIFIED,
        third_party=flags[0],
        nominal=flags[1],
        export=flags[2],
        summary=flags[3],
        self_billed=flags[4],
    )


# ── VAT categories (BT-118) and exemption reasons (BT-121 / BT-120) ─────────

CATEGORY_STANDARD = "S"
CATEGORY_ZERO = "Z"
CATEGORY_EXEMPT = "E"
CATEGORY_OUT_OF_SCOPE = "O"
VAT_CATEGORIES: tuple[str, ...] = (CATEGORY_STANDARD, CATEGORY_ZERO, CATEGORY_EXEMPT, CATEGORY_OUT_OF_SCOPE)


@dataclass(frozen=True)
class ExemptionReason:
    """One VATEX code. ``text`` is the reason text BR-KSA-83 compares against.

    ``needs_expert_review`` marks a code the 2023 standard does not list and
    whose required text the SDK does not state; the operator supplies the text.
    """

    code: str
    category: str
    text: str
    needs_expert_review: bool = False


# Texts from P1 §11.2.4 as the SDK schematron compares them (BR-KSA-83).
# DIPLOMAT and DUTYFREE are accepted by the 238 schematron for category Z but
# appear in neither the 2023 standard nor the text check, so they ship flagged.
EXEMPTION_REASONS: dict[str, ExemptionReason] = {
    r.code: r
    for r in (
        ExemptionReason("VATEX-SA-29", "E", "Financial services mentioned in Article 29 of the VAT Regulations"),
        ExemptionReason("VATEX-SA-29-7", "E", "Life insurance services mentioned in Article 29 of the VAT Regulations"),
        ExemptionReason("VATEX-SA-30", "E", "Real estate transactions mentioned in Article 30 of the VAT Regulations"),
        ExemptionReason("VATEX-SA-32", "Z", "Export of goods"),
        ExemptionReason("VATEX-SA-33", "Z", "Export of services"),
        ExemptionReason("VATEX-SA-34-1", "Z", "The international transport of Goods"),
        ExemptionReason("VATEX-SA-34-2", "Z", "international transport of passengers"),
        ExemptionReason(
            "VATEX-SA-34-3",
            "Z",
            "services directly connected and incidental to a Supply of international passenger transport",
        ),
        ExemptionReason("VATEX-SA-34-4", "Z", "Supply of a qualifying means of transport"),
        ExemptionReason(
            "VATEX-SA-34-5",
            "Z",
            "Any services relating to Goods or passenger transportation, as defined in article twenty five of "
            "these Regulations",
        ),
        ExemptionReason("VATEX-SA-35", "Z", "Medicines and medical equipment"),
        ExemptionReason("VATEX-SA-36", "Z", "Qualifying metals"),
        ExemptionReason("VATEX-SA-EDU", "Z", "Private education to citizen"),
        ExemptionReason("VATEX-SA-HEA", "Z", "Private healthcare to citizen"),
        ExemptionReason("VATEX-SA-MLTRY", "Z", "supply of qualified military goods"),
        ExemptionReason("VATEX-SA-DIPLOMAT", "Z", "", needs_expert_review=True),
        ExemptionReason("VATEX-SA-DUTYFREE", "Z", "", needs_expert_review=True),
        # Free text: the reason is the operator's own (P1 §11.2.4).
        ExemptionReason("VATEX-SA-OOS", "O", ""),
    )
}

# The two codes that need the buyer's national ID (BR-KSA-49).
CITIZEN_ONLY_REASONS: frozenset[str] = frozenset({"VATEX-SA-EDU", "VATEX-SA-HEA"})

# ── Party identification schemes (BT-29 / BT-46) ─────────────────────────────

# BR-KSA-08: the seller's other ID is one of these.
SELLER_ID_SCHEMES: tuple[str, ...] = ("CRN", "MOM", "MLS", "700", "SAG", "OTH")
# BR-KSA-14: the buyer's other ID is one of these.
BUYER_ID_SCHEMES: tuple[str, ...] = ("TIN", "CRN", "MOM", "MLS", "700", "SAG", "NAT", "GCC", "IQA", "PAS", "OTH")

# KSA-40, BR-KSA-91: a government buyer under VAT IR Art 20(5) is marked so.
GOVERNMENT_LEGAL_FORM = "GOV"

# ── Payment means (BT-81, UNTDID 4461 subset P1 §11.2.3) ─────────────────────

PAYMENT_MEANS: dict[str, str] = {
    "1": "Instrument not defined",
    "10": "In cash",
    "30": "Credit",
    "42": "Payment to bank account",
    "48": "Bank card",
}

# ── Chain seed (BR-KSA-26) ───────────────────────────────────────────────────

# base64 of the hex SHA-256 of "0": the PIH of every unit's first document.
FIRST_PREVIOUS_HASH = "NWZlY2ViNjZmZmM4NmYzOGQ5NTI3ODZjNmQ2OTZjNzljMmRiYzIzOWRkNGU5MWI0NjcyOWQ3M2EyN2ZiNTdlOQ=="

__all__ = [
    "ALG_C14N11",
    "ALG_ECDSA_SHA256",
    "ALG_SHA256",
    "ALG_XPATH",
    "BUYER_ID_SCHEMES",
    "CATEGORY_EXEMPT",
    "CATEGORY_OUT_OF_SCOPE",
    "CATEGORY_STANDARD",
    "CATEGORY_ZERO",
    "CITIZEN_ONLY_REASONS",
    "DOCUMENT_TYPES",
    "EXEMPTION_REASONS",
    "EXTENSION_URI",
    "FIRST_PREVIOUS_HASH",
    "GOVERNMENT_LEGAL_FORM",
    "KIND_SIMPLIFIED",
    "KIND_STANDARD",
    "NOTE_TYPES",
    "NS_CAC",
    "NS_CBC",
    "NS_DS",
    "NS_EXT",
    "NS_INVOICE",
    "NS_SAC",
    "NS_SBC",
    "NS_SIG",
    "NS_XADES",
    "PAYMENT_MEANS",
    "PROFILE_ID",
    "SAUDI_ARABIA",
    "SELLER_ID_SCHEMES",
    "SIGNATURE_ID",
    "SIGNATURE_INFORMATION_ID",
    "SIGNATURE_METHOD",
    "SIGNED_PROPERTIES_TYPE",
    "TAX_CURRENCY",
    "TYPE_CREDIT_NOTE",
    "TYPE_DEBIT_NOTE",
    "TYPE_INVOICE",
    "TYPE_PREPAYMENT",
    "VAT_CATEGORIES",
    "VAT_SCHEME",
    "XPATH_TRANSFORMS",
    "ExemptionReason",
    "Subtype",
    "parse_subtype",
]
