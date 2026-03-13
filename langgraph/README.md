# LangGraph Orchestrator (Research Assistant)

This service is the orchestrator for the research assistant pipeline.

## Responsibilities

- receives query requests from Streamlit/FastAPI
- executes a tool-calling graph (`planner -> tools -> synthesize`)
- invokes tool services for retrieval/recommendation/translation
- returns grounded answers and top paper references

Core implementation is in [src/agent/graph.py](src/agent/graph.py).

## Run locally

1. `cd langgraph`
2. `pip install -r requirements.txt`
3. `uvicorn api.server:app --host 0.0.0.0 --port 8000`

## Key environment variables

- `MCP_SERVER_URL` (default: `http://localhost:9000`)

## Notes for final submission

- replace current lightweight retrieval bridge with Milvus-backed retrieval
- keep answer-generation constrained to retrieved evidence to minimize hallucinations
- include experiment scripts/metrics for IVF_PQ vs DiskANN vs HNSW in root documentation
