import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models.user import User, UserRole
from app.db.models.department import Department
from app.db.models.print_server import PrintServer, PrintServerStatus
from app.db.models.printer import Printer
from app.db.models.discovered_printer import DiscoveredPrinter
from app.config.settings import settings


@pytest.fixture
def admin_token(client: TestClient, db_session: Session):
    admin = db_session.query(User).filter(User.role == UserRole.ADMIN).first()
    if not admin:
        admin = User(
            id=999,
            email="admin_test@test.local",
            full_name="Admin Test",
            role=UserRole.ADMIN,
            is_active=True
        )
        db_session.add(admin)
        db_session.commit()

    from app.config.security import create_access_token
    token = create_access_token(data={"sub": str(admin.id), "role": admin.role.value})
    return token


@pytest.fixture
def test_setup(db_session: Session):
    dept = db_session.query(Department).filter(Department.name == "Computer Science").first()
    if not dept:
        dept = Department(name="Computer Science", code="CSE")
        db_session.add(dept)
        db_session.commit()
        db_session.refresh(dept)

    server = db_session.query(PrintServer).filter(PrintServer.id == "AGENT-TEST-01").first()
    if not server:
        from app.config.security import hash_token
        server = PrintServer(
            id="AGENT-TEST-01",
            name="CSE Lab Agent 1",
            location="Room 101",
            device_token_hash=hash_token("test-agent-token"),
            department_id=dept.id,
            hostname="cse-pi-01.local",
            ip_address="192.168.1.150",
            status=PrintServerStatus.ONLINE,
            is_enabled=True,
        )
        db_session.add(server)
        db_session.commit()
        db_session.refresh(server)

    return {"department": dept, "server": server}



def test_printer_registration_validation(client: TestClient, admin_token: str, test_setup):
    headers = {"Authorization": f"Bearer {admin_token}"}
    dept = test_setup["department"]
    server = test_setup["server"]

    # 1. Reject invalid print agent
    res_bad_agent = client.post(
        "/api/admin/printers",
        headers=headers,
        json={
            "cups_printer_name": "HP_LaserJet_400",
            "display_name": "HP LaserJet 400",
            "ip_address": "192.168.1.200",
            "protocol": "Socket",
            "server_id": "NON_EXISTENT_AGENT",
            "department_id": dept.id,
            "location": "Room 101",
            "is_enabled": True
        }
    )
    assert res_bad_agent.status_code == 400
    assert "Selected Print Agent" in res_bad_agent.json()["message"]

    # 2. Successfully register printer
    payload = {
        "cups_printer_name": "HP_LaserJet_400",
        "display_name": "Department Laser Printer",
        "ip_address": "192.168.1.200",
        "protocol": "Socket",
        "device_uri": "socket://192.168.1.200:9100",
        "server_id": server.id,
        "department_id": dept.id,
        "location": "Room 101 Corner",
        "model": "HP LaserJet 400 M401dn",
        "supports_color": False,
        "supports_duplex": True,
        "is_enabled": True
    }
    res = client.post("/api/admin/printers", headers=headers, json=payload)
    assert res.status_code == 201
    created = res.json()

    assert created["cups_printer_name"] == "HP_LaserJet_400"
    assert created["display_name"] == "Department Laser Printer"
    assert created["ip_address"] == "192.168.1.200"
    assert created["protocol"] == "Socket"
    assert created["server_id"] == server.id
    assert created["is_enabled"] is True
    # Crucial requirement: Only after successful validation should printer be active!
    assert created["is_active"] is False
    assert created["test_status"] == "PENDING"

    # 3. Reject duplicate registration on same agent
    res_dup = client.post("/api/admin/printers", headers=headers, json=payload)
    assert res_dup.status_code == 400
    assert "already registered" in res_dup.json()["message"]


def test_test_connection_when_no_printer_connected(client: TestClient, admin_token: str, test_setup, db_session: Session):
    headers = {"Authorization": f"Bearer {admin_token}"}
    dept = test_setup["department"]
    server = test_setup["server"]

    # Register printer with non-routable dummy IP (representing no printer connected)
    reg_payload = {
        "cups_printer_name": "HP_Unreachable_01",
        "display_name": "Unreachable Printer",
        "ip_address": "192.0.2.1",  # Test-net IP that won't connect
        "protocol": "Socket",
        "server_id": server.id,
        "department_id": dept.id,
        "is_enabled": True
    }
    reg_res = client.post("/api/admin/printers", headers=headers, json=reg_payload)
    assert reg_res.status_code == 201
    printer_id = reg_res.json()["id"]

    # Trigger Test Connection
    test_res = client.post(f"/api/admin/printers/{printer_id}/test-connection", headers=headers)
    assert test_res.status_code == 200
    result = test_res.json()

    # Connection must fail cleanly without crashing, printer remains NOT active
    assert result["success"] is False
    assert result["is_active"] is False
    assert result["status"] == "FAILED"
    assert result["reachable"] is False
    assert "No recent matching" in result["message"]

    # Verify database state
    p = db_session.query(Printer).filter(Printer.id == printer_id).first()
    assert p.is_active is False
    assert p.test_status == "FAILED"
    assert p.last_tested_at is not None


