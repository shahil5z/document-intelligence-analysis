from fastapi.testclient import TestClient


def test_admin_endpoints_require_admin_role(
    client: TestClient, user_headers: dict[str, str]
) -> None:
    for path in ("/admin/users", "/admin/audit-logs"):
        response = client.get(path, headers=user_headers)
        assert response.status_code == 403, path
        assert response.json()["error"]["code"] == "forbidden"


def test_admin_endpoints_require_authentication(client: TestClient) -> None:
    assert client.get("/admin/users").status_code == 401


def test_admin_can_list_users(
    client: TestClient, admin_headers: dict[str, str], user_headers: dict[str, str]
) -> None:
    response = client.get("/admin/users", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert {item["email"] for item in body["items"]} == {"admin@example.com", "alice@example.com"}


def test_admin_can_filter_audit_logs(
    client: TestClient, admin_headers: dict[str, str], user_headers: dict[str, str]
) -> None:
    response = client.get(
        "/admin/audit-logs", params={"action": "user.registered"}, headers=admin_headers
    )
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["action"] == "user.registered"
    assert "request_id" in items[0]["metadata"]


def test_user_sees_only_own_audit_logs(
    client: TestClient, user_headers: dict[str, str], other_user_headers: dict[str, str]
) -> None:
    response = client.get("/audit-logs/me", headers=user_headers)
    assert response.status_code == 200
    me = client.get("/auth/me", headers=user_headers).json()
    items = response.json()["items"]
    assert items
    assert all(item["user_id"] == me["id"] for item in items)
