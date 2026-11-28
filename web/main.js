// The page: drawing, taps and saving to this device. All the recommending, group
// shortlists, vote counting and comment checks happen in Python (recommender.py).
"use strict";

let py = null;
let INFO = null;
const $ = (id) => document.getElementById(id);

// ------------------------------------------------------------------ storage (this device only)
const store = {
  get(key, fallback) {
    try { const v = localStorage.getItem("mr." + key); return v ? JSON.parse(v) : fallback; } catch { return fallback; }
  },
  set(key, value) { try { localStorage.setItem("mr." + key, JSON.stringify(value)); } catch { /* private mode */ } },
};
let ratings = store.get("ratings", {});      // {movieId: stars}
let comments = store.get("comments", {});    // {movieId: [comment]}
let night = store.get("night", null) || { people: [], sel: 0, shortlist: [], ballots: [], voter: 0, step: 1 };

function saveRatings() { store.set("ratings", ratings); updateCounts(); }
function saveNight() { store.set("night", night); }

// ------------------------------------------------------------------ Python bridge
function call(name, args = {}) {
  const out = JSON.parse(py.globals.get("call")(name, JSON.stringify(args)));
  if ("error" in out) throw new Error(out.error);
  return out.ok;
}

// The page shows right away; Python and the movie data load in the background, and the lists fill in
// as soon as they are ready (about half a second on a repeat visit).
async function start() {
  $("app").hidden = false;
  const want = (location.hash || "").slice(1);
  previewTab(["foryou", "night", "browse"].includes(want) ? want : "foryou");
  document.querySelectorAll("#tabs button").forEach((b) => { b.onclick = () => { if (!INFO) previewTab(b.dataset.tab); }; });
  document.documentElement.dataset.ui = "ready";
  try {
    const [pyodide, code, model] = await Promise.all([
      loadPyodideFast(),
      fetch("recommender.py").then((r) => { if (!r.ok) throw new Error("recommender.py missing"); return r.text(); }),
      fetch("data/model.json").then((r) => { if (!r.ok) throw new Error("model missing"); return r.text(); }),
    ]);
    py = pyodide;
    $("loadText").textContent = "Loading 100,836 movie ratings…";
    py.FS.writeFile("/home/pyodide/recommender.py", code);
    py.runPython("from recommender import call");
    INFO = call("load", { text: model });
  } catch (err) {
    $("loading").classList.add("failed");
    $("loadText").textContent = "Sorry, Python could not start in this browser: " + err.message;
    return;
  }
  $("loading").hidden = true;
  setup();
  if ($("q").value.trim()) $("q").dispatchEvent(new Event("input")); // typed while Python was starting
  document.documentElement.dataset.py = "ready";
  // Keeps Python saved on this device so the next visit starts without downloading it (see sw.js).
  if ("serviceWorker" in navigator && isSecureContext) navigator.serviceWorker.register("sw.js").catch(() => {});
}

// Switches the visible tab before Python is ready (the lists fill in once it is).
function previewTab(name) {
  document.querySelectorAll("#tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === name)));
  for (const t of ["foryou", "night", "browse"]) $("t-" + t).hidden = t !== name;
  history.replaceState(null, "", "#" + name);
}

// ------------------------------------------------------------------ small DOM helper
function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") e.className = v;
    else if (k === "text") e.textContent = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) e.append(kid.nodeType ? kid : String(kid));
  return e;
}

function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { t.hidden = true; }, 2600);
}

