"""Movie Recommender: the Python brain of the app.

Runs in the browser with Pyodide (and in a terminal: `python recommender.py "Toy Story" "Alien"`).
Standard library only. It loads web/data/model.json, made by build_model.py from MovieLens.

Three parts, from three GeeksforGeeks projects:
  1. Recommend: item-to-item collaborative filtering ("people who liked this also liked")
     with a per-movie baseline, so it can predict how many stars you'd give a movie.
  2. Vote: a group shortlist that suits everyone, then a ranked vote (instant runoff
     or Borda count) that picks the winner and shows every round.
  3. Comments: checks and tidies comments before the page saves them.

The page calls everything through call(name, json_args) and gets JSON back.
"""
import json
import math
import re
import time
import unicodedata
from difflib import SequenceMatcher

M = None  # the loaded model


class Model:
    def __init__(self, data):
        self.genres = data["genres"]
        self.movies = data["movies"]
        self.global_mean = data["global_mean"]
        self.meta = {k: data[k] for k in ("source", "ratings", "users", "min_ratings")}
        self.by_id = {m["id"]: i for i, m in enumerate(self.movies)}
        # neighbour lists as {index: similarity 0..1}
        self.nb = [{j: s / 1000 for j, s in row} for row in data["nb"]]
        self.keys = [_norm(m["t"]) for m in self.movies]
        self.aka_keys = [_norm(m["aka"] or "") for m in self.movies]


def load(text):
    global M
    M = Model(json.loads(text))
    return {"movies": len(M.movies), "genres": M.genres, **M.meta}


def _norm(s):
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("&", " and ")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s).split())


# Most telling genre first, so "Adventure|Animation|Children" is shown as an animation.
GENRE_ORDER = ["Animation", "Documentary", "Horror", "Sci-Fi", "Western", "Musical", "Film-Noir", "Fantasy",
               "Children", "Crime", "Mystery", "Thriller", "Romance", "War", "Comedy", "Action",
               "Adventure", "Drama", "IMAX"]


def _genres(m):
    names = [M.genres[g] for g in m["g"]]
    return sorted(names, key=lambda g: GENRE_ORDER.index(g) if g in GENRE_ORDER else 99)


def _card(i, **extra):
    m = M.movies[i]
    card = {
        "id": m["id"], "title": m["t"], "aka": m["aka"], "year": m["y"],
        "genres": _genres(m), "avg": m["avg"], "count": m["n"],
        "quality": round(m["q"], 2), "tags": m["tags"], "tmdb": m["tmdb"], "imdb": m["imdb"],
    }
    card.update(extra)
    return card


def _idx(movie_id):
    i = M.by_id.get(int(movie_id))
    if i is None:
        raise ValueError(f"unknown movie {movie_id}")
    return i


def _passes(i, genre=None, year_from=None, year_to=None):
    m = M.movies[i]
    if genre and genre in M.genres and M.genres.index(genre) not in m["g"]:
        return False
    if year_from and (m["y"] or 0) < int(year_from):
        return False
    if year_to and (m["y"] or 9999) > int(year_to):
        return False
    return True


# ---------------------------------------------------------------- finding movies

def search(query, limit=12):
    """Title search that forgives case, accents, punctuation and small typos."""
    q = _norm(query or "")
    if not q:
        return []
    words = q.split()
    scored = []
    for i, (key, aka) in enumerate(zip(M.keys, M.aka_keys)):
        best = 0
        for k in (key, aka):
            if not k:
                continue
            if k == q:
                best = max(best, 100)
            elif k.startswith(q) or (k.startswith("the ") and k[4:].startswith(q)):
                best = max(best, 80)
            elif all(w in k.split() or any(t.startswith(w) for t in k.split()) for w in words):
                best = max(best, 60)
            elif q in k:
                best = max(best, 40)
        if best:
            scored.append((best, M.movies[i]["n"], i))
    if not scored and len(q) >= 4:  # nothing matched: allow a typo or two
        for i, key in enumerate(M.keys):
            r = SequenceMatcher(None, q, key[: len(q) + 3]).ratio()
            if r >= 0.75:
                scored.append((r * 30, M.movies[i]["n"], i))
    scored.sort(reverse=True)
    return [_card(i) for _, _, i in scored[:limit]]


