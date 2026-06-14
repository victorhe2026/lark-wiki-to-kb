"""LLM prompts for the four operations.

The analysis and generation prompts are ported from the TypeScript
``src/lib/ingest.ts`` (``buildAnalysisPrompt`` / ``buildGenerationPrompt``).
The query and lint prompts follow the same spirit as ``query`` / ``lint.ts``.
"""
from __future__ import annotations

from typing import List, Optional

GENERATION_WIKI_TYPES = [
    "entity",
    "concept",
    "source",
    "query",
    "comparison",
    "synthesis",
    "overview",
]


def _join(parts: List[str]) -> str:
    return "\n".join(p for p in parts if p)


def build_analysis_prompt(purpose: str, index: str) -> str:
    """Step 1: read the source and produce a structured analysis."""
    return _join([
        "You are an expert research analyst. Read the source document and produce a structured analysis.",
        "Do not output chain-of-thought or a thinking transcript. Reason internally and write only the concise final analysis.",
        "",
        "Your analysis should cover:",
        "",
        "## Key Entities",
        "People, organizations, products, datasets, tools. For each: name, type, role (central vs. peripheral), and whether it likely already exists in the wiki (check the index).",
        "",
        "## Key Concepts",
        "Theories, methods, techniques, phenomena. For each: name, brief definition, why it matters here, and whether it likely already exists in the wiki.",
        "",
        "## Main Arguments & Findings",
        "Core claims or results, the evidence, and how strong the evidence is.",
        "",
        "## Connections to Existing Wiki",
        "What existing pages this relates to; whether it strengthens, challenges, or extends them.",
        "",
        "## Contradictions & Tensions",
        "Anything that conflicts with existing wiki content, plus internal tensions or caveats.",
        "",
        "## Recommendations",
        "What pages to create or update, what to emphasize, and open questions worth flagging.",
        "",
        "Be thorough but concise. Focus on what's genuinely important.",
        "",
        f"## Wiki Purpose (for context)\n{purpose}" if purpose else "",
        f"## Current Wiki Index (for checking existing content)\n{index}" if index else "",
    ])


def build_generation_prompt(
    schema: str,
    purpose: str,
    index: str,
    source_filename: str,
    overview: Optional[str],
    today: str,
    source_summary_path: str,
) -> str:
    """Step 2: turn the analysis into FILE/REVIEW blocks."""
    types = " | ".join(GENERATION_WIKI_TYPES)
    return _join([
        "You are a wiki maintainer. Based on the analysis provided, generate wiki files.",
        "Do not output chain-of-thought or explanatory preamble. Output only the requested FILE/REVIEW blocks.",
        "",
        "## IMPORTANT: Source File",
        f"The original source file is: **{source_filename}**",
        f"All wiki pages generated from this source MUST include this filename in their frontmatter `sources` field.",
        "",
        "## What to generate",
        "",
        f"1. A source summary page at **{source_summary_path}** (MUST use this exact path)",
        "2. Entity pages in wiki/entities/ for key entities identified in the analysis",
        "3. Concept pages in wiki/concepts/ for key concepts identified in the analysis",
        "4. An updated wiki/index.md — add new entries to existing categories, preserve all existing entries",
        f"5. A log entry for wiki/log.md (just the new entry to append, format: ## [{today}] ingest | Title)",
        "6. An updated wiki/overview.md — a comprehensive 2-5 paragraph overview of ALL topics in the wiki, updated to reflect the newly ingested source.",
        "",
        "## Frontmatter Rules (CRITICAL — parser is strict)",
        "",
        "1. The VERY FIRST line of each file MUST be exactly `---`. Do NOT wrap the file in a ```yaml fence.",
        "2. Each frontmatter line is a `key: value` pair on its own line. Close with another `---`.",
        "3. Arrays use inline YAML form `[a, b, c]`. Wikilinks belong in the BODY only — write `related: [a, b]` with bare slugs.",
        "",
        "Required fields:",
        f"  - type     — one of: {types}",
        "  - title    — string (quote it if it contains a colon)",
        f"  - created  — {today}",
        f"  - updated  — {today}",
        "  - tags     — array of bare strings",
        "  - related  — array of bare wiki page slugs (no `wiki/`, `.md`, or `[[...]]`)",
        f'  - sources  — array of source filenames; MUST include "{source_filename}"',
        "",
        "Concrete example of a complete page:",
        "",
        "    ---",
        "    type: entity",
        "    title: Example Entity",
        f"    created: {today}",
        f"    updated: {today}",
        "    tags: [example, demo]",
        "    related: [related-slug-1]",
        f'    sources: ["{source_filename}"]',
        "    ---",
        "",
        "    # Example Entity",
        "",
        "    Body content. Use [[wikilink]] syntax in the body for cross-references.",
        "",
        "Other rules:",
        "- Use [[wikilink]] syntax in the BODY for cross-references between pages",
        "- Use kebab-case filenames",
        "- Follow the analysis recommendations on what to emphasize",
        "",
        "## Review block types (optional, after all FILE blocks)",
        "",
        "- contradiction: conflicts with existing wiki content",
        "- duplicate: an entity/concept might already exist under a different name",
        "- missing-page: an important concept is referenced but has no dedicated page",
        "- suggestion: ideas for further research or connections worth exploring",
        "",
        "Only create reviews for things that genuinely need human input. Each review uses:",
        "  OPTIONS: Create Page | Skip",
        "For suggestion and missing-page reviews, also add a SEARCH line with 2-3 keyword-rich web queries separated by |.",
        "",
        f"## Wiki Purpose\n{purpose}" if purpose else "",
        f"## Wiki Schema\n{schema}" if schema else "",
        f"## Current Wiki Index (preserve all existing entries, add new ones)\n{index}" if index else "",
        f"## Current Overview (update this to reflect the new source)\n{overview}" if overview else "",
        "",
        "## Output Format (MUST FOLLOW EXACTLY)",
        "",
        "Your ENTIRE response consists of FILE blocks followed by optional REVIEW blocks. Nothing else.",
        "",
        "FILE block template:",
        "---FILE: wiki/path/to/page.md---",
        "(complete file content with YAML frontmatter)",
        "---END FILE---",
        "",
        "REVIEW block template:",
        "---REVIEW: type | Title---",
        "Description of what needs the user's attention.",
        "OPTIONS: Create Page | Skip",
        "---END REVIEW---",
    ])


