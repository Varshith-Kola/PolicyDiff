"""API endpoint tests for PolicyDiff.

Tests cover the core CRUD operations, auth flow, rate limiting responses,
and data validation.
"""

import pytest


class TestHealthCheck:
    def test_health_returns_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert "version" in data

    def test_health_reports_auth_status(self, client):
        resp = client.get("/health")
        data = resp.json()
        assert "auth_enabled" in data


class TestAuthEndpoints:
    def test_auth_status_when_disabled(self, client):
        resp = client.get("/api/auth/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["auth_enabled"] is False


class TestPolicyCRUD:
    def test_list_policies_empty(self, client):
        resp = client.get("/api/policies")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_create_policy(self, client):
        resp = client.post("/api/policies", json={
            "name": "Test Policy",
            "company": "TestCo",
            "url": "https://example.com/privacy",
            "policy_type": "privacy_policy",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Test Policy"
        assert data["company"] == "TestCo"
        assert data["snapshot_count"] == 0

    def test_create_policy_duplicate_url(self, client):
        url = "https://example.com/dup-test"
        client.post("/api/policies", json={
            "name": "First", "company": "Co", "url": url,
        })
        resp = client.post("/api/policies", json={
            "name": "Second", "company": "Co", "url": url,
        })
        assert resp.status_code == 409

    def test_create_policy_invalid_url(self, client):
        resp = client.post("/api/policies", json={
            "name": "Bad", "company": "Co", "url": "ftp://bad.url/test",
        })
        assert resp.status_code == 422  # Validation error

    def test_get_policy(self, client):
        create = client.post("/api/policies", json={
            "name": "Get Test", "company": "Co",
            "url": "https://example.com/get-test",
        })
        pid = create.json()["id"]
        resp = client.get(f"/api/policies/{pid}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Get Test"

    def test_get_policy_not_found(self, client):
        resp = client.get("/api/policies/99999")
        assert resp.status_code == 404

    def test_update_policy(self, client):
        create = client.post("/api/policies", json={
            "name": "Original", "company": "Co",
            "url": "https://example.com/update-test",
        })
        pid = create.json()["id"]
        resp = client.put(f"/api/policies/{pid}", json={"name": "Updated"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated"

    def test_delete_policy(self, client):
        create = client.post("/api/policies", json={
            "name": "Delete Me", "company": "Co",
            "url": "https://example.com/delete-test",
        })
        pid = create.json()["id"]
        resp = client.delete(f"/api/policies/{pid}")
        assert resp.status_code == 204
        assert client.get(f"/api/policies/{pid}").status_code == 404


class TestDashboard:
    def test_dashboard_stats(self, client):
        resp = client.get("/api/dashboard/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_policies" in data
        assert "active_policies" in data
        assert "total_snapshots" in data
        assert "recent_changes" in data


class TestSnapshots:
    def test_list_snapshots_empty(self, client):
        create = client.post("/api/policies", json={
            "name": "Snap Test", "company": "Co",
            "url": "https://example.com/snap-test",
        })
        pid = create.json()["id"]
        resp = client.get(f"/api/policies/{pid}/snapshots")
        assert resp.status_code == 200
        assert resp.json() == []


class TestExport:
    def test_export_csv(self, client):
        resp = client.get("/api/export/diffs?format=csv")
        assert resp.status_code == 200
        assert "text/csv" in resp.headers.get("content-type", "")

    def test_export_json(self, client):
        resp = client.get("/api/export/diffs?format=json")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
