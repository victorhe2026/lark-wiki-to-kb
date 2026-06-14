# LLM Wiki (Python)

A minimal Python implementation of the **LLM Wiki** pattern — an LLM-maintained,
self-building personal knowledge base. Instead of re-deriving knowledge on every
query (RAG), the LLM reads your sources once, integrates them into an interlinked
markdown wiki, and keeps it current.

This is a CLI + optional desktop GUI port of the [LLM Wiki desktop app](../README.md),
based on [Karpathy's methodology](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).

## What it does

- **Ingest** — two-step chain-of-thought: the LLM *analyzes* a source, then
  *generates* wiki pages (entities, concepts, source summary), updates
  `index.md` / `overview.md` / `log.md`, and flags review items. Incremental
  (sha256) so unchanged sources are skipped.
- **Search** — hybrid keyword + vector (embeddings) retrieval fused with RRF.
  Degrades to keyword-only with no API key.
- **Query** — retrieve relevant pages, answer with `[[wikilink]]` citations,
  optionally file the answer back as a new wiki page.
- **Lint** — health-check the wiki for contradictions, orphans, missing pages.
- **GUI** — a desktop window with an interactive knowledge graph, a
  search/ask panel, and a drag-in ingest box.

Output is plain markdown with YAML frontmatter and `[[wikilinks]]` — **Obsidian-compatible**.

## Install

```bash
cd py-llm-wiki
python3 -m venv .venv && source .venv/bin/activate
pip install -e .                       # core (CLI)
pip install -e '.[gui]'                # + desktop GUI (FastAPI, uvicorn, pywebview)
pip install -e '.[local-embed]'        # + on-device embeddings (fastembed)
```

Requires Python 3.9+.

## Configure the LLM

The API key is read **only** from the environment (never written to disk):

```bash
export OPENAI_API_KEY=sk-...
export OPENAI_BASE_URL=https://api.openai.com/v1   # optional: any compatible endpoint
export LLM_MODEL=gpt-4o-mini                        # optional
export EMBED_MODEL=text-embedding-3-small           # optional
```

Non-secret settings persist in `<wiki>/.llm-wiki/config.json`, so you set them
**once** instead of exporting every shell. View or change them with:

```bash
llm-wiki config my-wiki                                 # show current config
llm-wiki config my-wiki --base-url https://litellm.tvlk.cloud \
                        --model claude-sonnet-4.6 \
                        --chat-provider anthropic \
                        --embed-provider fastembed       # persist these
```

The **API key is the only thing read from the environment** (never written to
disk). It resolves from `OPENAI_API_KEY`, falling back to `ANTHROPIC_AUTH_TOKEN`
— so if your shell already exports `ANTHROPIC_AUTH_TOKEN` (e.g. for Claude
Code), you don't need to export anything at all. `llm-wiki config` prints
whether a key was found.

### Embeddings (vector search)

The embedding model is configured separately from the chat model, because some
chat endpoints don't serve embeddings (e.g. Claude has no embedding API).

- **Local, on-device (recommended)** — set `embed_provider` to `fastembed`. No
  API key, no network; a small ONNX model is downloaded once and cached.
  ```bash
  export EMBED_PROVIDER=fastembed
  export EMBED_MODEL=BAAI/bge-small-en-v1.5   # optional; this is the default
  ```
- **OpenAI-compatible endpoint** — `embed_provider=openai` uses the same
  `OPENAI_BASE_URL` + key as chat, with `EMBED_MODEL` (e.g.
  `text-embedding-3-small`).

If no embedder is available, search degrades to keyword-only (still useful at
small scale).

### Using a Claude / LiteLLM gateway

Many Claude gateways expose only the **Anthropic Messages API** (`/v1/messages`),
not the OpenAI route. Set `chat_provider=anthropic` (the chat call then uses
`/v1/messages`, sending both `Authorization: Bearer` and `x-api-key`), and use
local embeddings since Claude has no embedding API:
```bash
export OPENAI_API_KEY="$ANTHROPIC_AUTH_TOKEN"      # reuse your existing token
export OPENAI_BASE_URL="https://your-litellm-host" # gateway root (a trailing /v1 is OK; it's stripped)
export LLM_PROVIDER=anthropic                       # use /v1/messages, not /chat/completions
export LLM_MODEL="claude-sonnet-4.6"               # a model your gateway serves
export EMBED_PROVIDER=fastembed                     # Claude has no embeddings → go local
```
For an OpenAI-compatible gateway instead, omit `LLM_PROVIDER` (defaults to
`openai`) and point `OPENAI_BASE_URL` at the `/v1` route.

## Usage

```bash
llm-wiki init my-wiki --template research   # general|research|reading|personal|business
llm-wiki ingest my-wiki ./notes/            # a file or a folder (.txt/.md)
llm-wiki search my-wiki "chain of thought"
llm-wiki query  my-wiki "How does X relate to Y?" --save
llm-wiki lint   my-wiki
llm-wiki reindex my-wiki                    # rebuild embeddings
llm-wiki log    my-wiki -n 10
llm-wiki gui    my-wiki                      # open the desktop GUI
```

`dir` defaults to the current directory if omitted.

## Project layout on disk

```
my-wiki/
├── purpose.md   schema.md
├── raw/sources/                 # immutable copies of ingested sources
├── wiki/
│   ├── index.md  log.md  overview.md
│   └── entities/ concepts/ sources/ queries/ comparisons/ synthesis/
└── .llm-wiki/                   # config.json, ingest-cache.json, embeddings.json, reviews.md
```

## Tests (offline, no key needed)

```bash
python -m pytest                          # if pytest installed
python tests/test_offline.py              # pure-logic unit tests (no model)
python tests/test_pipeline_integration.py # full ingest→query→lint pipeline with a
                                          # stub chat LLM + real fastembed embedder
                                          # (downloads the embedding model once)
```

## Not in this MVP

PDF/DOCX parsing (extend `loaders.py`), web/deep-research, image/vision,
community detection. The TypeScript desktop app in the parent repo has these.