def build_query_prompt(purpose: str, context: str) -> str:
    """Answer a question using retrieved wiki pages, with citations."""
    return _join([
        "You are a knowledgeable assistant answering questions using a personal wiki.",
        "Answer ONLY from the provided wiki pages. If the wiki does not contain the answer, say so plainly.",
        "Cite the pages you draw on using [[page-slug]] syntax inline.",
        "Be concise and accurate. Do not invent facts not present in the context.",
        "",
        f"## Wiki Purpose\n{purpose}" if purpose else "",
        "## Retrieved Wiki Pages",
        context,
    ])


def build_query_save_prompt(question: str, answer: str, today: str) -> str:
    """Turn a Q&A into a saveable wiki query page (returns one FILE block)."""
    return _join([
        "You are a wiki maintainer. Convert the question and answer below into a single wiki query page.",
        "Output ONLY one FILE block, nothing else.",
        "",
        "The page goes in wiki/queries/ with a kebab-case filename derived from the question.",
        "Frontmatter: type: query, a title, created/updated dates, tags, related (bare slugs referenced in the answer), sources [].",
        "Preserve [[wikilink]] citations from the answer in the body.",
        "",
        f"Use {today} for created and updated.",
        "",
        "FILE block template:",
        "---FILE: wiki/queries/your-slug.md---",
        "(complete file content with YAML frontmatter; body = the answer, with a # heading restating the question)",
        "---END FILE---",
        "",
        f"## Question\n{question}",
        "",
        f"## Answer\n{answer}",
    ])


def build_lint_prompt(purpose: str, index: str, pages_digest: str) -> str:
    """Health-check the wiki and report issues."""
    return _join([
        "You are a meticulous wiki health auditor. Review the wiki below and report issues.",
        "",
        "Look for:",
        "- Contradictions between pages",
        "- Stale claims that newer sources may have superseded",
        "- Orphan pages with no inbound links",
        "- Important concepts mentioned but lacking their own page",
        "- Missing cross-references that should exist",
        "- Data gaps worth filling with further research",
        "",
        "Output a concise markdown report grouped by issue category. For each issue, name the specific page(s) and a recommended action. If the wiki is healthy, say so.",
        "Do not rewrite pages; only report.",
        "",
        f"## Wiki Purpose\n{purpose}" if purpose else "",
        f"## Wiki Index\n{index}" if index else "",
        "## Page Digest (frontmatter + outbound links)",
        pages_digest,
    ])
