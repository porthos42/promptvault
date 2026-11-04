#!/usr/bin/env python3
"""Generate five named variations for every seed prompt (one-time prefill).

For each seed/*.yaml, builds five variations from the prompt's variables:
- select variables cycle through their own options;
- text/textarea variables pick values from heuristic banks keyed on the variable
  name (tone, audience, length, ...), falling back to generic sample text.
The block is inserted as raw YAML text just before the ``body:`` line so the
rest of the file keeps its original formatting. Idempotent: files that already
declare ``variations:`` are skipped.

Run:  python tools/generate_seed_variations.py [--dry-run]
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent / "seed"

# Value banks keyed on substrings of the variable name; each bank has >= 5 entries.
BANKS: dict[str, list[str]] = {
    "tone": ["professional", "friendly", "witty", "formal", "encouraging"],
    "style": ["concise", "detailed", "step-by-step", "conversational", "academic"],
    "audience": ["a general audience", "technical experts", "complete beginners",
                 "busy executives", "students"],
    "reader": ["a general audience", "a domain expert", "a first-time user",
               "a hiring manager", "a student"],
    "length": ["short (1 paragraph)", "medium (3-5 paragraphs)", "brief (150 words)",
               "detailed (800+ words)", "bullet points only"],
    "level": ["beginner", "intermediate", "advanced", "expert", "complete beginner"],
    "complexity": ["simple", "moderate", "advanced", "comprehensive", "minimal"],
    "language_variant": ["US English", "UK English", "Canadian English",
                         "Australian English", "Indian English"],
    "language": ["English", "Spanish", "French", "German", "Japanese"],
    "format": ["markdown", "plain text", "bullet list", "table", "JSON"],
    "platform": ["LinkedIn", "X/Twitter", "Instagram", "TikTok", "Facebook"],
    "industry": ["technology", "healthcare", "finance", "retail", "education"],
    "company": ["a small startup", "a mid-size agency", "a Fortune 500 firm",
                "a local business", "a non-profit"],
    "product": ["a SaaS product", "a mobile app", "an online course",
                "a physical consumer product", "a B2B service"],
    "role": ["software engineer", "product manager", "marketing specialist",
             "data analyst", "team lead"],
    "job": ["software engineer", "data analyst", "product manager",
            "marketing manager", "customer success lead"],
    "context": ["a team meeting update", "a client presentation",
                "an internal documentation page", "a public blog post",
                "a project status report"],
    "goal": ["increase engagement", "drive sign-ups", "improve retention",
             "raise brand awareness", "reduce churn"],
    "constraint": ["under 200 words", "no jargon", "include a call to action",
                   "match a formal register", "second person, active voice"],
    "name": ["Alex Morgan", "Jordan Lee", "Sam Rivera", "Taylor Kim", "Casey Nguyen"],
    "company_name": ["Northwind Analytics", "Bluepeak Labs", "Vertex Studio",
                     "Harbor & Co.", "Brightline Media"],
    "num": ["3", "5", "7", "10", "2"],
    "count": ["3", "5", "7", "10", "2"],
    "topic": ["remote work productivity", "sustainable packaging",
              "machine learning basics", "personal budgeting", "urban gardening"],
    "subject": ["remote work productivity", "sustainable packaging",
                "machine learning basics", "personal budgeting", "urban gardening"],
    "text": ["The quick brown fox jumps over the lazy dog while the team reviews the quarterly results.",
             "Our latest release improves onboarding by 40%, but customers still report confusion about billing.",
             "In today's meeting we discussed the roadmap, staffing, and the upcoming product launch.",
             "Dear Sir or Madam, I am writing to inquire about the position advertised on your website.",
             "Machine learning models require careful validation before deployment in production systems."],
    "transcript": ["Speaker 1: We should prioritize the API migration this sprint. Speaker 2: Agreed, but the billing bug is blocking customers first.",
                   "Meeting notes: Budget approved for Q3. Marketing wants a launch date by Friday. Engineering flags a dependency on the data team.",
                   "Client call: They love the demo but want offline mode before signing. Pricing was not discussed.",
                   "Interview excerpt: The candidate described leading a five-person team through a full rewrite with zero downtime.",
                   "Support log: User cannot reset their password, reports an expired link, and asks about data export options."],
    "email": ["Hi team, attached is the draft proposal. Please review by Thursday and flag anything blocking.",
              "Dear customer, thank you for reaching out. We have escalated your ticket and will update you within 24 hours.",
              "Hello, following up on our call yesterday: as discussed, here are the revised timelines and costs.",
              "Hi Jordan, great meeting today! As promised, here is the summary and the next steps for the pilot.",
              "Dear hiring manager, I am excited to apply for the listed role and believe my background fits well."],
    "question": ["How does this work in practice?", "What are the main risks?",
                 "Why should we choose this approach?", "What does success look like?",
                 "How much does it cost?"],
    "prompt": ["Write a short story about a lighthouse keeper.",
               "Explain how neural networks learn, for a ten-year-old.",
               "Draft a polite decline to a meeting invitation.",
               "Summarize the plot of Hamlet in five bullet points.",
               "Brainstorm names for a coffee shop run by two sisters."],
    "data": ["2024-01: 1,200 users; 2024-02: 1,450 users; 2024-03: 1,390 users",
             "Product A: 45% margin; Product B: 32% margin; Product C: 51% margin",
             "Q1 revenue $1.2M, Q2 $1.5M, Q3 $1.1M, Q4 $1.8M",
             "Support tickets: Jan 320, Feb 290, Mar 410, Apr 380",
             "Churn by cohort: 2023-Q1 8%, 2023-Q2 6%, 2023-Q3 5%, 2023-Q4 4%"],
    "code": ["def add(a, b):\n    return a + b",
             "for i in range(10):\n    print(i)",
             "SELECT id, name FROM users WHERE active = 1;",
             "const items = list.filter(x => x.active).map(x => x.name);",
             "curl -X POST https://api.example.com/v1/items -d '{\"name\": \"test\"}'"],
    "url": ["https://example.com/blog/post-title", "https://example.com/products/item",
            "https://example.com/about", "https://example.com/docs/getting-started",
            "https://example.com/pricing"],
    "image": ["a minimalist line drawing of a mountain at dawn",
              "a photorealistic product shot on a white background",
              "a watercolor illustration of a city skyline",
              "an isometric 3D icon of a rocket ship",
              "a flat-design illustration of people collaborating"],
    "title": ["The Future of Remote Work", "A Beginner's Guide to Baking",
              "Ten Lessons from Our First Year", "Why Data Beats Opinion",
              "Getting Started with Automation"],
}
BANK_KEYS = list(BANKS)

# Fallback generic sample values per variation index (0-4) for unmatched variables.
FALLBACK = [
    "example value A", "example value B", "example value C",
    "example value D", "example value E",
]

# Human-friendly variation names, reused across all prompts.
NAMES = [
    "Quick start",       # mild defaults, minimal effort
    "Professional",      # formal register
    "Detailed",          # thorough / advanced
    "Beginner friendly", # simple language
    "Creative",          # expressive / unusual
]

# Per-variation index tuning applied on top of the bank picks.
TUNING = {
    0: {"length": "short (1 paragraph)", "complexity": "simple"},
    1: {"tone": "formal", "style": "concise"},
    2: {"length": "detailed (800+ words)", "complexity": "advanced"},
    3: {"level": "complete beginner", "style": "step-by-step"},
    4: {"tone": "witty", "style": "conversational"},
}


def pick_value(var_name: str, idx: int) -> str | None:
    """Best value for variable ``var_name`` at variation index ``idx``."""
    low = var_name.lower()
    for key in BANK_KEYS:
        if key in low:
            return BANKS[key][idx % len(BANKS[key])]
    return None


def variations_for(seed: dict) -> list[dict]:
    """Build the five variations for one parsed seed prompt."""
    variables = seed.get("variables") or []
    out: list[dict] = []
    for idx, name in enumerate(NAMES):
        values: dict[str, str] = {}
        for v in variables:
            vn = v.get("name", "")
            if v.get("type") == "select" and v.get("options"):
                values[vn] = str(v["options"][idx % len(v["options"])])
            else:
                picked = pick_value(vn, idx)
                if picked is None:
                    picked = FALLBACK[idx]
                if TUNING.get(idx, {}).get(vn.lower().replace(" ", "_")):
                    picked = TUNING[idx][vn.lower().replace(" ", "_")]
                values[vn] = picked
        out.append({"name": name, "values": values})
    return out


def dump_variations(variations: list[dict]) -> str:
    """Serialize variations as a YAML block ready to splice into a seed file.

    Dumps the whole structure with one yaml.dump call: dumping scalars
    individually appends a stray '...' document-end marker to each line.
    """
    block = yaml.dump(
        {"variations": variations},
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
        width=1000,
    )
    # strip the leading/trailing document-end marker that yaml.dump appends
    block = block.removeprefix("---")
    block = block.removeprefix("\n")
    return block.rstrip("\n") + "\n"


def process_file(path: Path, dry_run: bool) -> str:
    text = path.read_text(encoding="utf-8")
    if "variations:" in text:
        return "skip (already has variations)"
    seed = yaml.safe_load(text)
    if not isinstance(seed, dict):
        return "skip (not a mapping)"
    if not seed.get("variables"):
        return "skip (no variables)"
    block = dump_variations(variations_for(seed))
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    inserted = False
    for line in lines:
        if not inserted and line.startswith("body:"):
            out.append(block)
            inserted = True
        out.append(line)
    if not inserted:  # no body: line found at column 0 — bail out
        return "skip (no top-level body: line)"
    if not dry_run:
        path.write_text("".join(out), encoding="utf-8")
    return "written"


def main() -> int:
    dry = "--dry-run" in sys.argv
    counts = {"written": 0, "skip": 0}
    for path in sorted(ROOT.glob("*/*.yaml")):
        if path.name == "categories.yaml":
            continue
        result = process_file(path, dry)
        if result == "written":
            counts["written"] += 1
        else:
            counts["skip"] += 1
            print(f"  {path.name}: {result}")
    print(f"done: {counts['written']} files {'(dry-run) ' if dry else ''}updated, {counts['skip']} skipped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
