def test_erp_routes_require_authentication(client):
    for path in ("/api/erp/overview", "/api/erp/customer", "/api/erp/customer/example"):
        assert client.get(path).status_code == 401


def test_layout_does_not_publish_fixture_records(client):
    response = client.get("/api/layout/erpclaw")
    assert response.status_code == 200
    layout = response.json()
    assert "customer" in layout["entities"]
    assert not {"mockData", "kpis", "workflows", "attention", "activity"} & layout.keys()


def test_production_health_requires_erp_database(client, monkeypatch):
    import main

    def unavailable():
        raise RuntimeError("connection failed")

    monkeypatch.setattr(main, "_is_production", True)
    monkeypatch.setattr(main, "get_erp_pg_db", unavailable)
    assert client.get("/api/health").status_code == 503
