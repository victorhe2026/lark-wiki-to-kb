"""Scenario templates: default ``schema.md`` and ``purpose.md`` per use case.

Ported and condensed from the TypeScript ``src/lib/templates.ts``. Each
template defines the wiki's page types, naming/frontmatter conventions, and a
purpose scaffold the user fills in. ``schema`` is the structure rules the LLM
follows; ``purpose`` is the directional intent it reads for context.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

BASE_SCHEMA_TYPES = """| entity | wiki/entities/ | Named things (people, tools, organizations, datasets) |
| concept | wiki/concepts/ | Ideas, techniques, phenomena, frameworks |
| source | wiki/sources/ | Papers, articles, talks, books, blog posts |
| query | wiki/queries/ | Open questions under active investigation |
| comparison | wiki/comparisons/ | Side-by-side analysis of related entities |
| synthesis | wiki/synthesis/ | Cross-cutting summaries and conclusions |
| overview | wiki/ | High-level project summary (one per project) |"""

BASE_NAMING = """- Files: `kebab-case.md`
- Entities: match official name where possible (e.g., `openai.md`, `gpt-4.md`)
- Concepts: descriptive noun phrases (e.g., `chain-of-thought.md`)
- Sources: `author-year-slug.md` (e.g., `wei-2022-cot.md`)
- Queries: question as slug (e.g., `does-scale-improve-reasoning.md`)"""

BASE_FRONTMATTER = """All pages must include YAML frontmatter:

```yaml
---
type: entity | concept | source | query | comparison | synthesis | overview
title: Human-readable title
tags: []
related: []
created: YYYY-MM-DD
updated: YYYY-MM-DD
---
```

Source pages also include `authors: []`, `year: YYYY`, `url: ""`, `venue: ""`."""

BASE_INDEX_FORMAT = """`wiki/index.md` lists all pages grouped by type. Each entry:
```
- [[page-slug]] — one-line description
```"""

BASE_LOG_FORMAT = """`wiki/log.md` records activity in reverse chronological order:
```
## [YYYY-MM-DD] ingest | Title
- Action taken / finding noted
```"""

BASE_CROSSREF = """- Use `[[page-slug]]` syntax in page bodies to link between wiki pages
- Every entity and concept should appear in `wiki/index.md`
- Queries link to the sources and concepts they draw on
- Synthesis pages cite all contributing sources via `related:`"""

BASE_CONTRADICTION = """When sources contradict each other:
1. Note the contradiction in the relevant concept or entity page
2. Create or update a query page to track the open question
3. Link both sources from the query page
4. Resolve in a synthesis page once sufficient evidence exists"""


def _schema(title: str, extra_types: str = "", extra_sections: str = "") -> str:
    return f"""# Wiki Schema — {title}

## Page Types

| Type | Directory | Purpose |
|------|-----------|---------|
{BASE_SCHEMA_TYPES}{extra_types}

## Naming Conventions

{BASE_NAMING}

## Frontmatter

{BASE_FRONTMATTER}

## Index Format

{BASE_INDEX_FORMAT}

## Log Format

{BASE_LOG_FORMAT}

## Cross-referencing Rules

{BASE_CROSSREF}

## Contradiction Handling

{BASE_CONTRADICTION}
{extra_sections}"""


@dataclass
class WikiTemplate:
    id: str
    name: str
    description: str
    schema: str
    purpose: str
    extra_dirs: List[str] = field(default_factory=list)


GENERAL = WikiTemplate(
    id="general",
    name="General",
    description="A general-purpose knowledge base for any accumulating topic.",
    extra_dirs=[],
    schema=_schema("General Knowledge Base"),
    purpose="""# Project Purpose

## Goal

<!-- What is this wiki for? What knowledge are you accumulating and why? -->

>

## Key Questions

<!-- The questions you want this knowledge base to help you answer. -->

1.
2.
3.

## Scope

**In scope:**
-

**Out of scope:**
-

## Current Thinking

> Update this as your understanding evolves.
""",
)

RESEARCH = WikiTemplate(
    id="research",
    name="Research",
    description="Deep-dive research with hypothesis tracking and methodology notes.",
    extra_dirs=["wiki/methodology", "wiki/findings", "wiki/thesis"],
    schema=_schema(
        "Research Deep-Dive",
        extra_types="""
