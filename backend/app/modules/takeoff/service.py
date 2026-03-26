"""Takeoff business logic."""

import io
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.takeoff.models import TakeoffDocument
from app.modules.takeoff.repository import TakeoffRepository


def _extract_pdf_pages(content: bytes) -> list[dict]:
    """Extract text and tables from each page of a PDF.

    Returns a list of dicts: [{ page: 1, text: "...", tables: [...] }, ...]
    """
    pages: list[dict] = []
    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                page_text = ""
                page_tables: list[list[list[str]]] = []

                tables = page.extract_tables()
                if tables:
                    for table in tables:
                        cleaned = [
                            [str(cell or "") for cell in row] for row in table
                        ]
                        page_tables.append(cleaned)
                        for row in cleaned:
                            page_text += "\t".join(row) + "\n"
                else:
                    text = page.extract_text()
                    if text:
                        page_text = text

                pages.append({
                    "page": i,
                    "text": page_text.strip(),
                    "tables": page_tables,
                })
    except Exception:
        # If pdfplumber fails, try pymupdf as fallback
        try:
            import pymupdf

            doc = pymupdf.open(stream=content, filetype="pdf")
            for i, page in enumerate(doc, start=1):
                text = page.get_text()
                pages.append({"page": i, "text": text.strip(), "tables": []})
            doc.close()
        except Exception:
            pass

    return pages


def _count_pdf_pages(content: bytes) -> int:
    """Count the number of pages in a PDF."""
    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(content)) as pdf:
            return len(pdf.pages)
    except Exception:
        try:
            import pymupdf

            doc = pymupdf.open(stream=content, filetype="pdf")
            count = len(doc)
            doc.close()
            return count
        except Exception:
            return 0


class TakeoffService:
    """Business logic for takeoff operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = TakeoffRepository(session)

    async def upload_document(
        self,
        *,
        filename: str,
        content: bytes,
        size_bytes: int,
        owner_id: str,
        project_id: str | None = None,
    ) -> TakeoffDocument:
        """Upload and process a PDF document for takeoff."""
        # Count pages
        page_count = _count_pdf_pages(content)

        # Extract text from each page
        page_data = _extract_pdf_pages(content)
        full_text = "\n\n".join(p["text"] for p in page_data if p["text"])

        doc = TakeoffDocument(
            filename=filename,
            pages=page_count,
            size_bytes=size_bytes,
            content_type="application/pdf",
            status="uploaded",
            owner_id=uuid.UUID(owner_id),
            project_id=uuid.UUID(project_id) if project_id else None,
            extracted_text=full_text,
            page_data=page_data,
        )

        return await self.repo.create(doc)

    async def get_document(self, doc_id: str) -> TakeoffDocument | None:
        return await self.repo.get_by_id(uuid.UUID(doc_id))

    async def list_documents(
        self,
        owner_id: str,
        project_id: str | None = None,
    ) -> list[TakeoffDocument]:
        return await self.repo.list_for_user(
            uuid.UUID(owner_id),
            project_id=uuid.UUID(project_id) if project_id else None,
        )

    async def extract_tables(self, doc_id: str) -> dict:
        """Extract table data from an already-uploaded document."""
        doc = await self.repo.get_by_id(uuid.UUID(doc_id))
        if doc is None:
            return {"elements": [], "summary": {"total_elements": 0, "categories": {}}}

        elements = []
        idx = 0
        for page in (doc.page_data or []):
            for table in page.get("tables", []):
                if len(table) < 2:
                    continue
                # Use first row as header, remaining as data
                headers = [h.lower().strip() for h in table[0]]
                for row in table[1:]:
                    if not any(cell.strip() for cell in row):
                        continue
                    desc = row[0] if len(row) > 0 else ""
                    qty_str = row[1] if len(row) > 1 else "0"
                    unit = row[2] if len(row) > 2 else "pcs"

                    try:
                        qty = float(qty_str.replace(",", "."))
                    except (ValueError, AttributeError):
                        qty = 1.0

                    idx += 1
                    elements.append({
                        "id": f"ext_{idx}",
                        "category": "general",
                        "description": desc.strip() or f"Item {idx}",
                        "quantity": qty,
                        "unit": unit.strip() or "pcs",
                        "confidence": 0.6,
                    })

        categories: dict = {}
        for el in elements:
            cat = el["category"]
            if cat not in categories:
                categories[cat] = {"count": 0, "total_quantity": 0, "unit": el["unit"]}
            categories[cat]["count"] += 1
            categories[cat]["total_quantity"] += el["quantity"]

        return {
            "elements": elements,
            "summary": {"total_elements": len(elements), "categories": categories},
        }

    async def delete_document(self, doc_id: str) -> None:
        await self.repo.delete(uuid.UUID(doc_id))
