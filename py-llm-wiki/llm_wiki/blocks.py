"""Parse the FILE/REVIEW block protocol emitted by the generation step.

The LLM is instructed to return its entire response as a sequence of:

    ---FILE: wiki/path/to/page.md---
    <complete file content with frontmatter>
    ---END FILE---

optionally followed by review blocks:

    ---REVIEW: type | Title---
    Description of what needs attention.
    OPTIONS: Create Page | Skip
    SEARCH: query one | query two
    ---END REVIEW---

This mirrors the parser in the TypeScript ``src/lib/ingest.ts``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List

FILE_RE = re.compile(
    r"---FILE:\s*(?P<path>.+?)\s*---\r?\n(?P<content>.*?)\r?\n---END FILE---",
    re.DOTALL,
)
REVIEW_RE = re.compile(
    r"---REVIEW:\s*(?P<type>[^|]+?)\s*\|\s*(?P<title>.+?)\s*---\r?\n(?P<body>.*?)(?:\r?\n---END REVIEW---|\Z)",
    re.DOTALL,
)


@dataclass
class FileBlock:
    path: str
    content: str


@dataclass
class ReviewBlock:
    type: str
    title: str
    description: str
    options: List[str] = field(default_factory=list)
    search: List[str] = field(default_factory=list)


def parse_files(text: str) -> List[FileBlock]:
    blocks: List[FileBlock] = []
    for m in FILE_RE.finditer(text):
        path = m.group("path").strip()
        content = m.group("content").strip("\n")
        if path:
            blocks.append(FileBlock(path=path, content=content))
    return blocks


def parse_reviews(text: str) -> List[ReviewBlock]:
    # Only scan the region after the last FILE block, so REVIEW examples that
    # might appear inside file bodies are not picked up.
    last_file = None
    for m in FILE_RE.finditer(text):
        last_file = m
    region = text[last_file.end():] if last_file else text

    reviews: List[ReviewBlock] = []
    for m in REVIEW_RE.finditer(region):
        body = m.group("body")
        options: List[str] = []
        search: List[str] = []
        desc_lines: List[str] = []
        for line in body.splitlines():
            stripped = line.strip()
            if stripped.upper().startswith("OPTIONS:"):
                options = [o.strip() for o in stripped[len("OPTIONS:"):].split("|") if o.strip()]
            elif stripped.upper().startswith("SEARCH:"):
                search = [s.strip() for s in stripped[len("SEARCH:"):].split("|") if s.strip()]
            else:
                desc_lines.append(line)
        reviews.append(
            ReviewBlock(
                type=m.group("type").strip(),
                title=m.group("title").strip(),
                description="\n".join(desc_lines).strip(),
                options=options,
                search=search,
            )
        )
    return reviews
