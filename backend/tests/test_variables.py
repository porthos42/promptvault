from promptvault.services.variables import detect, merge_variables, render


def test_detect_unique_in_order() -> None:
    assert detect("Hi {{ name }}, {{role}} {{name}} {{ 1bad }} {x-y}") == ["name", "role"]


def test_merge_keeps_declared_metadata_and_drops_stale() -> None:
    declared = [
        {
            "name": "role",
            "label": "Job role",
            "type": "select",
            "default": "dev",
            "options": ["dev"],
        },
        {"name": "gone", "label": "Not in body"},
    ]
    out = merge_variables("{{name}} as {{role}}", declared)
    assert [v["name"] for v in out] == ["name", "role"]
    assert out[0]["label"] == "Name" and out[0]["type"] == "text"
    assert out[1]["label"] == "Job role" and out[1]["type"] == "select"
    assert out[1]["default"] == "dev" and out[1]["options"] == ["dev"]


def test_merge_invalid_type_falls_back_to_text() -> None:
    assert merge_variables("{{a}}", [{"name": "a", "type": "bogus"}])[0]["type"] == "text"


def test_render_values_defaults_and_missing() -> None:
    variables = merge_variables("{{a}} {{b}} {{c}}", [{"name": "b", "default": "B!"}])
    text, missing = render("{{a}} {{b}} {{c}}", variables, {"a": "A"})
    assert text == "A B! {{c}}"
    assert missing == ["c"]
    text, missing = render("{{a}} {{b}}", variables[:2], {"a": "1", "b": "2"})
    assert (text, missing) == ("1 2", [])
