# Backend setup & run

The API serves a RAG fact-check pipeline over ~485,000 indexed claims:
`multilingual-e5-large` embeddings → Pinecone → Groq (Llama 3.3 70B), with a
live web-search fallback when the index has no close match.

---

## 1. Install dependencies

```bash
cd backend
pip install -r requirements.txt
```

> **Package note:** install `pinecone`, **not** `pinecone-client`. The old
> `pinecone-client` package on PyPI is now a stub that raises on import.
> `requirements.txt` already pins the correct one.

## 2. Create your `.env`

```bash
cp .env.example .env
```

Fill in:

| Variable | Required | Notes |
|---|---|---|
| `PINECONE_API_KEY` | yes | index `fact-check-claims`, namespace `claims` |
| `GROQ_API_KEY` | yes | verdict generation (Llama 3.3 70B) |
| `GOOGLE_API_KEY` | optional | enables the Google Fact Check Tools API for Tier 3; without it only the keyless DuckDuckGo fallback runs |

## 3. Verify connections

```bash
python scripts/test_api.py --health-check
```

Expect `pinecone_connected: True` and a `vector_count` around 484,848.

## 4. Run the API

```bash
python -m uvicorn main:app --reload --port 8000
```

Startup prints a summary:

```
🚀 Starting Fact-Check API...
✅ Pinecone connected (484,848 vectors)
✅ Groq LLM configured (model 'llama-3.3-70b-versatile')
✅ Web search enabled (Google FC + DuckDuckGo)
✅ API running on http://localhost:8000
```

> The embedding model (~2.3 GB) loads lazily on the **first** fact-check. That
> request can take a minute on CPU; later checks run in a few seconds.

## 5. Test it

```bash
curl http://localhost:8000/health
```

```bash
curl -X POST http://localhost:8000/api/fact-check -H "Content-Type: application/json" -d "{\"claim\": \"COVID vaccines have microchips\"}"
```

Run the full sample set (10 claims):

```bash
python scripts/test_api.py
```

## 6. Run the frontend

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>. Vite proxies `/api` to port 8000.

---

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | status, version, dependency checks, vector count |
| `POST` | `/api/fact-check` | main endpoint — `{ "claim": "..." }` |
| `GET` | `/api/stats` | dataset distributions, checks today |
| `GET` | `/api/search?q=` | live web fact-check lookup only |
| `GET` | `/api/claims` | paginated read of stored claims |

Interactive docs: <http://localhost:8000/docs>

---

## Tier routing

| Tier | Top similarity | Evidence used |
|---|---|---|
| `HIGH` | ≥ `HIGH_CONF_THRESHOLD` (0.88) | index only |
| `MEDIUM` | ≥ `MEDIUM_CONF_THRESHOLD` (0.86) | index only |
| `LOW` | below that | **live web search** |
| `VERY_LOW` | nothing found anywhere | none — result is a starting point |

Web search fires **only at Tier 3 (LOW)**, keeping the common path fast and
free of search-API quota use.

**Why these thresholds look high:** `multilingual-e5-large` compresses cosine
similarity into a narrow band — unrelated text still scores ~0.83–0.85 against a
485K-claim index, and genuine matches land ~0.88+. The conventional 0.80/0.60
cut-offs would route *every* claim to Tier 1 and web search would never run.
Re-tune in `.env` if you change the embedding model.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `503` from `/api/fact-check` | a key is missing or an ML dep isn't installed — check `/health` |
| Verdict is always `UNVERIFIED` with "could not be automatically verified" | Groq call failed; check `backend/logs/api.log`. A `429` means the free-tier quota is spent — wait for the reset or add billing |
| First check takes ~60 s | one-time embedding-model load; subsequent checks are fast |
| `Exception: pinecone-client has been renamed` | uninstall `pinecone-client`, install `pinecone` |
| No sources ever returned | set `GOOGLE_API_KEY`; DuckDuckGo alone rarely returns fact-check abstracts |
