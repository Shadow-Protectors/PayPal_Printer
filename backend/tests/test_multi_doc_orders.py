import pytest
from app.db.models.order import Order
from app.db.models.document import Document
from tests.test_documents_and_orders import create_sample_pdf
import io
from PIL import Image

def create_sample_png():
    img = Image.new("RGB", (100, 100), color=(73, 109, 137))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

def test_multi_document_order_pricing_and_merging(client, test_print_server, db_session):
    # 1. Upload a PNG image (1 page)
    png_bytes = create_sample_png()
    up1 = client.post(
        "/api/documents/upload",
        files={"file": ("130210.png", png_bytes, "image/png")}
    )
    assert up1.status_code == 201
    doc1_id = up1.json()["documentId"]

    # 2. Upload a 13-page PDF
    pdf_bytes = create_sample_pdf(13)
    up2 = client.post(
        "/api/documents/upload",
        files={"file": ("2nd Years.pdf", pdf_bytes, "application/pdf")}
    )
    assert up2.status_code == 201
    doc2_id = up2.json()["documentId"]

    # 3. Create Multi-document order:
    # 130210.png: 1 page, 1 copy, B&W -> 1 * 2.00 = 2.00
    # 2nd Years.pdf: 13 pages, 1 copy, B&W -> 13 * 2.00 = 26.00
    # Total = 28.00
    order_payload = {
        "print_server_id": test_print_server.id,
        "items": [
            {
                "document_id": doc1_id,
                "settings": {
                    "copies": 1,
                    "colour": False,
                    "page_range": "all"
                }
            },
            {
                "document_id": doc2_id,
                "settings": {
                    "copies": 1,
                    "colour": False,
                    "page_range": "all"
                }
            }
        ]
    }

    res = client.post("/api/orders", json=order_payload)
    assert res.status_code == 201
    data = res.json()

    # Verify total price is ₹28.00 (₹2.00 + ₹26.00)
    assert data["amount"] == 28.00
    # Merged PDF has 14 pages (1 page image + 13 pages PDF)
    assert data["totalPages"] == 14
    assert "DOC-COMBINED-" in data["documentId"]

    # Verify order in DB
    order_in_db = db_session.query(Order).filter(Order.id == data["id"]).first()
    assert order_in_db is not None
    assert order_in_db.amount == 28.00
    assert order_in_db.total_pages == 14
    assert len(order_in_db.print_settings["items"]) == 2
    assert order_in_db.print_settings["items"][0]["amount"] == 2.00
    assert order_in_db.print_settings["items"][1]["amount"] == 26.00
