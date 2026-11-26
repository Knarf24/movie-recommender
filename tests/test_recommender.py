"""Tests for recommender.py. Run: python tests/test_recommender.py (or pytest)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import recommender as R  # noqa: E402

R.load((ROOT / "web" / "data" / "model.json").read_text(encoding="utf-8"))


def find(q):
    return R.search(q, 1)[0]["id"]


def test_search_forgives_case_accents_articles_and_typos():
    assert R.search("matrix", 1)[0]["title"] == "The Matrix"
    assert R.search("leon", 1)[0]["title"].startswith("Léon")
    assert R.search("se7en", 1)[0]["title"] == "Seven"          # alternate title
    assert R.search("shawshenk redemption", 1)[0]["title"] == "The Shawshank Redemption"  # typo
    assert R.search("", 5) == []


def test_similar_finds_the_sequel():
    titles = [m["title"] for m in R.similar(find("toy story"), 5)]
    assert "Toy Story 2" in titles
    titles = [m["title"] for m in R.similar(find("godfather"), 3)]
    assert "The Godfather: Part II" in titles


def test_recommend_follows_taste_and_explains_why():
    kids = R.recommend({find("toy story"): 5, find("finding nemo"): 5, find("shrek"): 5}, limit=10)["items"]
    assert sum("Animation" in m["genres"] or "Children" in m["genres"] for m in kids) >= 7
    assert all(m["because"] for m in kids)
    rated = {find("toy story"), find("finding nemo"), find("shrek")}
    assert not rated & {m["id"] for m in kids}


def test_dislikes_push_neighbours_down():
    like = R.recommend({find("alien"): 5}, limit=30)["items"]
    both = R.recommend({find("alien"): 5, find("aliens"): 1}, limit=30)["items"]
    assert find("aliens") not in {m["id"] for m in both}
    a3 = find("alien 3")
    rank = lambda items: next((k for k, m in enumerate(items) if m["id"] == a3), 99)
    assert rank(both) >= rank(like)


def test_cold_start_and_filters():
    out = R.recommend({}, limit=5)
    assert len(out["items"]) == 5 and out["items"][0]["reason"] == "crowd"
    horror = R.recommend({find("toy story"): 5}, genre="Horror", limit=5)["items"]
    assert horror and all("Horror" in m["genres"] for m in horror)
    old = R.recommend({find("toy story"): 5}, year_to=1970, limit=5)["items"]
    assert all(m["year"] <= 1970 for m in old)


def test_group_shortlist_skips_what_anyone_has_seen():
    people = [{"name": "Ana", "ratings": {find("toy story"): 5}},
              {"name": "Ben", "ratings": {find("alien"): 5, find("finding nemo"): 4}}]
    for strategy in R.STRATEGIES:
        out = R.group_recommend(people, strategy=strategy, limit=5)
        ids = {m["id"] for m in out["items"]}
        assert len(ids) == 5
        assert not ids & {find("toy story"), find("alien"), find("finding nemo")}
        assert [f["name"] for f in out["items"][0]["fits"]] == ["Ana", "Ben"]


def test_instant_runoff_moves_votes_until_majority():
    a, b, c = 1, 2, 3  # MovieLens ids for Toy Story, Jumanji, Grumpier Old Men
    ballots = [{"name": "1", "ranking": [a, b, c]}, {"name": "2", "ranking": [a, c, b]},
               {"name": "3", "ranking": [b, c, a]}, {"name": "4", "ranking": [c, b, a]},
               {"name": "5", "ranking": [c, b, a]}]
    out = R.tally([a, b, c], ballots)
    # Round 1: a=2, b=1, c=2 -> b is out, its vote goes to c -> c wins 3 of 5.
    assert out["rounds"][0]["eliminated"] == [b]
    assert out["winner"] == c
    assert "wins after 1 elimination round" in out["summary"]
    out = R.tally([a, b, c], ballots, method="borda")
    assert out["points"] == {a: 4, b: 5, c: 6} and out["winner"] == c


def test_movies_with_no_first_choices_drop_together():
    ballots = [{"name": "1", "ranking": [1, 2]}, {"name": "2", "ranking": [2, 1]}, {"name": "3", "ranking": [3, 1]}]
    out = R.tally([1, 2, 3, 5, 6], ballots)
    assert sorted(out["rounds"][0]["eliminated"]) == [5, 6]
    assert out["winner"] == 1  # 3 is dropped next, its voter moves to 1


def test_outright_winner_and_ties():
    out = R.tally([1, 2], [{"name": "x", "ranking": [2, 1]}])
    assert out["winner"] == 2 and len(out["rounds"]) == 1
    out = R.tally([1, 2], [{"name": "x", "ranking": [1, 2]}, {"name": "y", "ranking": [2, 1]}],
                  scores={1: 3.0, 2: 4.0})
    assert out["winner"] == 2  # tie broken by group score


def test_comments_are_tidied_and_checked():
    c = R.clean_comment("  Sam  ", "  Great   film!\n\n\n\nLoved it ")
    assert c["name"] == "Sam" and c["text"] == "Great film!\n\nLoved it" and not c["spoiler"]
    assert R.clean_comment("", "the twist at the end")["spoiler_hint"]
    for bad in ("", "   ", "x" * 401):
        try:
            R.clean_comment("a", bad)
            assert False
        except ValueError:
            pass


def test_bridge_returns_json_errors():
    assert json.loads(R.call("search", json.dumps({"query": "heat", "limit": 1})))["ok"][0]["title"] == "Heat"
    assert "error" in json.loads(R.call("movie", json.dumps({"movie_id": 999999999})))
    assert "error" in json.loads(R.call("tally", json.dumps({"candidates": [1], "ballots": []})))


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("ok ", t.__name__)
    print(f"{len(tests)} tests passed")
