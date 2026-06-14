# lark-wiki-to-kb

把 Lark/飞书知识库一键转化为本地知识图谱。

Given a Lark wiki URL, it crawls the whole space, runs every document through a two-step LLM ingest, and produces a searchable, graph-linked local knowledge base — with incremental re-runs so only changed docs are re-processed.

Built on top of [nashsu/llm_wiki](https://github.com/nashsu/llm_wiki). The core ingest and graph engine is theirs; we added the Lark pipeline and made the LLM layer resilient enough for long batch runs.

---

## Motivation

Flight operations has 300+ SOPs and guidelines scattered across a Lark wiki. Finding the right procedure during a live case meant either knowing where to look or asking a colleague. This tool pulls the whole wiki, extracts entities/concepts/cross-references with an LLM, and turns the flat doc list into a navigable knowledge graph you can search and ask questions against.

---

## What We Added

### 1. Lark ingest pipeline — `lark.py` (new file)

Zero new Python dependencies. Shells out to `lark-cli` (already installed and authenticated):

```
resolve_root(url)          → space_id + root node via lark-cli wiki +node-get
walk_space(space_id)       → depth-first recursive walk, cycle guard, cap 5000 nodes
fetch_markdown(node)       → lark-cli docs +fetch --doc-format markdown
export_wiki(url, dest)     → slugified .md files with provenance header
ingest_lark_wiki(...)      → export → existing ingest_path pipeline → summary
```

Non-doc types (sheet, bitable, mindnote, slides) are skipped and counted.

### 2. `ingest-lark` CLI command

```bash
llm-wiki ingest-lark ./flight-kb "https://<org>.larksuite.com/wiki/<token>"
```

Auto-inits the wiki project if it doesn't exist ("初始阶段" bootstrap). Prints per-doc ✓/⤳/✗ with exported/skipped/failed counts.

### 3. `/api/ingest-lark` + GUI button

`POST /api/ingest-lark { url, embed }` added to the FastAPI backend. A "From Lark" input row added to the web GUI header — same pipeline, no CLI needed.

### 4. Retry logic in `llm.py`

The Anthropic provider now retries up to 3× on transient failures (403, 429, 5xx, timeouts, connection drops) with 10s → 20s → 30s backoff. Necessary for batch runs of 300+ docs over a VPN-gated internal gateway where brief blips are common.

### 5. Offline unit tests — `tests/test_lark.py`

6 tests covering traversal, cycle guard, type filtering, slug deduplication, export, and full orchestration — all with monkeypatched `lark._run_lark`, no network or `lark-cli` needed.

---

## How It Works

```
lark-cli wiki +node-get          resolve URL → space_id + root node
lark-cli wiki +node-list         depth-first walk of all child nodes
lark-cli docs +fetch --doc-format markdown   export each doc/docx node

raw/lark-export/<slug>.md        stable staging dir (sha256 cache key for re-runs)

ingest_path (upstream pipeline):
  Step 1  LLM analyzes source → key concepts, entities, cross-references
  Step 2  LLM generates wiki pages → [[wikilinks]], index/log/overview updates
  fastembed (local, no API key)  → embeddings for vector search
  [[wikilinks]] → knowledge graph (auto-derived, no extra build step)
```

---

## Setup

```bash
# Prerequisites
npm install -g @larksuiteoapi/lark-cli
lark-cli auth login

cd py-llm-wiki
pip install -e '.[local-embed]'   # fastembed for local embeddings
```

## Configure

```bash
llm-wiki init ./my-wiki
llm-wiki config ./my-wiki \
  --base-url https://<your-llm-gateway> \
  --model claude-sonnet-4.6 \
  --chat-provider anthropic \
  --embed-provider fastembed
```

API key is read from environment only — never written to disk:

```bash
export ANTHROPIC_AUTH_TOKEN="<your-key>"   # or OPENAI_API_KEY
```

## Run

```bash
# Full ingest (auto-inits wiki, crawls Lark, runs LLM pipeline)
llm-wiki ingest-lark ./my-wiki "https://<org>.larksuite.com/wiki/<token>"

# Re-run incrementally (only changed/new docs, raw files already on disk)
llm-wiki ingest ./my-wiki ./my-wiki/raw/lark-export

# Open the graph + search GUI
llm-wiki gui ./my-wiki

# Query
llm-wiki query ./my-wiki "What is the escalation procedure for flight issuance failures?"
```

## Supported Node Types

| Type | Behaviour |
|------|-----------|
| `doc`, `docx` | Fetched and ingested |
| `sheet`, `bitable`, `mindnote`, `file`, `slides` | Skipped, counted in summary |

## Tests

```bash
cd py-llm-wiki
python -m pytest tests/test_lark.py -v   # offline, no network, no lark-cli
python -m pytest                          # full suite
```

## Project Layout

```
py-llm-wiki/
├── llm_wiki/
│   ├── lark.py        ← Lark fetcher + ingest orchestrator (new)
│   ├── cli.py         ← ingest-lark command (added)
│   ├── api.py         ← /api/ingest-lark endpoint (added)
│   ├── llm.py         ← retry logic (modified)
│   └── web/           ← "From Lark" button in GUI (modified)
└── tests/
    └── test_lark.py   ← 6 offline unit tests (new)
```

## Credits

- LLM Wiki pattern: [Andrej Karpathy](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
- Desktop + Python implementation: [nashsu/llm_wiki](https://github.com/nashsu/llm_wiki)

## License

GNU General Public License v3.0 — see [LICENSE](LICENSE).
