from lxml import etree

from app.main import app
from app.services.submission import Receipt, get_gateway

NS = {"d": "urn:example:tax-declaration:v1"}


def add(client, tp, kind, cents, day="2025-03-15"):
    r = client.post(
        f"/taxpayers/{tp['id']}/entries",
        json={"kind": kind, "amount_cents": cents, "occurred_on": day, "category": "services"},
    )
    assert r.status_code == 201, r.text


def generate(client, tp, method="actual"):
    return client.post(f"/taxpayers/{tp['id']}/declarations", json={"tax_year": 2025, "expense_method": method})


def test_duplicate_tax_id_rejected(client, taxpayer):
    r = client.post("/taxpayers", json={"full_name": "Someone Else", "tax_id": "CZ8001011234"})
    assert r.status_code == 409


def test_invalid_input_rejected(client, taxpayer):
    r = client.post(
        f"/taxpayers/{taxpayer['id']}/entries",
        json={"kind": "income", "amount_cents": -5, "occurred_on": "2025-01-01", "category": "x"},
    )
    assert r.status_code == 422


def test_full_flow_generate_approve_submit(client, taxpayer):
    add(client, taxpayer, "income", 100_000_000)
    add(client, taxpayer, "expense", 20_000_000)
    add(client, taxpayer, "income", 5_000_000, day="2024-12-31")  # other year, ignored

    r = generate(client, taxpayer)
    assert r.status_code == 201, r.text
    dec = r.json()
    assert dec["status"] == "draft"
    assert dec["totals"]["income_cents"] == 100_000_000

    xml = client.get(f"/declarations/{dec['id']}/xml")
    assert xml.headers["content-type"].startswith("application/xml")
    doc = etree.fromstring(xml.content)
    assert doc.findtext("d:Business/d:IncomeCents", namespaces=NS) == "100000000"
    assert doc.findtext("d:Taxpayer/d:DataBoxId", namespaces=NS) == "abc1234"

    assert client.post(f"/declarations/{dec['id']}/submit").status_code == 409  # not approved yet
    assert client.post(f"/declarations/{dec['id']}/approve").json()["status"] == "approved"

    first = client.post(f"/declarations/{dec['id']}/submit").json()
    second = client.post(f"/declarations/{dec['id']}/submit").json()
    assert first["status"] == "submitted"
    assert first["receipt_id"].startswith("SBX-")
    assert second["receipt_id"] == first["receipt_id"]  # idempotent, no double submission

    actions = [a["action"] for a in client.get(f"/declarations/{dec['id']}/audit").json()]
    assert actions == ["generated", "approved", "submitted"]


def test_draft_can_be_regenerated_but_approved_year_is_locked(client, taxpayer):
    add(client, taxpayer, "income", 50_000_000)
    dec = generate(client, taxpayer).json()

    add(client, taxpayer, "income", 10_000_000)
    regen = generate(client, taxpayer, method="flat_rate")
    assert regen.status_code == 200
    assert regen.json()["id"] == dec["id"]
    assert regen.json()["totals"]["income_cents"] == 60_000_000

    client.post(f"/declarations/{dec['id']}/approve")
    r = client.post(
        f"/taxpayers/{taxpayer['id']}/entries",
        json={"kind": "income", "amount_cents": 1, "occurred_on": "2025-06-01", "category": "late"},
    )
    assert r.status_code == 409
    assert generate(client, taxpayer).status_code == 409


def test_no_entries_means_no_declaration(client, taxpayer):
    assert generate(client, taxpayer).status_code == 422


def test_rejected_submission(client, taxpayer):
    class RejectingGateway:
        def submit(self, *, declaration_id, xml):
            return Receipt(receipt_id="", accepted=False, message="Signature missing")

    add(client, taxpayer, "income", 1_000_000)
    dec = generate(client, taxpayer).json()
    client.post(f"/declarations/{dec['id']}/approve")
    app.dependency_overrides[get_gateway] = RejectingGateway
    try:
        r = client.post(f"/declarations/{dec['id']}/submit")
    finally:
        app.dependency_overrides.pop(get_gateway)
    assert r.status_code == 502
    assert client.get(f"/declarations/{dec['id']}").json()["status"] == "rejected"


def test_validate_endpoint_reports_errors(client):
    bad = '<Declaration xmlns="urn:example:tax-declaration:v1" version="1.0"><Header/></Declaration>'
    r = client.post("/xml/validate", content=bad, headers={"content-type": "application/xml"})
    assert r.json()["valid"] is False
    assert r.json()["errors"]

    broken = client.post("/xml/validate", content="<not-closed>", headers={"content-type": "application/xml"})
    assert broken.json()["valid"] is False