// ------------------------------------------------------------------ poster artwork
const GENRE_LOOK = {
  Action: ["#ff5f45", "#7a1730", "💥"], Adventure: ["#ffb547", "#7b3b0c", "🧭"], Animation: ["#38d0ff", "#3d2bb5", "✏️"],
  Children: ["#7cf07a", "#1c7a6a", "🎈"], Comedy: ["#ffd84a", "#c2410c", "😂"], Crime: ["#9aa4b8", "#191c2c", "🕵️"],
  Documentary: ["#7dd3c8", "#134e4a", "🎥"], Drama: ["#c084fc", "#3b1260", "🎭"], Fantasy: ["#a78bfa", "#1e1b6b", "🐉"],
  "Film-Noir": ["#d4d4d8", "#18181b", "🚬"], Horror: ["#ff4d6d", "#1a0410", "🔪"], IMAX: ["#5eead4", "#0f3a52", "🎞️"],
  Musical: ["#f9a8d4", "#831843", "🎵"], Mystery: ["#818cf8", "#111538", "🔍"], Romance: ["#ff8fab", "#7a1f4b", "💘"],
  "Sci-Fi": ["#3fd6c6", "#102a6b", "🚀"], Thriller: ["#fb923c", "#2b0d0d", "⚡"], War: ["#a3a380", "#2a2a17", "🎖️"],
  Western: ["#e3a95d", "#5a2d0c", "🤠"],
};
function poster(m, badge) {
  const look = GENRE_LOOK[m.genres[0]] || ["#7a6bff", "#1b1735", "🎬"];
  const second = GENRE_LOOK[m.genres[1]] || look;
  const angle = (m.id * 47) % 360;
  const p = el("div", { class: "poster", role: "img", "aria-label": `${m.title} poster artwork` },
    badge ? el("span", { class: "badge", text: badge }) : null,
    el("span", { class: "pe", "aria-hidden": "true", text: look[2] }),
    el("span", { class: "pt", text: m.title }),
    el("span", { class: "py", text: m.year || "" }));
  p.style.background = `linear-gradient(${angle}deg, ${look[1]}, ${look[0]} 60%, ${second[0]})`;
  return p;
}

// ------------------------------------------------------------------ stars
function starsWidget(movieId, onChange) {
  const box = el("div", { class: "stars", role: "radiogroup", "aria-label": "Your rating" });
  const draw = () => {
    box.replaceChildren();
    const cur = ratings[movieId] || 0;
    for (let s = 1; s <= 5; s++) {
      box.append(el("button", {
        class: s <= cur ? "on" : "", type: "button", "aria-label": `${s} star${s > 1 ? "s" : ""}`, "aria-pressed": s === cur ? "true" : "false",
        text: "★",
        onclick: (e) => {
          e.stopPropagation();
          if (ratings[movieId] === s) delete ratings[movieId]; else ratings[movieId] = s;
          saveRatings();
          draw();
          onChange && onChange();
        },
      }));
    }
  };
  draw();
  return box;
}

// ------------------------------------------------------------------ cards
function card(m, opts = {}) {
  const open = () => openMovie(m.id);
  const body = el("div", { class: "body" },
    el("div", { class: "ct", onclick: open, text: m.title }),
    el("div", { class: "cy", text: [m.year, m.genres.slice(0, 2).join(" · ")].filter(Boolean).join(" · ") }));
  if (opts.pred && m.predicted != null) {
    body.append(el("div", { class: "pred" }, "We think ", el("b", { text: `${m.predicted.toFixed(1)}★` })));
    if (m.because && m.because.length) body.append(el("div", { class: "why", text: `Because you liked ${m.because.map((b) => b.title).join(" and ")}` }));
    else if (m.reason === "crowd") body.append(el("div", { class: "why", text: "Loved by MovieLens viewers" }));
  } else if (!opts.noAvg) {
    body.append(el("div", { class: "cy", text: `${m.avg.toFixed(1)}★ average · ${m.count} ratings` }));
  }
  if (opts.rate) body.append(starsWidget(m.id, opts.onRate));
  const badge = opts.badge ? opts.badge(m) : null;
  const p = poster(m, badge);
  p.addEventListener("click", open);
  return el("article", { class: "card" }, p, body);
}

