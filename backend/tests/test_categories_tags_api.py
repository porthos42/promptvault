from fastapi.testclient import TestClient
from tests.helpers import make


def test_category_crud_and_tree(client: TestClient) -> None:
    r = client.post("/api/v1/categories", json={"name": "Job Interviews", "icon": "briefcase"})
    assert r.status_code == 201
    assert r.json()["slug"] == "job-interviews" and r.json()["prompt_count"] == 0
    assert client.post("/api/v1/categories", json={"name": "Job Interviews"}).status_code == 409
    r = client.post("/api/v1/categories", json={"name": "Behavioral", "parent": "job-interviews"})
    assert r.json()["parent"] == "job-interviews"
    assert (
        client.post("/api/v1/categories", json={"name": "X", "parent": "nope"}).status_code == 404
    )

    r = client.patch(
        "/api/v1/categories/behavioral", json={"name": "Behavioral Qs", "sort_order": 5}
    )
    assert r.json()["name"] == "Behavioral Qs" and r.json()["sort_order"] == 5
    # cycle guard
    r = client.patch("/api/v1/categories/job-interviews", json={"parent": "behavioral"})
    assert r.status_code == 422
    # unparent
    r = client.patch("/api/v1/categories/behavioral", json={"parent": None})
    assert r.json()["parent"] is None

    make(client, category="behavioral")
    cats = {c["slug"]: c for c in client.get("/api/v1/categories").json()}
    assert cats["behavioral"]["prompt_count"] == 1 and cats["job-interviews"]["prompt_count"] == 0

    assert client.delete("/api/v1/categories/behavioral").status_code == 204
    assert client.get("/api/v1/categories/behavioral").status_code == 404
    # prompt survives, uncategorised
    items = client.get("/api/v1/prompts").json()["items"]
    assert len(items) == 1 and items[0]["category"] is None


def test_unknown_category_on_prompt_is_404(client: TestClient) -> None:
    r = client.post("/api/v1/prompts", json={"title": "t", "body": "b", "category": "nope"})
    assert r.status_code == 404


def test_tags_list_rename_merge_delete(client: TestClient) -> None:
    a = make(client, tags=["seo", "blog"])["id"]
    b = make(client, title="B", tags=["search"])["id"]
    tags = {t["name"]: t["prompt_count"] for t in client.get("/api/v1/tags").json()}
    assert tags == {"seo": 1, "blog": 1, "search": 1}

    r = client.put("/api/v1/tags/blog", json={"name": "Content Marketing"})
    assert r.json() == {"name": "content-marketing", "prompt_count": 1}

    r = client.put("/api/v1/tags/search", json={"name": "seo"})  # merge
    assert r.json() == {"name": "seo", "prompt_count": 2}
    assert client.get(f"/api/v1/prompts/{b}").json()["tags"] == ["seo"]

    assert client.delete("/api/v1/tags/seo").status_code == 204
    assert client.get(f"/api/v1/prompts/{a}").json()["tags"] == ["content-marketing"]
    assert client.delete("/api/v1/tags/seo").status_code == 404

    # trashed prompts do not count toward live tag counts
    client.delete(f"/api/v1/prompts/{a}")
    assert client.get("/api/v1/tags").json() == []
    assert client.get("/api/v1/tags", params={"include_unused": True}).json()
