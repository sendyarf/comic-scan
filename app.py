#!/usr/bin/env python3
"""
Website pencarian panel komik (Proyek 3).
Upload screenshot -> embedding API (llama-server :8080) -> Qdrant (:6333)
-> hasil + metadata AniList dari scraper.db.
"""
import base64
import io
import json
import os
import sqlite3

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from PIL import Image

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

EMBED_URL = os.environ.get("EMBED_URL", "http://127.0.0.1:8080/v1/embeddings")
EMBED_API_KEY = os.environ.get("EMBED_API_KEY", "")
QDRANT_URL = os.environ.get("QDRANT_URL", "http://127.0.0.1:6333").rstrip("/")
QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY", "")
COLLECTION = os.environ.get("QDRANT_COLLECTION", "komik_panels")
SCRAPER_DB = os.environ.get("SCRAPER_DB", "/home/hatch/workspace/komik-scraper/scraper.db")
PORT = int(os.environ.get("PORT", "8000"))
TOP_K = 8

EMBED_HEADERS = {"Authorization": f"Bearer {EMBED_API_KEY}"} if EMBED_API_KEY else {}
QDRANT_HEADERS = {"api-key": QDRANT_API_KEY} if QDRANT_API_KEY else {}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB


def embed_image(img_bytes):
    # normalisasi ke JPEG agar konsisten
    im = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    im.thumbnail((1024, 1024))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=88)
    b64 = base64.b64encode(buf.getvalue()).decode()
    body = {"content": [{"content": [{"type": "image_url",
            "image_url": {"url": "data:image/jpeg;base64," + b64}}]}]}
    r = requests.post(EMBED_URL, json=body, headers=EMBED_HEADERS, timeout=300)
    r.raise_for_status()
    return r.json()[0]["embedding"][0]


def qdrant_search(vec, limit=TOP_K):
    r = requests.post(
        f"{QDRANT_URL}/collections/{COLLECTION}/points/query",
        json={"query": vec, "limit": limit, "with_payload": True},
        headers=QDRANT_HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()["result"]["points"]


STATUS_ID = {"FINISHED": "Tamat", "RELEASING": "Ongoing",
             "NOT_YET_RELEASED": "Segera", "CANCELLED": "Batal", "HIATUS": "Hiatus"}
JENIS = {"JP": "Manga", "KR": "Manhwa", "CN": "Manhua"}


def comic_meta(slug):
    try:
        con = sqlite3.connect(SCRAPER_DB)
        row = con.execute(
            "SELECT title, anilist_id, titles_json, cover, genres_json, score, "
            "description, anilist_chapters, status, country, volumes, "
            "start_year, staff_json, tags_json, site_url "
            "FROM comics WHERE slug=?", (slug,)).fetchone()
        con.close()
    except Exception:
        return None
    if not row:
        return None
    (title, aid, tjson, cover, gjson, score, desc, a_ch,
     st, country, vols, year, staff_json, tags_json, site_url) = row
    titles = json.loads(tjson) if tjson else {}
    judul = (titles.get("english") or titles.get("romaji") or title or "").strip()
    alt = []
    for k in ("romaji", "native"):
        v = (titles.get(k) or "").strip()
        if v and v != judul:
            alt.append(v)
    for s in (titles.get("synonyms") or []):
        s = s.strip()
        if s and s != judul and s not in alt:
            alt.append(s)
    staff = json.loads(staff_json) if staff_json else []
    story = next((s["name"] for s in staff if "Story" in (s.get("role") or "")
                  and "Art" not in (s.get("role") or "")), None)
    art = next((s["name"] for s in staff if "Art" in (s.get("role") or "")), None)
    if not story and staff:  # fallback: Story & Art digabung
        both = next((s["name"] for s in staff if "Story & Art" in (s.get("role") or "")), None)
        story, art = both, both
    return {
        "judul_komikindo": (title or "").strip(),
        "anilist_id": aid,
        "anilist_url": site_url or (f"https://anilist.co/manga/{aid}" if aid else None),
        "judul": judul,
        "judul_alternatif": alt[:6],
        "cover": cover,
        "genres": json.loads(gjson) if gjson else [],
        "tags": json.loads(tags_json) if tags_json else [],
        "skor_anilist": score,
        "total_chapter_anilist": a_ch,
        "total_volume": vols,
        "tahun": year,
        "status": STATUS_ID.get(st, st),
        "jenis": JENIS.get(country, "Komik"),
        "story": story,
        "art": art,
        "sinopsis": (desc or "").strip(),
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/stats")
def stats():
    try:
        n_points = requests.get(
            f"{QDRANT_URL}/collections/{COLLECTION}", headers=QDRANT_HEADERS,
            timeout=10,
        ).json()["result"]["points_count"]
    except Exception:
        n_points = 0
    try:
        con = sqlite3.connect(SCRAPER_DB)
        n_comics = con.execute("SELECT COUNT(*) FROM comics").fetchone()[0]
        con.close()
    except Exception:
        n_comics = 0
    return jsonify({"panels": n_points, "comics": n_comics})


@app.route("/api/comics")
def comics():
    """Daftar komik di database (untuk section populer)."""
    try:
        con = sqlite3.connect(SCRAPER_DB)
        rows = con.execute(
            "SELECT slug, cover, genres_json, score FROM comics "
            "WHERE cover IS NOT NULL ORDER BY score DESC LIMIT 12").fetchall()
        con.close()
    except Exception:
        return jsonify({"comics": []})
    out = []
    for slug, cover, gjson, score in rows:
        meta = comic_meta(slug) or {}
        out.append({"slug": slug, "cover": cover,
                    "judul": meta.get("judul", slug),
                    "genres": (json.loads(gjson) if gjson else [])[:2],
                    "skor_anilist": score})
    return jsonify({"comics": out})


@app.route("/api/search", methods=["POST"])
def search():
    f = request.files.get("image")
    if not f:
        return jsonify({"error": "no image uploaded"}), 400
    try:
        vec = embed_image(f.read())
    except Exception as e:
        return jsonify({"error": f"embedding failed: {e}"}), 502
    try:
        points = qdrant_search(vec, limit=40)
    except Exception as e:
        return jsonify({"error": f"database query failed: {e}"}), 502

    # Grup per komik -> satu kartu per komik berisi daftar chapter yang cocok
    by_comic = {}
    for p in points:
        pl = p.get("payload", {})
        slug = pl.get("slug", "")
        if not slug:
            continue
        ch = pl.get("chapter", "?")
        entry = by_comic.setdefault(slug, {})
        if ch not in entry or p["score"] > entry[ch]:
            entry[ch] = p["score"]
    ranked = []
    for slug, chapters in by_comic.items():
        chs = sorted(chapters.items(), key=lambda kv: kv[1], reverse=True)
        ranked.append((chs[0][1], slug, chs))
    ranked.sort(key=lambda t: t[0], reverse=True)

    results = []
    for best, slug, chs in ranked[:5]:
        meta = comic_meta(slug) or {}
        results.append({
            "score": round(best, 4),
            "kecocokan": round(best * 100, 1),
            "slug": slug,
            "chapters": [
                {"chapter": c, "kecocokan": round(s * 100, 1)}
                for c, s in chs[:8]
            ],
            **meta,
        })
    return jsonify({"results": results})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, threaded=True)