// ------------------------------------------------------------------ setup
function setup() {
  for (const sel of ["fGenre", "bGenre", "nGenre"]) {
    for (const g of INFO.genres) $(sel).append(el("option", { value: g, text: g }));
  }
  document.querySelectorAll("#tabs button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
  setupSearch($("q"), $("qres"), (m) => rateRow(m));
  $("fGenre").addEventListener("change", renderRecs);
  $("fEra").addEventListener("change", renderRecs);
  $("clearRatings").addEventListener("click", () => {
    if (!Object.keys(ratings).length) return;
    ratings = {};
    saveRatings();
    renderForYou();
    toast("Your ratings were cleared.");
  });
  for (const id of ["bGenre", "bSort", "bEra"]) $(id).addEventListener("change", () => renderBrowse(true));
  $("bMore").addEventListener("click", () => renderBrowse(false));
  setupDetail();
  setupNight();
  updateCounts();
  renderForYou();
  const want = (location.hash || "").slice(1);
  showTab(["foryou", "night", "browse"].includes(want) ? want : "foryou");
}

function showTab(name) {
  document.querySelectorAll("#tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === name)));
  for (const t of ["foryou", "night", "browse"]) $("t-" + t).hidden = t !== name;
  if (name === "browse" && !$("browse").children.length) renderBrowse(true);
  if (name === "night") renderNight();
  if (name === "foryou") renderForYou();
  history.replaceState(null, "", "#" + name);
}

function updateCounts() {
  const n = Object.keys(ratings).length;
  $("ratedCount").textContent = n;
  $("mineCount").textContent = n;
}

function era(sel) {
  const v = $(sel).value;
  if (!v) return {};
  const [a, b] = v.split("-").map(Number);
  return { year_from: a || null, year_to: b };
}

// ------------------------------------------------------------------ search
function setupSearch(input, box, rowFn) {
  let timer;
  const run = () => {
    const q = input.value.trim();
    if (!q) { box.hidden = true; return; }
    const hits = call("search", { query: q, limit: 8 });
    box.replaceChildren(...(hits.length ? hits.map(rowFn) : [el("div", { class: "qrow small", text: "No movie found. MovieLens covers 2,269 well-known movies up to 2018." })]));
    box.hidden = false;
  };
  input.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(run, 120); });
  input.addEventListener("focus", () => { if (input.value.trim()) run(); });
  input.addEventListener("keydown", (e) => { if (e.key === "Escape") { box.hidden = true; input.blur(); } });
  document.addEventListener("click", (e) => { if (!box.contains(e.target) && e.target !== input) box.hidden = true; });
}

function qrowBase(m, ...right) {
  return el("div", { class: "qrow" }, poster(m),
    el("div", { class: "qt" },
      el("b", { text: m.title, onclick: () => openMovie(m.id) }),
      el("span", { class: "small", text: [m.year, m.genres.slice(0, 3).join(", ")].filter(Boolean).join(" · ") })),
    ...right);
}

function rateRow(m) {
  return qrowBase(m, starsWidget(m.id, () => { renderRecs(); renderStarter(); renderMine(); }));
}

// ------------------------------------------------------------------ for you
function renderForYou() {
  renderStarter();
  renderRecs();
  renderMine();
}

function renderStarter() {
  const n = Object.keys(ratings).length;
  $("starterWrap").hidden = n >= 8;
  if (n >= 8) return;
  $("starterHint").textContent = n < 3
    ? `Tap the stars on movies you've seen. ${3 - n} more rating${3 - n === 1 ? "" : "s"} and your picks become personal.`
    : "Nice. Keep rating to sharpen your picks, or scroll down to see them.";
  if (!$("starter").children.length) {
    $("starter").replaceChildren(...call("starter", { limit: 18 }).map((m) => card(m, { rate: true, noAvg: true, onRate: () => { renderRecs(); renderMine(); renderStarter(); } })));
  }
}

function renderRecs() {
  const n = Object.keys(ratings).length;
  const res = call("recommend", { ratings, genre: $("fGenre").value || null, ...era("fEra"), limit: 20 });
  $("recTitle").textContent = n ? "Top picks for you" : "Crowd favourites";
  $("recNote").textContent = n
    ? `Based on your ${n} rating${n === 1 ? "" : "s"}. Rate any pick to keep tuning it; tap a poster for details and comments.`
    : "Rate a few movies above and these turn into picks for you, each with the reason it was chosen.";
  $("recs").replaceChildren(...res.items.map((m) => card(m, {
    pred: n > 0, rate: true, badge: (x) => (n ? `${x.match}% match` : null),
    onRate: () => { renderRecs(); renderMine(); renderStarter(); },
  })));
}

function renderMine() {
  const ids = Object.keys(ratings);
  if (!ids.length) { $("mine").replaceChildren(el("p", { class: "small", text: "Nothing rated yet." })); return; }
  const rows = ids.map((id) => { try { return call("movie", { movie_id: +id }); } catch { return null; } }).filter(Boolean)
    .sort((a, b) => (ratings[b.id] - ratings[a.id]) || a.title.localeCompare(b.title));
  $("mine").replaceChildren(...rows.map((m) => el("div", { class: "mrow" },
    el("span", { text: `${m.title} (${m.year})`, onclick: () => openMovie(m.id) }),
    starsWidget(m.id, () => { renderRecs(); renderMine(); }))));
}

