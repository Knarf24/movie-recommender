"""Builds the recommendation model from the MovieLens data in dataset/.

Run once (needs numpy):  python build_model.py
Writes web/data/model.json, which recommender.py loads in the browser.

What it computes:
  * a catalogue of every movie with at least MIN_RATINGS ratings (title, year, genres,
    average rating, a fair "quality" score, top tags, TMDB / IMDb ids for links)
  * item-to-item similarity: adjusted cosine on user-mean-centred ratings, shrunk
    towards zero when few people rated both movies, keeping the TOP_K closest
    neighbours of each movie. This is the "people who liked this also liked" signal.
"""
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).parent
DATA = ROOT / "dataset"
OUT = ROOT / "web" / "data" / "model.json"

MIN_RATINGS = 10   # movies with fewer ratings are too noisy to recommend
TOP_K = 40         # neighbours kept per movie
SHRINK = 20        # co-rating count at which a similarity keeps half its strength
PRIOR_WEIGHT = 10  # ratings needed before a movie's own average outweighs the global one


def read(name):
    with open(DATA / name, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


ARTICLES = r"The|A|An|Les|La|Le|L'|Il|Das|Der|Die|El|Det|Los|Las|Un|Une"


def fix_article(name):
    """'Matrix, The' -> 'The Matrix'."""
    m = re.match(rf"^(.*), ({ARTICLES})$", name.strip())
    if not m:
        return name.strip()
    art = m.group(2)
    return f"{art}{'' if art.endswith(chr(39)) else ' '}{m.group(1)}"


def split_title(raw):
    """'Seven (a.k.a. Se7en) (1995)' -> ('Seven', 'Se7en', 1995)."""
    raw = raw.strip()
    m = re.match(r"^(.*?)\s*\((\d{4})(?:[-–]\d{0,4})?\)\s*$", raw)
    title, year = (m.group(1), int(m.group(2))) if m else (raw, None)
    aka = None
    groups = re.findall(r"\(([^()]+)\)", title)
    if groups and title.endswith(")") and not title.startswith("("):
        title = title[:title.index(" (")] if " (" in title else title
        aka = fix_article(re.sub(r"^a\.k\.a\. ", "", groups[0]))
    return fix_article(title), aka, year


def main():
    ratings = read("ratings.csv")
    counts = Counter(r["movieId"] for r in ratings)
    keep = sorted((int(m) for m, n in counts.items() if n >= MIN_RATINGS))
    index = {m: i for i, m in enumerate(keep)}

    users = sorted({int(r["userId"]) for r in ratings})
    uindex = {u: i for i, u in enumerate(users)}

    R = np.zeros((len(users), len(keep)), dtype=np.float64)
    mask = np.zeros_like(R, dtype=bool)
    all_by_user = defaultdict(list)
    for r in ratings:
        u, m, s = int(r["userId"]), int(r["movieId"]), float(r["rating"])
        all_by_user[u].append(s)
        if m in index:
            R[uindex[u], index[m]] = s
            mask[uindex[u], index[m]] = True

    # Centre each person's ratings on their own average (some people rate everything 4+).
    user_mean = np.array([np.mean(all_by_user[u]) for u in users])
    C = np.where(mask, R - user_mean[:, None], 0.0)

    dot = C.T @ C
    sq = (C ** 2).T @ mask.astype(np.float64)        # sum of squares over co-raters, per pair
    denom = np.sqrt(sq * sq.T)
    with np.errstate(invalid="ignore", divide="ignore"):
        sim = np.where(denom > 0, dot / denom, 0.0)
    co = mask.T.astype(np.float64) @ mask.astype(np.float64)
    sim *= co / (co + SHRINK)
    np.fill_diagonal(sim, 0.0)

    # Fair quality score: a Bayesian average, so 2 five-star ratings don't beat 300 four-star ones.
    n = mask.sum(axis=0)
    mean = np.where(n > 0, R.sum(axis=0) / np.maximum(n, 1), 0)
    global_mean = R[mask].mean()
    quality = (n * mean + PRIOR_WEIGHT * global_mean) / (n + PRIOR_WEIGHT)

    movies_meta = {int(m["movieId"]): m for m in read("movies.csv")}
    links = {int(l["movieId"]): l for l in read("links.csv")}
    tag_counts = defaultdict(Counter)
    for t in read("tags.csv"):
        m = int(t["movieId"])
        tag = t["tag"].strip().lower()
        if m in index and 2 < len(tag) <= 24:
            tag_counts[m][tag] += 1

    genres = sorted({g for m in keep for g in movies_meta[m]["genres"].split("|") if g != "(no genres listed)"})
    gindex = {g: i for i, g in enumerate(genres)}

    movies = []
    for i, m in enumerate(keep):
        meta = movies_meta[m]
        title, aka, year = split_title(meta["title"])
        link = links.get(m, {})
        movies.append({
            "id": m,
            "t": title,
            "aka": aka,
            "y": year,
            "g": [gindex[g] for g in meta["genres"].split("|") if g in gindex],
            "n": int(n[i]),
            "avg": round(float(mean[i]), 2),
            "q": round(float(quality[i]), 3),
            "tags": [t for t, _ in tag_counts[m].most_common(4)],
            "tmdb": int(link["tmdbId"]) if link.get("tmdbId") else None,
            "imdb": link.get("imdbId") or None,
        })

    neighbours = []
    for i in range(len(keep)):
        row = sim[i]
        top = np.argsort(-row)[:TOP_K]
        neighbours.append([[int(j), int(round(row[j] * 1000))] for j in top if row[j] > 0.005])

    model = {
        "source": "MovieLens ml-latest-small (GroupLens Research, University of Minnesota), generated 2018-09-26",
        "ratings": len(ratings),
        "users": len(users),
        "min_ratings": MIN_RATINGS,
        "global_mean": round(float(global_mean), 3),
        "genres": genres,
        "movies": movies,
        "nb": neighbours,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(model, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    print(f"{len(movies)} movies, {sum(len(x) for x in neighbours)} neighbour links -> {OUT} "
          f"({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
