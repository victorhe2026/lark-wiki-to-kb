# lark-wiki-to-kb

<p align="center">
  <img src="logo.jpg" width="128" height="128" style="border-radius: 22%;" alt="LLM Wiki Logo">
</p>

<p align="center">
  <strong>把 Lark/飞书知识库一键转化为本地知识图谱。</strong><br>
  Pull a Feishu wiki space, run two-step CoT ingest through an internal LLM gateway, and get a searchable, graph-linked knowledge base — automatically.
</p>

---

## What This Is

A fork of [llm_wiki](https://github.com/nashsu/llm_wiki) extended with a **Lark/Feishu wiki ingest pipeline** (`py-llm-wiki/llm_wiki/lark.py`).

Given a Lark wiki URL or node token, it:

1. Recursively fetches every `doc`/`docx` node via `lark-cli` (shell subprocess, no Lark SDK)
2. Stages the raw markdown under `raw/lark-export/` (stable, so re-runs are incremental via sha256 cache)
3. Runs the **two-step CoT ingest** through your configured LLM — analysis → structured wiki pages with `[[wikilinks]]`
4. Builds the **knowledge graph** automatically from wikilinks — no extra step needed
5. Skips unsupported node types (sheet, bitable, mindnote) with a count summary

The result is a local Obsidian-compatible wiki with a force-directed graph you can browse in the GUI.

## What We Added to the Original

| Component | Change |
|-----------|--------|
| `py-llm-wiki/llm_wiki/lark.py` | New module — Lark fetcher, walker, exporter, ingest orchestrator |
| `py-llm-wiki/llm_wiki/cli.py` | New `ingest-lark` subcommand with auto-init bootstrap |
| `py-llm-wiki/llm_wiki/api.py` | New `POST /api/ingest-lark` endpoint |
| `py-llm-wiki/llm_wiki/web/` | Lark URL input + "From Lark" button in GUI |
| `py-llm-wiki/llm_wiki/llm.py` | Retry logic (3× with 10/20/30s backoff) for 403/timeout/5xx |
| `py-llm-wiki/tests/test_lark.py` | 6 offline unit tests (no network, no lark-cli) |

No new Python dependencies — Lark transport is pure `subprocess` + stdlib.

## Prerequisites

```bash
# 1. lark-cli (Node.js) — already authenticated
npm install -g @larksuiteoapi/lark-cli
lark-cli auth login

# 2. Python deps
cd py-llm-wiki
pip install -e '.[local-embed]'   # fastembed for local embeddings
```

## Configuration

Non-secret settings live in `<wiki>/.llm-wiki/config.json`. Set once with:

```bash
llm-wiki config ./my-wiki \
  --base-url https://litellm.tvlk.cloud \
  --model claude-sonnet-4.6 \
  --chat-provider anthropic \
  --embed-provider fastembed
```

The API key is **only** read from the environment, never written to disk:

```bash
export ANTHROPIC_AUTH_TOKEN="<your-gateway-token>"
```

> **Internal gateway users:** `litellm.tvlk.cloud` requires VPN. The key resolves from `OPENAI_API_KEY` first, then `ANTHROPIC_AUTH_TOKEN`. `chat_provider=anthropic` uses the `/v1/messages` endpoint; `embed_provider=fastembed` keeps embeddings fully local with no network call.

## Usage

### CLI

```bash
# Import a whole Lark wiki space (auto-inits the wiki if it doesn't exist)
llm-wiki ingest-lark ./flight-kb \
  "https://traveloka.sg.larksuite.com/wiki/V3BPwvKmii9Hqxk4o2Bl27xfgfg"

# Re-run is incremental — unchanged docs are skipped via sha256 cache
# To skip re-fetching from Lark (raw files already on disk):
llm-wiki ingest ./flight-kb ./flight-kb/raw/lark-export

# Browse the knowledge graph
llm-wiki gui ./flight-kb
```

### Options

```
llm-wiki ingest-lark [dir] <wiki-url|token>
  --no-embed    skip embedding generation
  --no-init     fail if wiki doesn't exist (don't auto-create)
  --template    general|research|reading|personal|business (default: general)
```

### GUI

The web GUI (`llm-wiki gui`) includes a **"From Lark"** input row — paste a wiki URL and click the button to trigger the same pipeline without the CLI.

### API

```bash
curl -X POST http://localhost:8765/api/ingest-lark \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://traveloka.sg.larksuite.com/wiki/...", "embed": true}'
```

Returns `{ exported, skipped, results: [...] }`.

## Supported Node Types

| Type | Behaviour |
|------|-----------|
| `doc`, `docx` | Fetched as markdown, ingested |
| `sheet`, `bitable`, `mindnote`, `file`, `slides` | Skipped, counted in summary |

## How the Ingest Pipeline Works

```
lark-cli wiki +node-get          → resolve URL → space_id + root node
lark-cli wiki +node-list --page-all  → depth-first walk (cycle guard, MAX 5000 nodes)
lark-cli docs +fetch --doc-format markdown  → raw markdown per doc node

→ write to raw/lark-export/<slug>.md  (provenance header: node_token + URL)

→ ingest_path (existing pipeline):
    Step 1 (Analysis LLM call)  → key concepts, connections, gaps
    Step 2 (Generation LLM call) → wiki pages, [[wikilinks]], index/log/overview
    → embeddings (fastembed, local)
    → graph auto-derived from [[wikilinks]]
```

## Project Layout

```
py-llm-wiki/
├── llm_wiki/
│   ├── lark.py        ← NEW: Lark fetcher + ingest orchestrator
│   ├── cli.py         ← ingest-lark command
│   ├── api.py         ← /api/ingest-lark endpoint
│   ├── llm.py         ← retry logic added
│   └── web/           ← From Lark button in GUI
└── tests/
    └── test_lark.py   ← offline unit tests

flight-kb/             ← example wiki (not committed — local only)
├── raw/lark-export/   ← staged markdown from Lark
├── wiki/              ← LLM-generated pages with [[wikilinks]]
└── .llm-wiki/
    └── config.json    ← base_url, model, providers (no secrets)
```

## Running Tests

```bash
cd py-llm-wiki
python -m pytest tests/test_lark.py -v   # offline, no network, no lark-cli
```

## Credits

Built on top of [llm_wiki](https://github.com/nashsu/llm_wiki) by [@nashsu](https://github.com/nashsu), which implements [Karpathy's LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).

## License

GNU General Public License v3.0 — see [LICENSE](LICENSE).