// ------------------------------------------------------------------ browse
let browseOffset = 0;
function renderBrowse(reset) {
  if (reset) { browseOffset = 0; $("browse").replaceChildren(); }
  const res = call("browse", { genre: $("bGenre").value || null, sort: $("bSort").value, ...era("bEra"), limit: 24, offset: browseOffset });
  browseOffset += res.items.length;
  $("browse").append(...res.items.map((m) => card(m, { rate: true })));
  $("bNote").textContent = `${res.total.toLocaleString()} movies. "Best rated" uses a fair average, so a movie with three 5-star ratings doesn't beat one with 300 ratings of 4.5.`;
  $("bMore").hidden = browseOffset >= res.total;
}

// ------------------------------------------------------------------ movie details + comments
let current = null;
function setupDetail() {
  const d = $("detail");
  $("dClose").addEventListener("click", () => d.close());
  d.addEventListener("click", (e) => { if (e.target === d) d.close(); });
  d.addEventListener("close", () => { if (!$("t-foryou").hidden) renderForYou(); });
  $("cName").value = store.get("name", "");
  $("cForm").addEventListener("submit", (e) => {
    e.preventDefault();
    $("cErr").textContent = "";
    try {
      const c = call("clean_comment", { name: $("cName").value, text: $("cText").value, spoiler: $("cSpoiler").checked });
      if (c.spoiler_hint) { c.spoiler = true; toast("That sounds like a spoiler, so it is hidden until someone taps it."); }
      c.likes = 0;
      (comments[current] ||= []).unshift(c);
      store.set("comments", comments);
      store.set("name", c.name === "Guest" ? "" : c.name);
      $("cText").value = "";
      $("cSpoiler").checked = false;
      renderComments();
    } catch (err) {
      $("cErr").textContent = err.message;
    }
  });
}

function openMovie(id) {
  const m = call("movie", { movie_id: id });
  current = m.id;
  const p = poster(m);
  p.classList.add("big");
  $("dPoster").replaceWith(p);
  p.id = "dPoster";
  $("dTitle").textContent = `${m.title}${m.year ? ` (${m.year})` : ""}`;
  $("dAka").textContent = m.aka ? `Also known as ${m.aka}` : "";
  $("dMeta").replaceChildren(
    el("span", {}, el("b", { text: `${m.avg.toFixed(1)}★` }), ` average from ${m.count} ratings`),
    el("span", { text: m.genres.join(" · ") }));
  $("dTags").replaceChildren(...m.tags.map((t) => el("span", { class: "chip", text: `#${t}` })));
  $("dStars").replaceWith(Object.assign(starsWidget(m.id), { id: "dStars" }));
  const links = [];
  if (m.tmdb) links.push(el("a", { href: `https://www.themoviedb.org/movie/${m.tmdb}`, target: "_blank", rel: "noopener", text: "TMDB ↗" }));
  if (m.imdb) links.push(el("a", { href: `https://www.imdb.com/title/tt${m.imdb}/`, target: "_blank", rel: "noopener", text: "IMDb ↗" }));
  links.push(el("a", { href: `https://movielens.org/movies/${m.id}`, target: "_blank", rel: "noopener", text: "MovieLens ↗" }));
  $("dLinks").replaceChildren(...links);
  $("dSimilar").replaceChildren(...call("similar", { movie_id: m.id, limit: 12 }).map((s) =>
    card(s, { noAvg: true, badge: (x) => `${x.match}%` })));
  renderComments();
  const d = $("detail");
  if (!d.open) d.showModal();
  d.scrollTop = 0;
}