def movie(movie_id):
    return _card(_idx(movie_id))


def browse(genre=None, sort="top", year_from=None, year_to=None, limit=24, offset=0):
    """Lists movies. sort: top (fair average), popular (most ratings), newest."""
    ids = [i for i in range(len(M.movies)) if _passes(i, genre, year_from, year_to)]
    keyf = {
        "top": lambda i: -M.movies[i]["q"],
        "popular": lambda i: -M.movies[i]["n"],
        "newest": lambda i: (-(M.movies[i]["y"] or 0), -M.movies[i]["n"]),
    }.get(sort, lambda i: -M.movies[i]["q"])
    ids.sort(key=keyf)
    return {"total": len(ids), "items": [_card(i) for i in ids[offset: offset + limit]]}


def starter(limit=24):
    """Well-known movies across many genres, to rate first."""
    picked, seen_genres = [], {}
    for i in sorted(range(len(M.movies)), key=lambda i: -M.movies[i]["n"]):
        g = M.movies[i]["g"][0] if M.movies[i]["g"] else -1
        if seen_genres.get(g, 0) >= 4:
            continue
        seen_genres[g] = seen_genres.get(g, 0) + 1
        picked.append(i)
        if len(picked) >= limit:
            break
    return [_card(i) for i in picked]


def similar(movie_id, limit=12):
    """Movies the same people rated in the same way: 'more like this'."""
    i = _idx(movie_id)
    mine = set(M.movies[i]["g"])
    rows = []
    for j, s in M.nb[i].items():
        overlap = len(mine & set(M.movies[j]["g"])) / max(1, len(mine | set(M.movies[j]["g"])))
        rows.append((s * (0.85 + 0.3 * overlap), j))
    rows.sort(reverse=True)
    return [_card(j, match=min(99, round(100 * a))) for a, j in rows[:limit]]


# ---------------------------------------------------------------- recommending

def _predict(ratings):
    """ratings {movie_id: stars}. Returns ({index: (stars, evidence, reasons)}, offset, rated set).

    Prediction = movie's fair average + your personal lean + a weighted average of how much
    you liked/disliked its neighbours compared with their averages (item-based CF with baseline).
    """
    rated = {}
    for mid, stars in (ratings or {}).items():
        i = M.by_id.get(int(mid))
        if i is not None and stars is not None:
            rated[i] = max(0.5, min(5.0, float(stars)))
    devs = {i: r - M.movies[i]["q"] for i, r in rated.items()}
    lean = sum(devs.values()) / (len(devs) + 8) if devs else 0.0  # shrunk towards 0

    acc = {}
    for i, d in devs.items():
        d -= lean
        for j, s in M.nb[i].items():
            if j in rated:
                continue
            a = acc.setdefault(j, [0.0, 0.0, []])
            a[0] += s * d
            a[1] += s
            if d > 0 and rated[i] >= 3.5:
                a[2].append((s * d, i))
    # Genre taste: which genres the movies you rated above their average share.
    taste = {}
    for i, d in devs.items():
        for g in M.movies[i]["g"]:
            taste[g] = taste.get(g, 0.0) + (d - lean)
    norm = math.sqrt(sum(v * v for v in taste.values())) or 1.0
    taste = {g: v / norm for g, v in taste.items()}

    out = {}
    for j, (num, den, why) in acc.items():
        boost = num / (den + 0.35)
        stars = max(0.5, min(5.0, M.movies[j]["q"] + lean + boost))
        gs = M.movies[j]["g"]
        fit = sum(taste.get(g, 0.0) for g in gs) / math.sqrt(len(gs)) if gs else 0.0
        # Rank by how far the evidence lifts it above its own average, how sure we are,
        # how well it fits your genres, and a little for overall quality.
        conf = den / (den + 0.6)
        rank = boost * conf + 0.35 * fit + 0.25 * (M.movies[j]["q"] - M.global_mean)
        why.sort(reverse=True)
        out[j] = (stars, den, [i for _, i in why[:2]], rank)
    return out, lean, set(rated), taste