def test_heartbeat_sync_flags_mismatches_and_records_discovered(client: TestClient, admin_token: str, test_setup, db_session: Session):

    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    server = test_setup["server"]
    dept = test_setup["department"]

    # Register Printer A with IP 192.168.1.100
    reg_res = client.post(
        "/api/admin/printers",
        headers=admin_headers,
        json={
            "cups_printer_name": "Printer_Registered_A",
            "display_name": "Registered Printer A",
            "ip_address": "192.168.1.100",
            "protocol": "Socket",
            "server_id": server.id,
            "department_id": dept.id,
            "is_enabled": True
        }
    )
    assert reg_res.status_code == 201

    agent_headers = {"Authorization": "Bearer test-agent-token"}

    # Case 1: Agent reports heartbeat with an IP mismatch for Printer_Registered_A
    # (e.g. reported 192.168.1.105 instead of registered 192.168.1.100)
    # AND reports an unregistered printer "New_Unknown_Printer"
    heartbeat_payload = {
        "printerState": "READY",
        "paperState": "AVAILABLE",
        "printers": [
            {
                "cups_printer_name": "Printer_Registered_A",
                "ip_address": "192.168.1.105",
                "device_uri": "socket://192.168.1.105:9100",
                "status": "READY",
                "jobs": 0
            },
            {
                "cups_printer_name": "New_Unknown_Printer",
                "ip_address": "192.168.1.199",
                "device_uri": "socket://192.168.1.199:9100",
                "status": "READY",
                "jobs": 0
            }
        ]
    }
    hb_res = client.post("/api/agent/heartbeat", headers=agent_headers, json=heartbeat_payload)
    assert hb_res.status_code == 200

    # Verify Admin Get Printers shows the IP Mismatch flagged
    printers_res = client.get("/api/admin/printers", headers=admin_headers)
    assert printers_res.status_code == 200
    printers = printers_res.json()

    target_printer = next(p for p in printers if p["cups_printer_name"] == "Printer_Registered_A")
    assert target_printer["has_mismatch"] is True
    assert "IP Mismatch" in target_printer["mismatch_details"]

    # Verify that the backend DID NOT automatically create a Printer record for New_Unknown_Printer
    assert not any(p["cups_printer_name"] == "New_Unknown_Printer" for p in printers)

    # Verify that New_Unknown_Printer WAS added to DiscoveredPrinter
    disc_res = client.get("/api/admin/discovered-printers", headers=admin_headers)
    assert disc_res.status_code == 200
    disc_list = disc_res.json()
    assert any(d["cups_printer_name"] == "New_Unknown_Printer" for d in disc_list)

    # Case 2: Agent reports empty printers list (no printers connected)
    hb_empty = client.post(
        "/api/agent/heartbeat",
        headers=agent_headers,
        json={
            "printerState": "OFFLINE",
            "paperState": "UNAVAILABLE",
            "printers": []
        }
    )
    assert hb_empty.status_code == 200

    # Registered printer should now be flagged as not detected / offline
    printers_res2 = client.get("/api/admin/printers", headers=admin_headers)
    target_printer2 = next(p for p in printers_res2.json() if p["cups_printer_name"] == "Printer_Registered_A")
    assert target_printer2["has_mismatch"] is True
    assert "not detected in CUPS" in target_printer2["mismatch_details"]


def test_admin_print_agents_and_discovery_dismiss(client: TestClient, admin_token: str, db_session: Session):
    headers = {"Authorization": f"Bearer {admin_token}"}

    # Register a new agent
    agent_res = client.post(
        "/api/admin/print-agents",
        headers=headers,
        json={
            "id": "AGENT-NEW-99",
            "name": "Library Pi Station",
            "location": "Library 2nd Floor",
            "hostname": "lib-pi.local",
            "ip_address": "192.168.1.77",
            "software_version": "1.4.0"
        }
    )
    assert agent_res.status_code == 201
    assert agent_res.json()["id"] == "AGENT-NEW-99"

    # List agents
    list_res = client.get("/api/admin/print-agents", headers=headers)
    assert list_res.status_code == 200
    assert any(a["id"] == "AGENT-NEW-99" for a in list_res.json())

    # Dismiss a discovered printer
    disc = DiscoveredPrinter(
        id="TEMP-DISC-01",
        server_id="AGENT-NEW-99",
        cups_printer_name="Temp_Printer",
        first_seen=datetime.now(timezone.utc),
        last_seen=datetime.now(timezone.utc)
    )
    db_session.add(disc)
    db_session.commit()


    del_disc = client.delete("/api/admin/discovered-printers/TEMP-DISC-01", headers=headers)
    assert del_disc.status_code == 200

    # Delete agent
    del_agent = client.delete("/api/admin/print-agents/AGENT-NEW-99", headers=headers)
    assert del_agent.status_code == 200