function renderComments() {
  const list = comments[current] || [];
  $("dCount").textContent = list.length ? `(${list.length})` : "";
  $("cList").replaceChildren(...(list.length ? list.map((c, k) => {
    const text = el("p", { class: c.spoiler ? "spoil" : "", text: c.text, title: c.spoiler ? "Spoiler: tap to show" : null });
    if (c.spoiler) text.addEventListener("click", () => text.classList.remove("spoil"));
    return el("div", { class: "comment" },
      el("div", { class: "ch" }, el("span", {}, el("b", { text: c.name }), ` · ${new Date(c.ts).toLocaleDateString()}${c.spoiler ? " · spoiler" : ""}`),
        el("span", { class: "acts" },
          el("button", { type: "button", "aria-label": "Like", text: `👍 ${c.likes || 0}`, onclick: () => { c.likes = (c.likes || 0) + 1; store.set("comments", comments); renderComments(); } }),
          el("button", { type: "button", "aria-label": "Delete comment", text: "🗑", onclick: () => { list.splice(k, 1); store.set("comments", comments); renderComments(); } }))),
      text);
  }) : [el("p", { class: "small", text: "No comments yet. Be the first." })]));
}

// ------------------------------------------------------------------ movie night
const LOVE = 5, OK = 3.5, NO = 1;

function setupNight() {
  $("addPerson").addEventListener("submit", (e) => {
    e.preventDefault();
    const name = $("personName").value.trim().slice(0, 20);
    if (!name) return;
    if (night.people.some((p) => p.name.toLowerCase() === name.toLowerCase())) { toast(`${name} is already in.`); return; }
    if (night.people.length >= 8) { toast("Up to 8 people per night."); return; }
    night.people.push({ name, ratings: {} });
    night.sel = night.people.length - 1;
    $("personName").value = "";
    resetVotes();
    saveNight();
    renderNight();
    $("pq").focus();
  });
  setupSearch($("pq"), $("pqres"), (m) => qrowBase(m, el("div", { class: "qbtns" },
    el("button", { type: "button", text: "❤️ Love", onclick: () => addFav(m, LOVE) }),
    el("button", { type: "button", text: "🙂 OK", onclick: () => addFav(m, OK) }),
    el("button", { type: "button", text: "👎 No", onclick: () => addFav(m, NO) }))));
  $("demoNight").addEventListener("click", demoNight);
  $("buildShort").addEventListener("click", buildShortlist);
  $("back1").addEventListener("click", () => goStep(1));
  $("strategy").addEventListener("change", () => { night.strategy = $("strategy").value; saveNight(); });
  $("nGenre").addEventListener("change", () => { night.genre = $("nGenre").value; saveNight(); });
  $("startVote").addEventListener("click", () => { resetVotes(); goStep(3); });
  $("imReady").addEventListener("click", () => { $("passPhone").hidden = true; $("ballot").hidden = false; renderBallot(); });
  $("resetBallot").addEventListener("click", () => { ballotPick = []; renderBallot(); });
  $("castVote").addEventListener("click", castVote);
  $("method").addEventListener("change", renderWinner);
  $("revote").addEventListener("click", () => { resetVotes(); goStep(3); });
  $("newNight").addEventListener("click", () => {
    night = { people: [], sel: 0, shortlist: [], ballots: [], voter: 0, step: 1 };
    saveNight();
    renderNight();
  });
}

function resetVotes() { night.ballots = []; night.voter = 0; ballotPick = []; }

function addFav(m, stars) {
  const p = night.people[night.sel];
  if (!p) return;
  p.ratings[m.id] = stars;
  p.titles = { ...(p.titles || {}), [m.id]: m.title };
  $("pq").value = "";
  $("pqres").hidden = true;
  saveNight();
  renderPeople();
}

function demoNight() {
  const pick = (q) => call("search", { query: q, limit: 1 })[0];
  const person = (name, likes, dislikes = []) => {
    const p = { name, ratings: {}, titles: {} };
    for (const [q, s] of [...likes.map((q) => [q, LOVE]), ...dislikes.map((q) => [q, NO])]) {
      const m = pick(q);
      if (m) { p.ratings[m.id] = s; p.titles[m.id] = m.title; }
    }
    return p;
  };
  night = {
    people: [
      person("Amara", ["Shrek", "Finding Nemo", "Harry Potter and the Sorcerer's Stone"]),
      person("Ben", ["The Matrix", "Star Wars: Episode IV", "Lord of the Rings: The Fellowship"], ["The Notebook"]),
      person("Chipo", ["Titanic", "Pride & Prejudice", "The Princess Bride"]),
    ],
    sel: 0, shortlist: [], ballots: [], voter: 0, step: 1, strategy: "fair", genre: "",
  };
  saveNight();
  renderNight();
  toast("Demo night: three friends with different tastes.");
}