def _genre_fit(j, taste):
    gs = M.movies[j]["g"]
    return sum(taste.get(g, 0.0) for g in gs) / math.sqrt(len(gs)) if gs else 0.0


def _guess(j, lean, taste):
    """For a movie none of your rated movies point to: (stars, rank score) from its fair
    average, your lean and your genre taste, minus a little for the uncertainty."""
    fit = _genre_fit(j, taste)
    stars = max(0.5, min(5.0, M.movies[j]["q"] + lean + 0.5 * fit - 0.2))
    return stars, 0.35 * fit + 0.25 * (M.movies[j]["q"] - M.global_mean) - 0.15


def _match_from_rank(rank):
    """Turns a rank score (about -0.5 .. 1.2) into a friendly 0..99 'match' percent."""
    return int(max(0, min(99, round(55 + 40 * rank))))


def _because(idxs):
    return [{"id": M.movies[i]["id"], "title": M.movies[i]["t"]} for i in idxs]


def recommend(ratings=None, genre=None, year_from=None, year_to=None, exclude=None, limit=20):
    """Personal picks for someone who rated some movies. Each comes with predicted stars,
    a 'match' percent, and the movies they rated that led to it."""
    preds, lean, rated, taste = _predict(ratings)
    skip = rated | {M.by_id[int(x)] for x in (exclude or []) if int(x) in M.by_id}
    rows = []
    for j, (stars, ev, why, rank) in preds.items():
        if j in skip or not _passes(j, genre, year_from, year_to):
            continue
        rows.append((rank, j, stars, ev / (ev + 0.6), why))
    rows.sort(reverse=True)
    picks = [_card(j, predicted=round(stars, 1), match=_match_from_rank(rank), confidence=round(conf, 2),
                   because=_because(why), reason="because" if why else "similar")
             for rank, j, stars, conf, why in rows[:limit]]
    if len(picks) < limit:  # not enough evidence (or no ratings yet): fill with crowd favourites
        have = {p["id"] for p in picks}
        for i in sorted(range(len(M.movies)), key=lambda i: -M.movies[i]["q"]):
            if len(picks) >= limit:
                break
            if i in skip or M.movies[i]["id"] in have or not _passes(i, genre, year_from, year_to):
                continue
            stars, rank = _guess(i, lean, taste) if rated else (M.movies[i]["q"], 0.0)
            picks.append(_card(i, predicted=round(stars, 1), match=_match_from_rank(rank), confidence=0,
                               because=[], reason="crowd"))
    return {"rated": len(rated), "lean": round(lean, 2), "items": picks}


def _match(stars):
    return int(round(max(0, min(100, (stars - 1.0) / 4.0 * 100))))


# ---------------------------------------------------------------- movie night (group)

STRATEGIES = {
    "average": "Highest average: the most enjoyment overall",
    "fair": "Fair: a high average, with a penalty when people disagree",
    "least_misery": "No one suffers: ranked by the least happy person",
}


