from tests.conftest import create_sample_pdf

def test_document_upload_without_login(client):
    """Verifies that any user can upload documents without login."""
    pdf_bytes = create_sample_pdf(4)

    res = client.post(
        "/api/documents/upload",
        files={"file": ("syllabus.pdf", pdf_bytes, "application/pdf")}
    )
    assert res.status_code == 201
    data = res.json()
    assert data["originalFilename"] == "syllabus.pdf"
    assert data["pages"] == 4
    assert data["status"] == "ACTIVE"
    assert data["documentId"].startswith("doc_")

def test_document_upload_corrupt_rejected(client):
    corrupt_bytes = b"%PDF-1.4 Fake corrupted body text"

    res = client.post(
        "/api/documents/upload",
        files={"file": ("broken.pdf", corrupt_bytes, "application/pdf")}
    )
    assert res.status_code == 400
    assert res.json()["error"] == "INVALID_FILE"

def test_order_creation_and_pricing_without_login(client, test_print_server):
    """Verifies that an order can be created and priced without login."""
    pdf_bytes = create_sample_pdf(5)

    # 1. Upload 5-page PDF with no auth
    up_res = client.post(
        "/api/documents/upload",
        files={"file": ("project.pdf", pdf_bytes, "application/pdf")}
    )
    doc_id = up_res.json()["documentId"]

    # 2. Create order selecting pages "1-3,5" (total 4 pages), copies = 2
    # Price formula: 4 pages * 2 copies * 2.00 rate = 16.00
    order_res = client.post(
        "/api/orders",
        json={
            "document_id": doc_id,
            "print_server_id": test_print_server.id,
            "settings": {
                "copies": 2,
                "page_range": "1-3,5",
                "colour": False,
                "sides": "two-sided-long-edge",
                "paper_size": "A4",
                "orientation": "portrait"
            }
        }
    )
    assert order_res.status_code == 201
    order_data = order_res.json()
    assert order_data["totalPages"] == 4
    assert order_data["copies"] == 2
    assert order_data["amount"] == 16.0
    assert order_data["status"] == "CREATED"

def test_order_invalid_page_range_exceeds(client, test_print_server):
    pdf_bytes = create_sample_pdf(2)

    up_res = client.post(
        "/api/documents/upload",
        files={"file": ("short.pdf", pdf_bytes, "application/pdf")}
    )
    doc_id = up_res.json()["documentId"]

    # Attempt to request page 10 on a 2-page document
    order_res = client.post(
        "/api/orders",
        json={
            "document_id": doc_id,
            "print_server_id": test_print_server.id,
            "settings": {
                "copies": 1,
                "page_range": "1-10"
            }
        }
    )
    assert order_res.status_code == 400
    assert order_res.json()["error"] == "INVALID_PAGE_RANGE"

def test_order_creation_flat_payload_without_nested_settings(client, test_print_server):
    pdf_bytes = create_sample_pdf(3)

    up_res = client.post(
        "/api/documents/upload",
        files={"file": ("notes.pdf", pdf_bytes, "application/pdf")}
    )
    doc_id = up_res.json()["documentId"]

    # Post flat payload without "settings" object (the exact payload from the user's issue)
    order_res = client.post(
        "/api/orders",
        json={
            "documentId": doc_id,
            "printServerId": test_print_server.id,
            "colorMode": "MONO",
            "duplex": False,
            "copies": 1,
            "pageRange": "ALL",
            "paymentMethod": "RAZORPAY"
        }
    )
    assert order_res.status_code == 201
    data = order_res.json()
    assert data["totalPages"] == 3
    assert data["copies"] == 1
    assert data["status"] == "CREATED"
