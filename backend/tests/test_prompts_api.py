from fastapi.testclient import TestClient
from tests.helpers import BASE, make


def test_create_detects_variables_and_starts_at_v1(client: TestClient) -> None:
    p = make(client, tags=["Resume ", "ATS", "resume"], description="d")
    assert p["version"] == 1
    assert [v["name"] for v in p["variables"]] == ["bullet", "job_title"]
    assert p["tags"] == ["ats", "resume"]
    assert p["deleted_at"] is None and p["created_at"].endswith(("Z", "+00:00"))
    got = client.get(f"/api/v1/prompts/{p['id']}").json()
    assert got["title"] == BASE["title"]


def test_validation_errors_are_problem_json(client: TestClient) -> None:
    r = client.post("/api/v1/prompts", json={"title": "", "body": "x"})
    assert r.status_code == 422
    assert r.headers["content-type"].startswith("application/problem+json")
    r = client.post("/api/v1/prompts", json={**BASE, "difficulty": "expert"})
    assert r.status_code == 422
    r = client.get("/api/v1/prompts/nope")
    assert r.status_code == 404
    assert r.json()["title"] == "Not found"


def test_patch_put_and_revisions(client: TestClient) -> None:
    p = make(client)
    pid = p["id"]
    r = client.patch(f"/api/v1/prompts/{pid}", json={"title": "New title"})
    assert r.status_code == 200 and r.json()["version"] == 2
    # no-op change creates no revision
    r = client.patch(f"/api/v1/prompts/{pid}", json={"title": "New title"})
    assert r.json()["version"] == 2
    # favorite/rating are not versioned
    r = client.patch(f"/api/v1/prompts/{pid}", json={"is_favorite": True, "rating": 4})
    assert r.json()["version"] == 2 and r.json()["is_favorite"] is True and r.json()["rating"] == 4
    # body change re-detects variables
    r = client.patch(f"/api/v1/prompts/{pid}", json={"body": "Only {{x}}"})
    assert [v["name"] for v in r.json()["variables"]] == ["x"] and r.json()["version"] == 3
    r = client.put(f"/api/v1/prompts/{pid}", json={"title": "Replaced", "body": "Plain text"})
    assert r.json()["version"] == 4 and r.json()["variables"] == []
    revs = client.get(f"/api/v1/prompts/{pid}/revisions").json()
    assert [x["version"] for x in revs] == [4, 3, 2, 1]
    assert revs[-1]["snapshot"]["title"] == BASE["title"]
    r = client.post(f"/api/v1/prompts/{pid}/revisions/1/restore")
    assert r.status_code == 200
    assert r.json()["title"] == BASE["title"] and r.json()["version"] == 5
    assert client.post(f"/api/v1/prompts/{pid}/revisions/99/restore").status_code == 404


def test_trash_restore_and_permanent_delete(client: TestClient) -> None:
    pid = make(client)["id"]
    assert client.delete(f"/api/v1/prompts/{pid}", params={"permanent": True}).status_code == 409
    assert client.delete(f"/api/v1/prompts/{pid}").status_code == 204
    assert client.get("/api/v1/prompts").json()["total"] == 0
    trash = client.get("/api/v1/prompts", params={"trash": True}).json()
    assert trash["total"] == 1 and trash["items"][0]["deleted_at"]
    assert client.post(f"/api/v1/prompts/{pid}/restore").json()["deleted_at"] is None
    assert client.get("/api/v1/prompts").json()["total"] == 1
    client.delete(f"/api/v1/prompts/{pid}")
    assert client.delete(f"/api/v1/prompts/{pid}", params={"permanent": True}).status_code == 204
    assert client.get(f"/api/v1/prompts/{pid}").status_code == 404


def test_purge_trash(client: TestClient) -> None:
    a, b = make(client)["id"], make(client, title="Other")["id"]
    client.delete(f"/api/v1/prompts/{a}")
    assert client.delete("/api/v1/trash", params={"older_than_days": 1}).json() == {"purged": 0}
    assert client.delete("/api/v1/trash").json() == {"purged": 1}
    assert client.get(f"/api/v1/prompts/{a}").status_code == 404
    assert client.get(f"/api/v1/prompts/{b}").status_code == 200