def group_recommend(people, strategy="fair", genre=None, year_from=None, year_to=None, limit=5):
    """people: [{name, ratings: {movie_id: stars}}]. Builds a shortlist for the whole group."""
    people = [p for p in (people or []) if p.get("name")]
    if not people:
        raise ValueError("add at least one person")
    per = []
    seen = set()
    for p in people:
        preds, lean, rated, taste = _predict(p.get("ratings") or {})
        per.append((p["name"], preds, lean, taste))
        seen |= rated
    pool = set()
    for _, preds, _, _ in per:
        pool |= set(sorted(preds, key=lambda j: -preds[j][3])[:150])
    pool |= set(sorted(range(len(M.movies)), key=lambda i: -M.movies[i]["q"])[:60])

    rows = []
    for j in pool:
        if j in seen or not _passes(j, genre, year_from, year_to):
            continue
        fits, utils = [], []
        for name, preds, lean, taste in per:
            if j in preds:
                stars, _, why, util = preds[j]
            else:
                (stars, util), why = _guess(j, lean, taste), []
            utils.append(util)
            fits.append({"name": name, "predicted": round(stars, 1), "match": _match_from_rank(util),
                         "because": _because(why[:1])})
        avg = sum(utils) / len(utils)
        sd = math.sqrt(sum((v - avg) ** 2 for v in utils) / len(utils))
        score = {"average": avg, "least_misery": min(utils) + 0.01 * avg, "fair": avg - 0.75 * sd}.get(strategy, avg - 0.75 * sd)
        rows.append((score, j, fits, avg))
    rows.sort(key=lambda r: (-r[0], -M.movies[r[1]]["n"]))
    return {
        "strategy": strategy, "strategy_label": STRATEGIES.get(strategy, STRATEGIES["fair"]),
        "items": [_card(j, group_score=round(score, 3), group_match=_match_from_rank(avg), fits=fits)
                  for score, j, fits, avg in rows[:limit]],
    }


def tally(candidates, ballots, method="instant_runoff", scores=None):
    """Counts a ranked vote.

    candidates: movie ids on the shortlist. ballots: [{name, ranking: [ids, best first]}].
    scores: optional {id: group score}, used only to break exact ties (then the shortlist order).
    instant_runoff: count first choices; if nobody has more than half, drop the last place
    movie and move its voters to their next choice; repeat. borda: n-1 points for a first
    choice, n-2 for second, and so on.
    """
    cands = [int(c) for c in candidates]
    order = {c: k for k, c in enumerate(cands)}
    scores = {int(k): v for k, v in (scores or {}).items()}
    tiekey = lambda c: (scores.get(c, 0), -order[c])  # higher is better
    clean = []
    for b in ballots or []:
        r = []
        for c in b.get("ranking", []):
            c = int(c)
            if c in order and c not in r:
                r.append(c)
        if r:
            clean.append({"name": b.get("name", "?"), "ranking": r})
    if not clean:
        raise ValueError("no votes yet")

    n = len(cands)
    borda = {c: 0 for c in cands}
    for b in clean:
        for k, c in enumerate(b["ranking"]):
            borda[c] += n - 1 - k
    first = {c: sum(1 for b in clean if b["ranking"][0] == c) for c in cands}

    if method == "borda":
        winner = max(cands, key=lambda c: (borda[c], first[c]) + tiekey(c))
        tied = [c for c in cands if borda[c] == borda[winner]]
        return {"method": method, "winner": winner, "points": borda, "first": first,
                "voters": len(clean), "rounds": [], "tie_broken": len(tied) > 1,
                "summary": _summary_borda(winner, borda, len(tied) > 1)}

    alive = list(cands)
    rounds = []
    while True:
        counts = {c: 0 for c in alive}
        exhausted = 0
        for b in clean:
            top = next((c for c in b["ranking"] if c in counts), None)
            if top is None:
                exhausted += 1
            else:
                counts[top] += 1
        active = len(clean) - exhausted
        lead = max(alive, key=lambda c: (counts[c],) + tiekey(c))
        if counts[lead] * 2 > active or len(alive) == 1:
            rounds.append({"counts": counts, "eliminated": [], "exhausted": exhausted})
            winner = lead
            break
        zero = [c for c in alive if counts[c] == 0]
        if zero and len(zero) < len(alive):
            out = zero  # movies nobody ranked first (yet) all go together
        else:
            low = min(counts[c] for c in alive)
            out = [min((c for c in alive if counts[c] == low), key=lambda c: (borda[c],) + tiekey(c))]
        rounds.append({"counts": counts, "eliminated": out, "exhausted": exhausted})
        alive = [c for c in alive if c not in out]
    return {"method": "instant_runoff", "winner": winner, "rounds": rounds, "points": borda,
            "first": first, "voters": len(clean), "tie_broken": False,
            "summary": _summary_irv(winner, rounds, len(clean))}