| thesis | wiki/thesis/ | Working hypothesis and its evolution over time |
| methodology | wiki/methodology/ | Research methods, protocols, and study designs |
| finding | wiki/findings/ | Individual empirical results or observations |""",
        extra_sections="""
## Research-Specific Conventions

- Keep thesis pages updated as evidence accumulates — they are living documents
- Every finding should assess replication status when known
- Distinguish between direct evidence and inference in finding pages
""",
    ),
    purpose="""# Project Purpose — Research Deep-Dive

## Research Question

<!-- State the central question. Be specific and falsifiable. -->

>

## Hypothesis / Working Thesis

<!-- Your current best guess. Update it as evidence accumulates. -->

>

## Sub-questions

1.
2.
3.

## Scope

**In scope:**
-

**Out of scope:**
-

## Success Criteria

<!-- How will you know when you have a satisfying answer? -->

-

## Current Status

> Not started.
""",
)

READING = WikiTemplate(
    id="reading",
    name="Reading",
    description="Track a book's characters, themes, plot threads, and chapter notes.",
    extra_dirs=["wiki/characters", "wiki/themes", "wiki/plot-threads", "wiki/chapters"],
    schema=_schema(
        "Reading a Book",
        extra_types="""
| character | wiki/characters/ | People and figures in the book |
| theme | wiki/themes/ | Recurring ideas, motifs, and symbolic threads |
| plot-thread | wiki/plot-threads/ | Storylines or narrative arcs being tracked |
| chapter | wiki/chapters/ | Per-chapter notes and summaries |""",
        extra_sections="""
## Reading-Specific Conventions

- Chapter pages capture fresh reactions written during or after reading
- Distinguish plot summary from personal interpretation
- Theme pages track *development* across the book, not just existence
- Flag unresolved plot threads with status `open` until resolved
""",
    ),
    purpose="""# Project Purpose — Reading

## Book

<!-- Title, author, edition. -->

>

## Why I'm Reading This

>

## What I Want to Track

<!-- Characters? Themes? Arguments? Historical context? -->

-

## Current Status

> Not started.
""",
)

PERSONAL = WikiTemplate(
    id="personal",
    name="Personal",
    description="Track goals, health, psychology, and self-improvement over time.",
    extra_dirs=["wiki/goals", "wiki/journal", "wiki/habits"],
    schema=_schema(
        "Personal Knowledge Base",
        extra_types="""
| goal | wiki/goals/ | Objectives and their progress over time |
| journal | wiki/journal/ | Dated reflections and entries |
| habit | wiki/habits/ | Routines being built or tracked |""",
        extra_sections="""
## Personal Conventions

- Journal entries are dated and append-only
- Goal pages track progress and revisions, not just the target
- Be honest in self-assessment; the wiki is for you
""",
    ),
    purpose="""# Project Purpose — Personal

## What I'm Working On

<!-- The aspects of yourself / life you're tracking. -->

>

## Goals

1.
2.

## Areas of Focus

-

## Current Status

> Just getting started.
""",
)

BUSINESS = WikiTemplate(
    id="business",
    name="Business",
    description="An internal wiki fed by docs, threads, meetings, and calls.",
    extra_dirs=["wiki/projects", "wiki/people", "wiki/decisions"],
    schema=_schema(
        "Business / Team Knowledge Base",
        extra_types="""
| project | wiki/projects/ | Initiatives, their status and stakeholders |
| person | wiki/people/ | Team members, customers, partners |
| decision | wiki/decisions/ | Decisions made, with rationale and date |""",
        extra_sections="""
## Business Conventions

- Decision pages record the *why* and the date, not just the outcome
- Project pages link to the decisions and people involved
- Keep customer/partner data on a need-to-know basis
""",
    ),
    purpose="""# Project Purpose — Business / Team

## What This Wiki Covers

>

## Key Questions

1.
2.

## Stakeholders

-

## Current Status

> Just getting started.
""",
)

TEMPLATES: Dict[str, WikiTemplate] = {
    t.id: t for t in (GENERAL, RESEARCH, READING, PERSONAL, BUSINESS)
}


def get_template(template_id: str) -> WikiTemplate:
    if template_id not in TEMPLATES:
        valid = ", ".join(TEMPLATES)
        raise ValueError(f"Unknown template '{template_id}'. Choose one of: {valid}")
    return TEMPLATES[template_id]
