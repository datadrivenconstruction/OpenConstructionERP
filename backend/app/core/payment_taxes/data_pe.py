# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Peru payment tax rows: the construction detraction and the IGV retention.

**Detraccion (SPOT).** On a construction contract the buyer pays part of the
invoice, as a percentage of its total, into the seller's detraction account at
the Banco de la Nacion instead of to the seller, and the seller later uses the
balance only to pay taxes. It is a deposit, not income tax, but for the
certificate it behaves like a withholding on the invoice: the seller receives
the total less the deposit. The row is therefore ``income_withholding`` on the
net plus VAT total, and its condition text says what it really is.

**Retencion del IGV.** A buyer the tax authority has designated as a
withholding agent keeps 3 percent of the invoice total and pays it to SUNAT.
It applies only to designated buyers and is mutually exclusive with the
detraction on the same invoice, which the accountant decides; this table
carries both rows and does not choose between them.

**What ``unconfirmed`` means here.** Neither rate was read in the primary text.
The legal references are the instruments these regimes are published in, from
memory of the tax authority's framework, and each needs a Peruvian accountant
to read the current annex before a filing relies on it. An unconfirmed row
still computes; the status travels with the figure.

Deliberately absent: the IGV itself (a VAT rate, in the tax seed and the
markup stack), a detraction for other services (the annex lists many, each its
own rate; the one construction row is what the pack's partners need), and the
exemption of a seller whose account holds a balance above the invoice.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.core.payment_taxes.tables import RateRow

__all__ = ["ROWS"]

_READ = "2026-10-22"
_SUNAT_URL = "https://www.sunat.gob.pe/legislacion/"
_FROM = date(2026, 1, 1)

_DETRACTION_CONDITION = {
    "en": (
        "Deposited by the buyer into the seller's detraction account at the Banco de la Nacion, not paid to the "
        "seller, when the construction invoice exceeds the threshold. The code of the service on the invoice "
        "is 030 (construction contracts)."
    ),
    "es": (
        "El comprador la deposita en la cuenta de detracciones del vendedor en el Banco de la Nacion, y no se "
        "paga al vendedor, cuando la factura de construccion supera el monto minimo. El codigo del servicio en "
        "la factura es 030 (contratos de construccion)."
    ),
}

_RETENTION_CONDITION = {
    "en": (
        "Kept by a buyer designated as a withholding agent and paid to the tax authority. It does not apply "
        "together with the detraction on the same invoice."
    ),
    "es": (
        "La retiene el comprador designado agente de retencion y la paga a la SUNAT. No se aplica junto con "
        "la detraccion en la misma factura."
    ),
}

ROWS: tuple[RateRow, ...] = (
    RateRow(
        country_code="PE",
        kind="income_withholding",
        code="PE_DETRACCION_CONSTRUCCION",
        labels={"en": "Detraction, construction contracts", "es": "Detraccion, contratos de construccion"},
        base="net_plus_vat",
        rate_pct=Decimal("4"),
        numerator=None,
        denominator=None,
        threshold_amount=Decimal("700"),
        threshold_currency="PEN",
        threshold_scope="per_document",
        threshold_measure="net_plus_vat",
        cap_amount=None,
        effective_from=_FROM,
        effective_to=None,
        legal_reference=(
            "Decreto Legislativo 940 (Sistema de Pago de Obligaciones Tributarias); "
            "Resolucion de Superintendencia 183-2004/SUNAT, Anexo 3 (construction contracts, code 030)"
        ),
        source_url=_SUNAT_URL,
        read_date=_READ,
        review_status="unconfirmed",
        threshold_applies="above",
        conditions=_DETRACTION_CONDITION,
    ),
    RateRow(
        country_code="PE",
        kind="income_withholding",
        code="PE_RETENCION_IGV",
        labels={"en": "IGV withholding by designated agents", "es": "Retencion del IGV por agentes designados"},
        base="net_plus_vat",
        rate_pct=Decimal("3"),
        numerator=None,
        denominator=None,
        threshold_amount=Decimal("700"),
        threshold_currency="PEN",
        threshold_scope="per_document",
        threshold_measure="net_plus_vat",
        cap_amount=None,
        effective_from=_FROM,
        effective_to=None,
        legal_reference="Resolucion de Superintendencia 037-2002/SUNAT (Regimen de Retenciones del IGV)",
        source_url=_SUNAT_URL,
        read_date=_READ,
        review_status="unconfirmed",
        buyer_scope="designated_only",
        threshold_applies="above",
        conditions=_RETENTION_CONDITION,
    ),
)