def _t(mid):
    return M.movies[M.by_id[mid]]["t"] if M and mid in M.by_id else str(mid)


def _summary_irv(winner, rounds, voters):
    last = rounds[-1]["counts"][winner]
    if len(rounds) == 1:
        return f"{_t(winner)} wins outright with {last} of {voters} first-choice votes."
    return (f"{_t(winner)} wins after {len(rounds) - 1} elimination round"
            f"{'s' if len(rounds) > 2 else ''}, with {last} of {voters} votes in the final count.")


def _summary_borda(winner, points, tie):
    s = f"{_t(winner)} wins with {points[winner]} Borda points."
    return s + (" It was a tie, broken by the group fit score." if tie else "")


# ---------------------------------------------------------------- comments

MAX_COMMENT = 400


def clean_comment(name, text, spoiler=False):
    """Tidies a comment before it is saved. Raises ValueError if it can't be saved."""
    text = re.sub(r"[ \t]+", " ", (text or "").replace("\r", "")).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    if not text:
        raise ValueError("Write something first.")
    if len(text) > MAX_COMMENT:
        raise ValueError(f"Keep it under {MAX_COMMENT} characters ({len(text)} now).")
    name = re.sub(r"\s+", " ", (name or "")).strip()[:30] or "Guest"
    hint = bool(re.search(r"\b(dies|died|killed|ending|twist|turns out|in the end)\b", text, re.I))
    return {"name": name, "text": text, "spoiler": bool(spoiler), "spoiler_hint": hint and not spoiler,
            "ts": int(time.time() * 1000)}


# ---------------------------------------------------------------- page bridge

API = {f.__name__: f for f in (load, search, movie, browse, starter, similar, recommend,
                                group_recommend, tally, clean_comment)}


def call(name, args_json="{}"):
    """Called from JavaScript. Always returns JSON: {"ok": ...} or {"error": "..."}."""
    try:
        args = json.loads(args_json or "{}")
        result = API[name](**args) if isinstance(args, dict) else API[name](*args)
        return json.dumps({"ok": result}, ensure_ascii=False)
    except (ValueError, KeyError, TypeError) as e:
        return json.dumps({"error": str(e)})


# ---------------------------------------------------------------- terminal use

def _main(argv):
    from pathlib import Path
    load((Path(__file__).parent / "web" / "data" / "model.json").read_text(encoding="utf-8"))
    if len(argv) >= 2 and argv[0] == "--similar":
        hits = search(argv[1], 1)
        if not hits:
            print("No movie found.")
            return
        print(f"More like {hits[0]['title']} ({hits[0]['year']}):")
        for m in similar(hits[0]["id"], 10):
            print(f"  {m['match']:3d}%  {m['title']} ({m['year']})")
        return
    if not argv:
        print('Usage: python recommender.py "Movie you love" ["Another" ...]\n'
              '       python recommender.py --similar "Movie"')
        return
    ratings = {}
    for q in argv:
        stars = 5.0
        if "=" in q:
            q, stars = q.rsplit("=", 1)
            stars = float(stars)
        hits = search(q, 1)
        if hits:
            ratings[hits[0]["id"]] = stars
            print(f"You: {hits[0]['title']} ({hits[0]['year']}) {stars}*")
        else:
            print(f"Not found: {q}")
    print("\nRecommended for you:")
    for m in recommend(ratings, limit=10)["items"]:
        why = f"  (because you liked {m['because'][0]['title']})" if m["because"] else ""
        print(f"  {m['predicted']:.1f}*  {m['title']} ({m['year']}){why}")


if __name__ == "__main__":
    import sys
    _main(sys.argv[1:])
