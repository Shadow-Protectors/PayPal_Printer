# 🖨️ SmartPrint AI: Autonomous Campus Print Kiosk
### PayPal AI Hackathon 2026 Submission

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Demo Video](https://img.shields.io/badge/Demo%20Video-YouTube-red.svg)](https://youtu.be/oXzuF-Bvp4Y)
[![Backend: FastAPI](https://img.shields.io/badge/Backend-FastAPI-blue.svg)](https://fastapi.tiangolo.com/)
[![Payment: PayPal Sandbox](https://img.shields.io/badge/Payment-PayPal%20Sandbox-003087.svg)](https://developer.paypal.com/)
[![AI: Google Gemini](https://img.shields.io/badge/AI-Gemini%201.5%20Flash-orange.svg)](https://deepmind.google/technologies/gemini/)

---

## 📌 Executive Summary

**SmartPrint AI** is an autonomous campus print dispatch and self-service kiosk system that bridges **Google Gemini AI** and the **PayPal Developer Platform**. 

Students frequently waste significant money printing 50+ page PowerPoint presentations with dark themes, colored backgrounds, and low text density. SmartPrint AI ingests lecture PDFs, analyzes the academic structure using Gemini 1.5 Flash, strips out toner-heavy background graphics, and condenses the material into high-yield 2 to 4-page study revision sheets.

The server enforces zero-trust, server-authoritative pricing ($0.10/page), securely creates and verifies PayPal Sandbox captures, and unlocks single-use 6-digit release PINs expiring in 30 minutes for physical kiosk printing.

---

## 🏛️ System Architecture

```text
[Student Browser]
       │
       ▼ (1. Uploads PDF)
[FastAPI Server] ──(2. Extract Text & Pages)──► [Gemini 1.5 Flash]
       │                                                │
       │ (3. Returns Cost Comparison: Full vs AI)       ▼ (Generates Condensed Notes)
       ▼                                         [ReportLab PDF Engine]
[Student Selects Option]                                │
       │                                                ▼ (Compiles 2-Page Study PDF)
       ▼ (4. POST /api/kiosk/create-order)
[PayPal Sandbox API] (v2/checkout/orders)
       │
       ▼ (5. Student Approves in Sandbox Popup)
[FastAPI Server] ──(6. POST /api/kiosk/capture-order)──► [PayPal Capture API]
       │
       ▼ (7. Server verifies status == COMPLETED, Amount & Currency match)
[Generate Single-Use 6-Digit PIN] (30-min expiry)
       │
       ▼ (8. Student enters PIN on Kiosk Touchscreen)
[Physical Kiosk Tray] ──► Prints Document & Marks PIN Used
```

---

## 🌟 Key Engineering Highlights

### 1. Zero-Trust Server-Authoritative Pricing
* The frontend never dictates or sends payment amounts.
* The server counts pages directly from the uploaded document using `pypdf`, computes the exact charge, and creates the order through the **PayPal Orders v2 API**.
* On capture callback, `paypal_service.verify_capture()` validates that the transaction status is `COMPLETED`, currency is `USD`, and the paid amount matches the server-calculated value down to the cent before issuing any release code.

### 2. Idempotent Job Dispatch
* Every print job is keyed to the unique PayPal Order ID.
* If a network disconnect or client retry occurs, the capture endpoint re-checks the database and safely returns the existing release code without double-charging or duplicating queue records.

### 3. Resilient AI Optimization with Fallback
* Gemini 1.5 Flash extracts high-yield definitions, formulas, and bullet points.
* To safeguard against API rate limits or network latency, the service includes an automatic rule-based fallback that parses key conceptual sentences and compiles the PDF without blocking the payment flow.

---

## 🚀 Quickstart Guide

### Prerequisites
* Python 3.11+ (Tested on Python 3.13)
* Google Chrome or any modern browser

### Step 1: Install Dependencies
```powershell
pip install -r backend/requirements.txt
```

### Step 2: Configure Environment
Copy or edit `backend/.env`:
```ini
ENVIRONMENT=development
DATABASE_URL=sqlite:///./smartprint.db
STORAGE_ROOT=./storage

# PayPal Sandbox Credentials (from developer.paypal.com)
PAYPAL_CLIENT_ID=your_sandbox_client_id
PAYPAL_CLIENT_SECRET=your_sandbox_client_secret
PAYPAL_API_BASE=https://api-m.sandbox.paypal.com

# Optional: Google Gemini API Key for live AI summarization
GEMINI_API_KEY=your_gemini_api_key
```
*(Note: If no PayPal keys are set, the platform runs in automated sandbox simulation mode for offline testing).*

### Step 3: Run the Platform
```powershell
python run.py
```
Open **`http://127.0.0.1:8000`** in your browser.

---

## 🧪 Automated Testing

Run the full end-to-end test suite (testing PDF ingestion, server pricing, PayPal capture verification, idempotency, and single-use PIN expiration):

```powershell
cd backend
python -m pytest test_paypal_service.py test_kiosk_loop.py -v
```

---

## 📋 Hackathon Evaluation & Known Scope

* **Scope for Hackathon:** The web UI directly simulates both the student ordering flow and the campus kiosk PIN release pad in a unified, testable interface.
* **Production Roadmap:** In a full multi-building campus deployment, the physical Raspberry Pi print agent runs CUPS over local network sockets and polls `/api/kiosk/status` via authenticated mTLS tokens. PayPal webhooks will be added to handle background asynchronous captures for mobile browsers that close before the frontend callback.

---

## 📄 License
This project is licensed under the [MIT License](LICENSE).