def test_duplicate(client: TestClient) -> None:
    p = make(client, tags=["a"], is_favorite=True)
    d = client.post(f"/api/v1/prompts/{p['id']}/duplicate").json()
    assert d["id"] != p["id"] and d["title"].endswith("(copy)")
    assert d["tags"] == ["a"] and d["is_favorite"] is False and d["version"] == 1


def test_render(client: TestClient) -> None:
    p = make(client, variables=[{"name": "job_title", "default": "Engineer"}])
    r = client.post(f"/api/v1/prompts/{p['id']}/render", json={"values": {"bullet": "Did stuff"}})
    assert r.json()["rendered"] == "Rewrite Did stuff for Engineer"
    assert r.json()["missing"] == []
    r = client.post(f"/api/v1/prompts/{p['id']}/render", json={"values": {}})
    assert r.json()["missing"] == ["bullet"]


def test_list_filters_and_pagination(client: TestClient) -> None:
    client.post("/api/v1/categories", json={"name": "Career"})
    client.post("/api/v1/categories", json={"name": "Resume", "parent": "career"})
    client.post("/api/v1/categories", json={"name": "Coding"})
    ids = [
        make(client, title="r1", category="resume", tags=["a", "b"], difficulty="advanced")["id"],
        make(client, title="r2", category="resume", tags=["a"])["id"],
        make(client, title="c1", category="coding", tags=["b"], is_favorite=True)["id"],
        make(client, title="n1")["id"],
        make(client, title="n2")["id"],
    ]
    q = lambda **p: client.get("/api/v1/prompts", params=p).json()  # noqa: E731
    assert q(category="career")["total"] == 2  # includes child category
    assert q(category="resume")["total"] == 2
    assert q(category="coding")["total"] == 1
    assert q(tags=["a", "b"])["total"] == 1
    assert q(tags=["a", "b"], tags_mode="any")["total"] == 3
    assert q(difficulty="advanced")["total"] == 1
    assert q(favorite=True)["total"] == 1
    assert client.get("/api/v1/prompts", params={"category": "zzz"}).status_code == 404
    # keyset pagination: no dupes, no gaps
    seen, cursor = [], None
    while True:
        page = q(limit=2, **({"cursor": cursor} if cursor else {}))
        seen += [i["id"] for i in page["items"]]
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert sorted(seen) == sorted(ids) and len(seen) == len(set(seen))
    assert client.get("/api/v1/prompts", params={"cursor": "garbage"}).status_code == 422


def bulk(client: TestClient, payload: dict) -> object:  # type: ignore[type-arg]
    return client.post("/api/v1/prompts/bulk", json=payload)


def test_bulk_actions(client: TestClient) -> None:
    client.post("/api/v1/categories", json={"name": "SEO"})
    a, b = make(client)["id"], make(client, title="B")["id"]
    ids = [a, b, "missing"]
    r = client.post(
        "/api/v1/prompts/bulk", json={"ids": ids, "action": "add_tags", "tags": ["x", "y"]}
    )
    assert r.json() == {"affected": 2, "not_found": ["missing"]}
    bulk(client, {"ids": [a], "action": "remove_tags", "tags": ["x"]})
    assert client.get(f"/api/v1/prompts/{a}").json()["tags"] == ["y"]
    client.post(
        "/api/v1/prompts/bulk", json={"ids": ids, "action": "set_category", "category": "seo"}
    )
    assert client.get(f"/api/v1/prompts/{b}").json()["category"]["slug"] == "seo"
    bulk(client, {"ids": [a], "action": "favorite"})
    assert client.get(f"/api/v1/prompts/{a}").json()["is_favorite"] is True
    bulk(client, {"ids": [a, b], "action": "delete"})
    assert client.get("/api/v1/prompts").json()["total"] == 0
    bulk(client, {"ids": [a], "action": "restore"})
    assert client.get("/api/v1/prompts").json()["total"] == 1
    r = bulk(client, {"ids": [a], "action": "add_tags"})
    assert r.status_code == 422
