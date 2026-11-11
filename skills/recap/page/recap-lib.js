// Pure functions for the recap page, with no DOM access, so they can be tested with
// `node --test skills/recap/page/recap-lib.test.js`. The page loads this file with a script tag.
// All text from the data is escaped before it is formatted.
(function (lib) {
  "use strict";

  const STATUS_ORDER = ["read", "skim", "unread-link", "archive", "done", "dropped"];
  const GRAPH_GAPS = new Map([
    ["missing", "not in graph"],
    ["unextracted", "only authors or citations in graph"],
  ]);
  const PAPER_ID = /ARXIV:\d{4}\.\d{4,5}|DOI:10\.\d{4,9}\/[^\s`,;)<&]*[^\s`,;)<&.]/g;
  const ENTITIES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  const INSIGHT_FIELDS = [
    ["insight", "Insight"],
    ["why", "Why"],
    ["sources", "Sources"],
    ["evidence", "Evidence"],
    ["users_view", "User's view"],
    ["tags", "Tags"],
    ["added", "Added"],
  ];

  function esc(text) {
    return String(text ?? "").replace(/[&<>"']/g, (c) => ENTITIES[c]);
  }

  function anchor(paperId) {
    return (
      "p-" +
      String(paperId)
        .replace(/[^A-Za-z0-9]+/g, "-")
        .replace(/^-+|-+$/g, "")
    );
  }

  // Escape, then render `code` and **bold**, and link paper IDs that are on the list.
  function inline(text, known) {
    let out = esc(text)
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    if (known) out = out.replace(PAPER_ID, (id) => (known.has(id) ? `<a href="#${anchor(id)}">${id}</a>` : id));
    return out;
  }

  function safeUrl(url) {
    return /^https?:\/\//.test(url || "") ? esc(url) : "";
  }

  function gapLabel(status) {
    return GRAPH_GAPS.get(status) || "";
  }

  // The part of the address after #, decoded. A malformed address gives "" instead of an error.
  function hashName(hash) {
    try {
      return decodeURIComponent(String(hash || "").slice(1));
    } catch {
      return "";
    }
  }

  function groupBy(items, key) {
    const groups = new Map();
    items.forEach((item) => {
      const value = key(item);
      if (!groups.has(value)) groups.set(value, []);
      groups.get(value).push(item);
    });
    return groups;
  }

  function renderActivity(data, known) {
    const items = [
      ...data.papers.map((p) => [
        p.added,
        "paper",
        `Added <a href="#${anchor(p.id)}">${esc(p.title)}</a> as <em>${esc(p.status)}</em>`,
      ]),
      ...data.pins.map((p) => [p.added, "pin", `Pinned ${esc(p.type)}: ${inline(p.title)}`]),
      ...data.insights.map((i) => [
        i.added,
        "insight",
        `Logged insight: <a href="#${esc(i.id)}">${inline(i.title)}</a>`,
      ]),
      ...data.questions.map((q) => [q.added, "question", inline(q.text, known)]),
    ];
    if (!items.length) return '<p class="empty">Nothing recorded yet.</p>';
    const days = groupBy(items, (item) => item[0] || "");
    const order = [...days.keys()].sort().reverse();
    return order
      .map((day, index) => {
        const rows = days.get(day);
        const kinds = [...groupBy(rows, (row) => row[1])]
          .sort()
          .map(([kind, list]) => `${list.length} ${kind}${list.length > 1 ? "s" : ""}`);
        const list = rows.map(([, kind, text]) => `<li><span class="tag">${kind}</span> ${text}</li>`).join("");
        return `<details${index === 0 ? " open" : ""}><summary><strong>${esc(day || "No date")}</strong> · ${kinds.join(", ")}</summary><ul>${list}</ul></details>`;
      })
      .join("");
  }

  function paperTitle(p) {
    const url = safeUrl(p.url);
    return url ? `<a href="${url}" target="_blank" rel="noopener noreferrer">${esc(p.title)}</a>` : esc(p.title);
  }

  function paperGap(p) {
    const label = gapLabel(p.graph);
    return label ? ` <span class="tag warn">${label}</span>` : "";
  }

  function linkedInsights(insights) {
    const items = insights
      .map((i) => `<li><span class="tag">insight</span> <a href="#${esc(i.id)}">${inline(i.title)}</a></li>`)
      .join("");
    return items ? `<ul class="linked">${items}</ul>` : "";
  }

  function renderPaper(p, insights) {
    const label = p.id.startsWith("http") ? "link" : p.id;
    return (
      `<article id="${anchor(p.id)}"><h3>${paperTitle(p)}</h3>` +
      `<p class="meta">${esc(label)} · added ${esc(p.added)} · rating ${esc(p.rating || "-")} · ${esc(p.tags)}</p>` +
      `<p>${inline(p.summary)}${paperGap(p)}</p>${linkedInsights(insights)}</article>`
    );
  }

  function renderPapers(data, insightsByPaper) {
    if (!data.papers.length) return '<p class="empty">No papers yet.</p>';
    const groups = groupBy(data.papers, (p) => p.status || "");
    const order = [...STATUS_ORDER, ...[...groups.keys()].filter((s) => !STATUS_ORDER.includes(s)).sort()];
    return order
      .filter((status) => groups.has(status))
      .map((status) => {
        const papers = [...groups.get(status)].sort((a, b) => (b.added || "").localeCompare(a.added || ""));
        const cards = papers.map((p) => renderPaper(p, insightsByPaper.get(p.id) || [])).join("");
        return `<h3 class="group">${esc(status || "no status")} (${papers.length})</h3>${cards}`;
      })
      .join("");
  }

  function renderInsights(data, known) {
    if (!data.insights.length) return '<p class="empty">No insights yet.</p>';
    return data.insights
      .map((i) => {
        const rows = INSIGHT_FIELDS.filter(([key]) => i[key])
          .map(([key, label]) => `<dt>${label}</dt><dd>${inline(i[key], known)}</dd>`)
          .join("");
        const kind = i.kind ? ` <span class="tag">${esc(i.kind)}</span>` : "";
        return `<article id="${esc(i.id)}"><h3>${inline(i.title)}${kind}</h3><dl>${rows}</dl></article>`;
      })
      .join("");
  }

  function renderPins(data, known) {
    if (!data.pins.length) return '<p class="empty">No pins yet.</p>';
    const groups = groupBy(data.pins, (p) => p.type);
    return [...groups.keys()]
      .sort()
      .map((type) => {
        const list = groups
          .get(type)
          .map((p) => `<li><strong>${inline(p.title)}</strong>: ${inline(p.body, known)}</li>`)
          .join("");
        return `<details><summary><strong>${esc(type)}</strong> (${groups.get(type).length})</summary><ul>${list}</ul></details>`;
      })
      .join("");
  }

  // The HTML for the four recap views, and the counts shown in the tabs.
  function buildRecap(data) {
    const known = new Set(data.papers.map((p) => p.id));
    const insightsByPaper = new Map();
    data.insights.forEach((i) =>
      i.papers.forEach((id) => {
        if (!insightsByPaper.has(id)) insightsByPaper.set(id, []);
        insightsByPaper.get(id).push(i);
      }),
    );
    const stats = [
      [data.papers.length, "papers", "papers"],
      [data.papers.filter((p) => p.status === "read").length, "to read", "papers"],
      [data.insights.length, "insights", "insights"],
      [data.pins.length, "pins", "pins"],
      [data.questions.length, "questions", "activity"],
      [data.graph.entities.length, "graph entities", "graph"],
    ]
      .map(([n, label, tab]) => `<a class="stat" href="#${tab}"><b>${n}</b><span>${label}</span></a>`)
      .join("");
    const graphNote = data.graph.error
      ? `<p class="warning">The graph can't be shown: ${esc(data.graph.error)}</p>`
      : "";
    const waiting = data.papers.filter((p) => gapLabel(p.graph));
    const gaps = waiting.length
      ? `<div class="gaps"><h3>Needs graph extraction (${waiting.length})</h3><ul>` +
        waiting
          .map(
            (p) =>
              `<li><a href="#${anchor(p.id)}">${esc(p.title)}</a> <span class="tag warn">${gapLabel(p.graph)}</span></li>`,
          )
          .join("") +
        '</ul><p class="meta">Ask Claude to extract these into the graph, or discuss them with /read.</p></div>'
      : "";
    const view = (id, title, body) =>
      `<div class="recap view" data-view="${id}" id="${id}" hidden><h2>${title}</h2>${body}</div>`;
    return {
      html:
        view(
          "activity",
          "Activity",
          `<div class="stats">${stats}</div>${graphNote}${gaps}<section>${renderActivity(data, known)}</section>`,
        ) +
        view("papers", "Papers", renderPapers(data, insightsByPaper)) +
        view("insights", "Insights", renderInsights(data, known)) +
        view("pins", "Pins", renderPins(data, known)),
      counts: {
        papers: data.papers.length,
        insights: data.insights.length,
        pins: data.pins.length,
        graph: data.graph.entities.length,
      },
    };
  }

  Object.assign(lib, { esc, anchor, inline, safeUrl, gapLabel, hashName, groupBy, buildRecap });
})(typeof module === "object" && module.exports ? module.exports : (window.RecapLib = {}));
