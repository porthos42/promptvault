import time

from fastapi.testclient import TestClient
from tests.helpers import make


def search(client: TestClient, q: str, **params: object) -> dict:  # type: ignore[type-arg]
    r = client.get("/api/v1/prompts", params={"q": q, **params})
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


def titles(res: dict) -> list[str]:  # type: ignore[type-arg]
    return [i["title"] for i in res["items"]]


def seed(client: TestClient) -> None:
    client.post("/api/v1/categories", json={"name": "Marketing"})
    client.post("/api/v1/categories", json={"name": "Coding"})
    make(
        client,
        title="Cold Email Writer",
        body="Write a cold outreach email to {{prospect}}.",
        category="marketing",
        tags=["sales", "email"],
        description="B2B outreach",
    )
    make(
        client,
        title="SEO Blog Outline",
        body="Outline a blog post about {{topic}} for search.",
        category="marketing",
        tags=["seo"],
        difficulty="advanced",
    )
    make(
        client,
        title="Code Reviewer",
        body="Review this {{language}} code. Mention any email logic.",
        category="coding",
        tags=["review"],
    )
    make(
        client,
        title="Resume Bullet Rewriter",
        body="Rewrite resume bullets for impact.",
        tags=["resume", "career"],
    )


def test_basic_search_ranks_title_above_body(client: TestClient) -> None:
    seed(client)
    res = search(client, "email")
    # "Cold Email Writer" has email in title+tags; "Code Reviewer" only in body
    assert titles(res) == ["Cold Email Writer", "Code Reviewer"]
    assert res["total"] == 2 and res["sort"] == "relevance" and res["corrected_query"] is None


def test_prefix_stemming_phrase_and_tags(client: TestClient) -> None:
    seed(client)
    assert titles(search(client, "outl")) == ["SEO Blog Outline"]  # prefix
    assert titles(search(client, "rewriting")) == ["Resume Bullet Rewriter"]  # stemming
    assert titles(search(client, '"cold outreach"')) == ["Cold Email Writer"]  # phrase
    assert search(client, '"outreach cold"')["total"] == 0
    assert titles(search(client, "career")) == ["Resume Bullet Rewriter"]  # tags are indexed
    assert titles(search(client, "b2b")) == ["Cold Email Writer"]  # description is indexed
    assert titles(search(client, "blog seo")) == ["SEO Blog Outline"]  # AND semantics


def test_hostile_input_is_safe(client: TestClient) -> None:
    seed(client)
    for q in [
        '"',
        "*",
        "email OR",
        "NEAR(",
        "title:email",
        "a AND (",
        "'; DROP TABLE prompt;--",
        "{{x}}",
    ]:
        r = client.get("/api/v1/prompts", params={"q": q})
        assert r.status_code == 200, (q, r.text)
    assert client.get("/api/v1/prompts").json()["total"] == 4


def test_search_follows_edits_trash_and_tag_changes(client: TestClient) -> None:
    seed(client)
    pid = search(client, "outline")["items"][0]["id"]
    client.patch(f"/api/v1/prompts/{pid}", json={"title": "Content Planner"})
    assert search(client, "outline")["total"] == 1  # body still says "Outline"
    assert titles(search(client, "planner")) == ["Content Planner"]
    client.patch(f"/api/v1/prompts/{pid}", json={"tags": ["editorial"]})
    assert titles(search(client, "editorial")) == ["Content Planner"]
    assert search(client, "seo")["total"] == 0
    client.put("/api/v1/tags/editorial", json={"name": "calendar"})
    assert titles(search(client, "calendar")) == ["Content Planner"]
    assert search(client, "editorial")["total"] == 0
    client.delete("/api/v1/tags/calendar")
    assert search(client, "calendar")["total"] == 0
    client.post("/api/v1/prompts/bulk", json={"ids": [pid], "action": "add_tags", "tags": ["bulk"]})
    assert titles(search(client, "bulk")) == ["Content Planner"]
    client.delete(f"/api/v1/prompts/{pid}")
    assert search(client, "planner")["total"] == 0  # trash excluded
    assert search(client, "planner", trash=True)["total"] == 1
    # restoring puts it back in the index; permanent delete leaves the index consistent
    client.post(f"/api/v1/prompts/{pid}/restore")
    assert titles(search(client, "planner")) == ["Content Planner"]
    assert search(client, "planner", trash=True)["total"] == 0
    client.delete(f"/api/v1/prompts/{pid}")
    client.delete(f"/api/v1/prompts/{pid}", params={"permanent": True})
    assert search(client, "planner")["total"] == 0
    assert search(client, "email")["total"] == 2  # index still healthy


