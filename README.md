# 🎬 Movie Recommender

**Live demo:** https://knarf24.github.io/movie-recommender/

**The problem:** "What should we watch?" Streaming apps push whatever they want to promote, and when friends or
family watch together, nobody can agree and the evening goes on scrolling.

**The app:** rate a few movies you've seen and get picks you'll actually like, each with the reason it was chosen.
Then run a movie night: everyone adds favourites, the app builds a shortlist that suits the whole group, and a
secret ranked vote picks the winner. Free, no sign-up, no API keys, and it works offline after the first visit.

- **🎯 For you:** search and rate movies (or tap the stars on a starter set). Picks show a predicted star rating,
  a match percent and "Because you liked …". Filter by genre and era. Rating anything re-tunes the picks instantly.
- **🎞️ Movie details:** average rating, tags people gave it, links to TMDB, IMDb and MovieLens, "More like this",
  and your own rating.
- **🍿 Movie night:** add up to 8 people and the movies each of them loves (or hates), or try the demo night.
  Choose how to pick for a group: *Fair* (high average with a penalty when people disagree), *Highest average*,
  or *No one suffers* (ranked by the least happy person). Movies anyone has already seen are left out. Each
  shortlisted movie shows a bar for how much each person should enjoy it.
- **🗳️ Secret ballot:** pass the phone round; each person ranks the shortlist privately. The winner is counted by
  **instant runoff** (keep dropping the last place movie until one has a majority) or **Borda count** (points by
  position), with every round shown.
- **💬 Comments:** a comment thread on every movie, with likes, and spoilers hidden until tapped (the app also
  hides a comment that sounds like a spoiler).

All the recommending, group shortlists, vote counting and comment checks are **Python** (`recommender.py`, standard
library only) running **inside your browser** with [Pyodide](https://pyodide.org). It is hosted free on GitHub Pages.

## How the recommendations work

`build_model.py` turns the MovieLens ratings into `web/data/model.json` (about 1.2 MB):

1. Keeps the 2,269 movies with at least 10 ratings (fewer is too noisy).
2. Centres every person's ratings on their own average, because some people rate everything 4 stars or more.
3. Measures how alike two movies are from the people who rated both (**adjusted cosine similarity**), shrunk
   towards zero when only a few people rated both, and keeps each movie's 40 closest neighbours.
4. Gives each movie a fair average (a **Bayesian average**), so 3 five-star ratings don't beat 300 four-and-a-half-star ones.

In the browser, `recommender.py` predicts your stars for a movie as its fair average, plus your personal lean,
plus how much you liked its neighbours compared with their averages (**item-based collaborative filtering**).
It ranks by how strongly the evidence lifts a movie, how sure it is, and how well it fits the genres you rate
highly, and it remembers which of your movies led to each pick so it can say why. With no ratings yet it shows
crowd favourites.

Built by combining three GeeksforGeeks Python projects:

| GeeksforGeeks project | What it does here |
|---|---|
| [Movie Recommendation System](https://www.geeksforgeeks.org/python/movie-recommendation-system-using-django/) | Personal picks, "more like this" and the group shortlist |
| [Voting System](https://www.geeksforgeeks.org/python/voting-system-project-using-django-framework/) | Secret ranked ballots counted by instant runoff or Borda count |
| [Comments System](https://www.geeksforgeeks.org/python/django-project-to-create-a-comments-system/) | Comment threads on each movie, with likes and spoiler hiding |

## Files

| File | What it is |
|---|---|
| `recommender.py` | Search, recommendations, similar movies, group shortlist, vote counting and comment checks (Python, standard library only) |
| `build_model.py` | Builds `web/data/model.json` from the MovieLens CSVs (needs numpy): `python build_model.py` |
| `dataset/` | The MovieLens ml-latest-small CSV files and their licence |
| `web/` | The page: `index.html`, `main.js` (drawing, taps, saving to the device), `style.css`, `sw.js` (offline and saved Python), `pyfast.js` (quick Python start), and Pyodide in `web/pyodide/` |
| `tests/test_recommender.py` | Tests: `python tests/test_recommender.py` |
| `build_site.sh`, `.github/workflows/` | Builds `_site/` and publishes it to GitHub Pages; runs the tests on every push |

Try it in a terminal too:

```
python recommender.py "Toy Story" "Finding Nemo" "Shrek=4"
python recommender.py --similar "The Godfather"
```

## Limits

- The data stops in 2018 and covers 2,269 well-known movies, so newer releases are not there.
- MovieLens has no posters, so the cards use artwork drawn from each movie's genre, with links out to TMDB and IMDb.
- Ratings, movie nights and comments are saved in this browser only. Comments are not shared with other people.

## Privacy

Nothing leaves your device. There is no server and no account.

## Data and licence

Movie data: [MovieLens](https://grouplens.org/datasets/movielens/) ml-latest-small (100,836 ratings and 3,683
tags by 610 people, 1996 to 2018), by GroupLens Research at the University of Minnesota. It is used and
redistributed here for non-commercial purposes under its own licence (see `dataset/MOVIELENS-LICENSE-README.txt`).
This project is not endorsed by the University of Minnesota or GroupLens. Citation: F. Maxwell Harper and Joseph A.
Konstan. 2015. The MovieLens Datasets: History and Context. ACM Transactions on Interactive Intelligent Systems
(TiiS) 5, 4: 19:1–19:19. https://doi.org/10.1145/2827872

Code: MIT. Pyodide is MPL-2.0.

## Fast loading

The page shows straight away and Python starts in the background, so nothing waits on a
"Starting Python" screen. Anything that needs Python simply waits for it if you are quicker.

- **Saved on the device** (`web/sw.js`): after the first visit, Python (Pyodide) and its packages are kept in
  the browser, so a refresh or a later visit doesn't download them again. Every app on the same site shares
  that one saved copy. The app's own files are still fetched fresh, so updates show up right away.
- **Quick restart** (`web/pyfast.js`): the first visit also saves a snapshot of a freshly started Python.
  Later visits restore it instead of starting Python from scratch (about 1.2 s down to 0.3 s on a laptop).
  If the snapshot can't be used (for example after a Pyodide upgrade), Python starts normally and a new one
  is saved.
- `build_site.sh` writes the Pyodide version into `sw.js`, so upgrading `web/pyodide/` needs no other change.
