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
    # Finance/investing banks (listed first: first substring match wins).
    "ticker": ["AAPL", "MSFT", "VTI", "TSLA", "JNJ"],
    "earnings": ["Q3 revenue rose 12% while margins fell; management cut guidance.",
                 "EPS beat estimates but free cash flow declined for a second quarter.",
                 "Revenue flat; the company raised its dividend and announced buybacks.",
                 "Gross margin expanded 2 points; inventory is up 30% year over year.",
                 "Missed on revenue; the new product line grew 60% from a small base."],
    "news": ["Headline: 'Rate-cut hopes send indexes to record high' (mainstream outlet).",
             "Headline: 'This stock could double' (social media post, no data cited).",
             "Press release: company announces a partnership and raises full-year outlook.",
             "Newsletter: 'The market is topping — sell everything now' (no sources given).",
             "Headline: 'Earnings season kicks off with mixed results' (mainstream outlet)."],
    "holdings": ["VTI 60%, AAPL 25%, cash 15%",
                 "Five stocks; the largest is 45% of the total",
                 "Target-date fund 80%, brokerage ETF 20%",
                 "One stock 50%, ETF 30%, crypto 20%",
                 "Index fund 70%, bonds 20%, cash 10%"],
    "research_notes": ["Thesis: subscriber base growing, but valuation looks rich; risk: competition.",
                       "Rising debt in the 10-K; a founder sold shares; new market entry planned.",
                       "Insider buying last quarter; gross margin improving for three years.",
                       "Strong brand but slowing growth; management turnover in the past year.",
                       "Revenue concentrated in one customer (35%); expanding to two regions."],
    "savings": ["401k $120,000, IRA $30,000, cash $20,000",
                "Employer pension plus $85,000 in index funds",
                "Nothing saved yet; starting from zero",
                "$250,000 spread across two accounts",
                "Roth IRA $15,000, employer plan $40,000"],
    "income": ["Salary $4,000/month plus $800/month rental",
               "Freelance income varies: $2,000-$4,000/month",
               "W-2 job $90,000/year with an uncertain bonus",
               "Expected pension $1,800/month at age 67",
               "Two incomes: $5,500/month combined"],
    "expenses": ["Housing $1,800, food $600, healthcare $400, car $350",
                 "Rent $1,500, food $500, travel $200, insurance $250",
                 "Mortgage $2,100, utilities $400, food $700",
                 "Rent-free (paid-off home), food $500, hobbies $300",
                 "Housing $1,200, debt payments $600, food $450"],
    "expense": ["Software subscriptions $600, home office $900, 3,000 miles driven",
                "Client meals $350, professional dues $250",
                "Home office $1,200, internet $840, phone $600",
                "Course fees $1,500, 2,000 miles driven, supplies $400",
                "Childcare $5,000, out-of-pocket medical $2,300"],
    "situation": ["Single employee, one W-2 job, no dependents",
                  "Married filing jointly, two kids, one mortgage",
                  "Self-employed freelancer making quarterly estimates",
                  "Retired last year with a pension and part-time income",
                  "Graduate student with a small side business"],
    "life_changes": ["Got married and started a new job",
                     "Bought a house and had a child",
                     "Started freelancing mid-year",
                     "Moved to a different state",
                     "Inherited an investment account"],
    "goals": ["retire comfortably", "buy a home", "reach financial independence",
              "fund a child's education", "grow long-term wealth"],
    "constraints": ["keep monthly effort low",
                    "no more than 15 minutes of attention per week",
                    "avoid anything needing constant monitoring",
                    "keep an emergency fund untouched first",
                    "nothing locked away past the stated horizon"],
    "comfort": ["I can tolerate a 30% drop without selling",
                "I check prices daily and get anxious",
                "I would likely sell after a 20% drop",
                "I ignore short-term swings",
                "I panic first, then reconsider in a week"],
    "portfolio_relevance": ["I hold some index funds",
                            "I hold one stock I am watching",
                            "no holdings yet",
                            "I hold mostly crypto",
                            "I hold one managed fund"],
    "companies": ["Company A P/E 18; Company B P/E 24; Company C P/E 12",
                  "AAPL P/E 28 vs MSFT P/E 32",
                  "Retailer EV/EBITDA 9 vs software firm EV/EBITDA 21",
                  "Bank P/B 1.1 vs industrial P/B 3.4",
                  "Dividend yields: 2.1%, 3.4%, 5.8%"],
    "focus_areas": ["revenue and margins", "guidance changes", "cash flow",
                    "costs and inventory", "dividend and buybacks"],
    "current_age": ["35", "45", "52", "60", "28"],
    "age_goal": ["55", "62", "65", "67", "50"],
    "amount": ["200", "500", "1000", "2500", "150"],
    "portfolio": ["10,000", "50,000", "120,000", "8,500", "300,000"],
    "value": ["10,000", "50,000", "120,000", "8,500", "300,000"],
    "fee_percent": ["0.03%", "0.20%", "0.50%", "1.00%", "1.50%"],
    "fee": ["0.03%", "0.20%", "0.50%", "1.00%", "1.50%"],
    "percent": ["0.03%", "0.25%", "0.50%", "1.00%", "1.50%"],
    "rate": ["3%", "5%", "7%", "8%", "10%"],
    "contribution": ["1,200", "6,000", "12,000", "500", "24,000"],
    "years": ["5", "10", "20", "30", "3"],
    "year": ["2026", "2025", "2024", "2026", "2025"],
    "horizon": ["about 5 years", "about 10 years", "about 20 years",
                "about 30 years", "under 3 years"],
    "timeline": ["about 5 years", "about 10 years", "about 20 years",
                 "about 30 years", "under 3 years"],
    "currency": ["USD", "EUR", "GBP", "CAD", "AUD"],
    "jurisdiction": ["US (federal)", "California, US", "United Kingdom", "Canada", "Germany"],
    "obligations": ["one W-2 job, no other income",
                    "freelance income on top of a W-2 job",
                    "rental property income",
                    "investment income only",
                    "two jobs plus a side business"],
    "concept": ["compound interest", "tax brackets", "index funds vs ETFs",
                "dollar-cost averaging", "required minimum distributions"],
    "lifestyle": ["Modest: small town, paid-off home, one trip a year",
                  "Active: gym, hobbies, frequent family visits",
                  "Frugal city renter, no car, cooks at home",
                  "Half the year abroad in a low-cost country",
                  "Beach town, boating, golf twice a month"],
    "budget": ["Rent $1,600, food $500, transport $300",
               "Mortgage $1,900, utilities $350, food $700",
               "No rent (staying with family); food $400, transport $200",
               "Rent $2,100, insurance $250, hobbies $300",
               "Mortgage paid off; food $600, travel $400"],
    "location": ["Austin, Texas", "a small town in Ohio", "Lisbon, Portugal",
                 "rural Hawaii", "Chicago suburbs"],
    "pension": ["employer 401(k)", "state teacher's pension",
                "government civil service pension", "private company pension plan",
                "military retirement"],
    "form_name": ["W-4", "1040", "W-9", "1099-NEC", "state income tax form"],
    "form_text": ["Section 1a: filing status checkboxes (single, married filing jointly, ...).",
                  "Line 1: wages; Line 2: interest income; Line 3: dividends.",
                  "Part I: taxpayer details; Part II: income; Part III: deductions.",
                  "Box 1: compensation; Box 5: contributions; Box 12: codes.",
                  "Page 1: personal details; Schedule 1: additional income and adjustments."],
    "account_type": ["401(k)", "Roth IRA", "traditional IRA", "taxable brokerage",
                     "employer pension plan"],
    "loss_reaction": ["Sell everything to avoid further losses",
                      "Hold, but check prices daily",
                      "Buy more if the thesis is unchanged",
                      "Feel anxious but stay the course",
                      "Panic first, then reconsider within a week"],
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
