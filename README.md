# 🛡️ VaultIQ — NextGen AI Financial Intelligence

A reference demo of an **agentic, MongoDB-Atlas-native FSI fraud-detection
suite**. Three specialist agents collaborate over a single MongoDB cluster
that simultaneously serves as operational store, vector store, time-series
store, geospatial store and graph store (PolyStorage).

> Built for the *LangChain Interrupt* talk — every box on the slide maps to
> exactly one module under `src/vaultiq/`.

---

## Architecture

```
┌──────────────┐   ┌────────────────┐   ┌─────────────────┐   ┌──────────────────┐
│   NiceGUI    │──▶│ Fraud Sentinel │──▶│ Customer Trust  │──▶│ Case Resolution  │
│  live UI     │   │   (scoring)    │   │     (KYC)       │   │  (CRM / MCP)     │
└──────────────┘   └────────────────┘   └─────────────────┘   └──────────────────┘
        │                  │                    │                       │
        ▼                  ▼                    ▼                       ▼
 ┌────────────────────────────────────────────────────────────────────────────┐
 │                       MongoDB Atlas — PolyStorage                          │
 │  customers · accounts · cards · devices · merchants · relationships(graph) │
 │  transactions(TS)  ·  *_geo(2dsphere)  ·  fraud_kb / case_notes(vector)    │
 │  cases · case_events · lg_checkpoints · llm_semantic_cache · sem_memory    │
 └────────────────────────────────────────────────────────────────────────────┘
```

* **LangGraph** orchestrates the 3-agent flow with conditional routing.
* **`MongoDBSaver`** persists every checkpoint so paused runs can resume.
* **`MongoDBAtlasSemanticCache`** dedupes LLM calls across the whole app.
* **`MongoDBAtlasVectorSearch`** powers the fraud KB, case notes and the
  long-term semantic memory each agent reads/writes.
* **`MongoDBAtlasHybridSearchRetriever`** blends BM25 + vector for KB lookup.
* **MongoDB MCP server** is bridged into the Case agent through
  `langchain-mcp-adapters` for ad-hoc read-only queries.
* **Voyage `voyage-finance-2`** is the primary embedding model (Azure OpenAI
  `text-embedding-3-large` is the auto-fallback).
* **LangSmith** traces every node + tool call when `LANGCHAIN_TRACING_V2=true`.

---

## Repo layout

```
.
├── app.py                     # NiceGUI entry point  (python app.py)
├── config/vaultiq.properties  # service map (LLM, embeddings, collections, MCP, agents…)
├── data/
│   ├── fraud_kb_corpus.py     # curated FSI policy / playbook corpus
│   └── seed_data.py           # generates 500–1000 customers + 14–30d of TS history
├── scripts/
│   ├── build_indexes.py       # idempotently creates BTree / 2dsphere / Vector / FTS / TS
│   ├── seed.py                # one-shot data seeder
│   ├── run_one.py             # CLI: inject one scenario through the agents
│   └── run_app.py             # convenience launcher for Streamlit
├── src/vaultiq/
│   ├── settings.py            # .properties + ${ENV:default} loader
│   ├── db/                    # Mongo client, logical→physical collection map, indices
│   ├── llm/                   # chat LLM, embeddings, semantic cache
│   ├── memory/                # chat history, MongoDB checkpointer, semantic memory
│   ├── retrievers/            # vector / FTS / hybrid retrievers (langchain-mongodb)
│   ├── tools/                 # fraud / kyc / case / geo / graph / TS / MCP tools
│   ├── scenarios/             # 7 injectable fraud scenarios
│   ├── agents/                # 3 ReAct agents + LangGraph wiring + Deep Agents alt
│   └── ui/                    # NiceGUI dashboard + framework-agnostic stream runner
└── tests/test_imports.py      # static smoke test
```

---

## Setup

Requires Python ≥ 3.11, an MongoDB Atlas cluster with **Atlas Search** and
**Atlas Vector Search** enabled, plus API keys for Azure OpenAI, Voyage AI and
(optionally) LangSmith.

Tested on Ubuntu 22.04 / 24.04 with the system `python3.12`.

```bash
sudo apt update && sudo apt install -y python3.12-venv git

git clone https://github.com/sourav11b/langchain_interrupt_demo.git
cd langchain_interrupt_demo

python3 -m venv demo
source demo/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

cp .env.example .env          # then fill in the keys with your editor of choice
```

All wiring (collection names, index names, thresholds, agent params) lives
in `config/vaultiq.properties`; only secrets/endpoints belong in `.env`.

---

## Run

From the repo root, with the `demo` virtualenv activated:

```bash
# 1. Create every index (BTree, 2dsphere, time-series, vector, FTS)
python -m scripts.build_indexes

# 2. Seed mock data + embed the fraud KB
python -m scripts.seed

# 3a. Smoke-test one scenario from the CLI
python -m scripts.run_one --scenario ato_sim_swap

# 3b. Or launch the live NiceGUI dashboard. Default port is 8505 (override
#     with VAULTIQ_PORT). On EC2, open the port in your security group.
python app.py
# or, on a server, run inside a detached `screen` session so it survives
# the SSH connection closing (this is what `_deploy_remote.sh` does):
screen -dmS vaultiq bash -lc \
  "VAULTIQ_PORT=8505 VAULTIQ_HOST=0.0.0.0 demo/bin/python app.py >>~/vaultiq.log 2>&1"
# then:  screen -r vaultiq   (Ctrl-A D to detach)
#        tail -f ~/vaultiq.log
#        screen -S vaultiq -X quit   (to stop)
```

The dashboard exposes a sidebar with **Live stream** (auto-generates one tx
per refresh) and a **scenario injector** for the seven built-in patterns:
`normal`, `low_risk`, `geo_velocity`, `ato_sim_swap`, `card_testing`,
`mule_funnel`, `gambling_burst`. The centre pane shows the live tx feed +
per-run agent timeline; the right pane shows open cases, the per-case event
timeline, and the score distribution.

---

## What gets demonstrated

| Capability | Where |
|---|---|
| 3-agent A2A flow (Detect → Verify → Act) | `src/vaultiq/agents/{fraud,kyc,case}_agent.py` + `graph.py` |
| LangGraph + MongoDB checkpointing | `agents/graph.py`, `memory/checkpointer.py` |
| LangSmith observability | env-driven, no code change required |
| `MongoDBAtlasVectorSearch` | `retrievers/`, `memory/semantic_memory.py` |
| `MongoDBAtlasSemanticCache` | `llm/cache.py` |
| `MongoDBAtlasHybridSearchRetriever` | `retrievers/fraud_kb.py` |
| `MongoDBChatMessageHistory` | `memory/chat_history.py` |
| Long-term semantic memory + write-on-finish | `memory/semantic_memory.py`, `agents/graph._memory_writer_node` |
| MongoDB MCP server | `tools/mcp_tools.py`, attached to Case agent |
| Voyage finance-2 embeddings (Azure fallback) | `llm/factory.py` |
| Deep Agents (a2a) supervisor — alt entry point | `agents/deep_supervisor.py` |
| PolyStorage (struct / TS / geo / graph / vector) | `db/indices.py`, `db/collections.py` |

---

## License

Demo / educational use. Not affiliated with any production system.