function goStep(n) {
  night.step = n;
  saveNight();
  renderNight();
  $("t-night").scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderNight() {
  const step = night.step || 1;
  document.querySelectorAll("#steps li").forEach((li) => {
    const s = +li.dataset.step;
    li.className = s === step ? "on" : s < step ? "done" : "";
  });
  for (let k = 1; k <= 4; k++) $("n" + k).hidden = k !== step;
  $("strategy").value = night.strategy || "fair";
  $("nGenre").value = night.genre || "";
  if (step === 1) renderPeople();
  if (step === 2) renderShortlist();
  if (step === 3) renderVoteStep();
  if (step === 4) renderWinner();
}

function renderPeople() {
  const ppl = night.people;
  $("people").replaceChildren(...ppl.map((p, k) => el("span", { class: "person" + (k === night.sel ? " sel" : "") },
    el("span", { style: "cursor:pointer", onclick: () => { night.sel = k; saveNight(); renderPeople(); }, text: p.name }),
    el("span", { class: "n", text: `${Object.keys(p.ratings).length} 🎬` }),
    el("button", { type: "button", "aria-label": `Remove ${p.name}`, text: "✕", onclick: () => {
      ppl.splice(k, 1); night.sel = Math.max(0, Math.min(night.sel, ppl.length - 1)); resetVotes(); saveNight(); renderPeople();
    } }))));
  if (!ppl.length) $("people").append(el("span", { class: "small", text: "Add everyone who's watching tonight, or try the demo." }));
  const p = ppl[night.sel];
  $("personEdit").hidden = !p;
  if (p) {
    $("peName").textContent = p.name;
    const mine = Object.keys(ratings).length;
    const chips = Object.entries(p.ratings).map(([id, s]) => el("span", { class: "chip" },
      `${s >= LOVE ? "❤️" : s >= OK ? "🙂" : "👎"} ${(p.titles || {})[id] || id}`,
      el("button", { type: "button", "aria-label": "Remove", text: "✕", onclick: () => { delete p.ratings[id]; saveNight(); renderPeople(); } })));
    if (mine && !p.usedMine) {
      chips.push(el("button", { type: "button", class: "ghost", text: `Use my ${mine} ratings from "For you"`, onclick: () => {
        for (const [id, s] of Object.entries(ratings)) {
          p.ratings[id] = s;
          try { p.titles = { ...(p.titles || {}), [id]: call("movie", { movie_id: +id }).title }; } catch { /* skip */ }
        }
        p.usedMine = true; saveNight(); renderPeople();
      } }));
    }
    $("pfavs").replaceChildren(...chips);
  }
  $("buildShort").disabled = !ppl.length;
}

function buildShortlist() {
  try {
    const res = call("group_recommend", { people: night.people.map((p) => ({ name: p.name, ratings: p.ratings })),
      strategy: $("strategy").value, genre: $("nGenre").value || null, limit: 5 });
    night.shortlist = res.items;
    night.strategyLabel = res.strategy_label;
    resetVotes();
    goStep(2);
  } catch (err) {
    toast(err.message);
  }
}

function renderShortlist() {
  $("shortNote").textContent = `${night.strategyLabel || ""}. Movies anyone has already seen are left out. The bars show how much each person should enjoy it.`;
  $("shortlist").replaceChildren(...night.shortlist.map((m) => {
    const p = poster(m);
    p.addEventListener("click", () => openMovie(m.id));
    return el("div", { class: "sitem" }, p,
      el("div", { class: "sbody" },
        el("div", { class: "ct", onclick: () => openMovie(m.id), text: `${m.title} (${m.year})` }),
        el("div", { class: "small", text: `${m.genres.slice(0, 3).join(" · ")} · group fit ${m.group_match}%` }),
        el("div", { class: "fits" }, ...m.fits.flatMap((f) => [
          el("span", { text: f.name }),
          el("div", { class: "bar", title: `${f.match}%` }, el("i", { style: `width:${f.match}%` })),
          el("span", { class: "small", text: f.because.length ? `${f.predicted}★ · likes ${f.because[0].title}` : `${f.predicted}★` }),
        ]))));
  }));
}

let ballotPick = [];
function renderVoteStep() {
  const voter = night.people[night.voter];
  if (!voter) { goStep(4); return; }
  $("voteTitle").textContent = "Secret ballot";
  $("voteProgress").textContent = `${night.voter + 1} of ${night.people.length}`;
  $("voterName").textContent = voter.name;
  $("voterName2").textContent = voter.name;
  $("passPhone").hidden = false;
  $("ballot").hidden = true;
  ballotPick = [];
}

function renderBallot() {
  $("ballotList").replaceChildren(...night.shortlist.map((m) => {
    const k = ballotPick.indexOf(m.id);
    return el("button", { type: "button", class: "bopt" + (k >= 0 ? " picked" : ""), onclick: () => {
      if (k >= 0) ballotPick.splice(k, 1); else ballotPick.push(m.id);
      renderBallot();
    } }, el("span", { class: "rank", text: k >= 0 ? k + 1 : "" }),
      el("span", {}, el("b", { text: m.title }), el("span", { class: "small", text: ` ${m.year} · ${m.genres.slice(0, 2).join(", ")}` })));
  }));
  $("castVote").disabled = !ballotPick.length;
  $("castVote").textContent = ballotPick.length && ballotPick.length < night.shortlist.length
    ? `Cast my vote (${ballotPick.length} ranked)` : "Cast my vote";
}

function castVote() {
  const voter = night.people[night.voter];
  night.ballots.push({ name: voter.name, ranking: ballotPick.slice() });
  night.voter += 1;
  ballotPick = [];
  saveNight();
  if (night.voter >= night.people.length) goStep(4);
  else { toast(`Thanks ${voter.name}! Vote saved.`); renderVoteStep(); }
}

function renderWinner() {
  const byId = Object.fromEntries(night.shortlist.map((m) => [m.id, m]));
  let res;
  try {
    res = call("tally", { candidates: night.shortlist.map((m) => m.id), ballots: night.ballots, method: $("method").value,
      scores: Object.fromEntries(night.shortlist.map((m) => [m.id, m.group_score])) });
  } catch (err) {
    $("winner").replaceChildren(el("p", { text: err.message }));
    $("rounds").replaceChildren();
    return;
  }
  const w = byId[res.winner];
  const p = poster(w);
  p.addEventListener("click", () => openMovie(w.id));
  $("winner").replaceChildren(p, el("div", {},
    el("div", { class: "wl", text: "Tonight you're watching" }),
    el("h2", { text: `${w.title} (${w.year})` }),
    el("p", { text: res.summary }),
    el("button", { class: "ghost", type: "button", text: "Details & comments", onclick: () => openMovie(w.id) })));
  const name = (id) => byId[id].title;
  let table;
  if (res.method === "borda") {
    const ids = Object.keys(res.points).map(Number).sort((a, b) => res.points[b] - res.points[a]);
    table = el("table", {}, el("tr", {}, el("th", { text: "Movie" }), el("th", { text: "Points" }), el("th", { text: "1st choices" })),
      ...ids.map((id) => el("tr", { class: id === res.winner ? "win" : "" }, el("td", { text: name(id) }),
        el("td", { class: "num", text: res.points[id] }), el("td", { class: "num", text: res.first[id] }))));
  } else {
    const ids = night.shortlist.map((m) => m.id);
    table = el("table", {},
      el("tr", {}, el("th", { text: "Movie" }), ...res.rounds.map((_, k) => el("th", { text: `Round ${k + 1}` }))),
      ...ids.map((id) => el("tr", {}, el("td", { class: id === res.winner ? "win" : "", text: name(id) }),
        ...res.rounds.map((r) => {
          const v = r.counts[id];
          return el("td", { class: "num" + (r.eliminated.includes(id) ? " out" : "") + (v != null && id === res.winner && r === res.rounds.at(-1) ? " win" : ""), text: v == null ? "" : v });
        }))));
  }
  $("rounds").replaceChildren(
    el("p", { class: "small", text: res.method === "borda"
      ? "Borda count: each ballot gives points by position (first choice gets the most). Highest total wins."
      : "Instant runoff: count everyone's first choice. If no movie has more than half, the last one is dropped and its voters move to their next choice. Repeat until one has a majority." }),
    table);
}

// ------------------------------------------------------------------ go
start();