def test_search_combines_with_filters(client: TestClient) -> None:
    seed(client)
    assert titles(search(client, "email", category="marketing")) == ["Cold Email Writer"]
    assert titles(search(client, "email", tags="review")) == ["Code Reviewer"]
    assert search(client, "email", difficulty="advanced")["total"] == 0
    assert titles(search(client, "outline", difficulty="advanced")) == ["SEO Blog Outline"]
    assert search(client, "email", has_variables=True)["total"] == 2
    assert titles(search(client, "resume", has_variables=False)) == ["Resume Bullet Rewriter"]


def test_typo_correction(client: TestClient) -> None:
    seed(client)
    res = search(client, "outlne")
    assert titles(res) == ["SEO Blog Outline"] and res["corrected_query"] == "outline"
    res = search(client, "reumse bulets")
    assert titles(res) == ["Resume Bullet Rewriter"]
    assert res["corrected_query"] == "resume bullets"
    assert search(client, "zzzzqq")["total"] == 0


def test_sorting(client: TestClient) -> None:
    seed(client)
    ids = {i["title"]: i["id"] for i in client.get("/api/v1/prompts").json()["items"]}
    assert (
        titles(client.get("/api/v1/prompts", params={"sort": "title"}).json())[0] == "Code Reviewer"
    )
    assert titles(client.get("/api/v1/prompts", params={"sort": "newest"}).json())[0] == (
        "Resume Bullet Rewriter"
    )
    # popular / recent via /use
    for _ in range(2):
        client.post(f"/api/v1/prompts/{ids['SEO Blog Outline']}/use")
    used = client.post(f"/api/v1/prompts/{ids['Code Reviewer']}/use").json()
    assert used["use_count"] == 1 and used["last_used_at"]
    pop = client.get("/api/v1/prompts", params={"sort": "popular"}).json()
    assert titles(pop)[:2] == ["SEO Blog Outline", "Code Reviewer"]
    rec = client.get("/api/v1/prompts", params={"sort": "recent"}).json()
    assert titles(rec)[:2] == ["Code Reviewer", "SEO Blog Outline"]
    # using a prompt must not bump updated_at or add a revision
    got = client.get(f"/api/v1/prompts/{ids['Code Reviewer']}").json()
    assert got["version"] == 1 and got["updated_at"] == used["updated_at"]
    # rating
    client.patch(f"/api/v1/prompts/{ids['Cold Email Writer']}", json={"rating": 5})
    assert titles(client.get("/api/v1/prompts", params={"sort": "rating"}).json())[0] == (
        "Cold Email Writer"
    )
    assert client.get("/api/v1/prompts", params={"sort": "bogus"}).status_code == 422


def test_date_and_model_filters(client: TestClient) -> None:
    make(client, title="A", model_hints="Claude, temp 0.3")
    make(client, title="B", model_hints="GPT-4o")
    assert titles(client.get("/api/v1/prompts", params={"model": "claude"}).json()) == ["A"]
    far = "2999-01-01T00:00:00Z"
    assert client.get("/api/v1/prompts", params={"created_after": far}).json()["total"] == 0
    assert client.get("/api/v1/prompts", params={"created_before": far}).json()["total"] == 2
    assert (
        client.get("/api/v1/prompts", params={"updated_after": "2000-01-01"}).json()["total"] == 2
    )


def test_relevance_pagination(client: TestClient) -> None:
    for i in range(7):
        make(client, title=f"Email template {i}", body="email " * (i + 1))
    seen, cursor = [], None
    while True:
        page = search(client, "email", limit=3, **({"cursor": cursor} if cursor else {}))
        seen += [i["id"] for i in page["items"]]
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert len(seen) == 7 and len(set(seen)) == 7
    # a cursor from another sort is rejected
    first = search(client, "email", limit=3)["next_cursor"]
    r = client.get("/api/v1/prompts", params={"q": "email", "sort": "title", "cursor": first})
    assert r.status_code == 422


def test_search_scales(client: TestClient) -> None:
    """Smoke check only; the real 10k benchmark is tests/test_search_perf.py."""
    seed(client)
    t0 = time.perf_counter()
    for _ in range(20):
        search(client, "email")
    assert (time.perf_counter() - t0) / 20 < 0.5
