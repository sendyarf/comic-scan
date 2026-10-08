# ComicScan — Search Comic by Screenshot

Upload a comic panel screenshot, find the title, chapter, and full details.
Built with AI image embeddings + vector search.

![ComicScan](static/hero.png)

## How it works

```
User uploads screenshot
        │  POST /api/search
        ▼
┌──────────────┐   embed (768-dim)   ┌──────────────────┐
│   ComicScan  │ ──────────────────▶ │  Embedding API   │
│  (Flask)     │                     │ (llama.cpp server)│
└──────────────┘                     └──────────────────┘
        │  vector query (top-K)
        ▼
┌──────────────┐   metadata lookup   ┌──────────────────┐
│    Qdrant    │ ──────────────────▶ │  scraper.db      │
│ (vector DB)  │    (AniList data)   │  (SQLite)        │
└──────────────┘                     └──────────────────┘
```

- **Embedding API** — separate service (`llama-server` + EmbeddingGemma 2),
  text & image → 768-dim vectors. Reusable by other websites.
- **Scraper bot** (separate repo/folder) — crawls comic sites, embeds every
  page, upserts to Qdrant with `{title, chapter, page}` payload, deletes the
  original images. Only embeddings are stored.
- **AniList enrichment** — matches titles to AniList GraphQL for covers,
  genres, synopsis, scores, staff.

## Quickstart

```bash
pip install flask pillow python-dotenv requests

cp .env.example .env
# edit .env: EMBED_URL, EMBED_API_KEY, QDRANT_URL, QDRANT_API_KEY, ...

python app.py
# open http://localhost:8000
```

## Configuration (`.env`)

| Variable            | Description                                      |
|---------------------|--------------------------------------------------|
| `EMBED_URL`         | Embedding API endpoint                           |
| `EMBED_API_KEY`     | Bearer token for the embedding API (optional)    |
| `QDRANT_URL`        | Qdrant REST base URL                             |
| `QDRANT_API_KEY`    | Qdrant API key, sent as `api-key` header (optional) |
| `QDRANT_COLLECTION` | Collection name (default `komik_panels`)         |
| `SCRAPER_DB`        | Path to scraper SQLite DB (AniList metadata)     |
| `PORT`              | Website port (default `8000`)                    |

`.env` is gitignored — never commit secrets. See `.env.example`.

## API

- `GET /` — upload page (click, drag & drop, or `Ctrl+V` paste)
- `POST /api/search` — multipart `image` → JSON `{results: [...]}`
  (one card per comic: title, alt titles, genres, tags, AniList score,
  status, type, year, volumes, story/art, synopsis, ranked chapter list)
- `GET /api/comics` — comics in the database (covers for the gallery)
- `GET /api/stats` — `{panels, comics}` counts

## Project structure

```
app.py               # Flask app
templates/index.html # full landing page (no build step, no emoji — SVG icons)
static/hero.png      # hero illustration
.env.example         # config template
```

## Notes

- One search takes ~20s on CPU (embedding time). The UI shows a timer.
- Uploaded images are never stored — used once for the query, then discarded.
- If the top similarity is below 70%, the panel is probably not indexed yet.
