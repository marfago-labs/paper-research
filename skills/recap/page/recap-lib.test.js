// Tests for recap-lib.js. Run: node --test skills/recap/page/recap-lib.test.js
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const lib = require("./recap-lib.js");

const DATA = {
  generated: "2026-01-04 10:00",
  papers: [
    {
      added: "2026-01-02",
      title: "A <b>bold</b> paper",
      id: "ARXIV:2601.00001",
      status: "read",
      rating: "4",
      tags: "agents",
      summary: "Uses `code` and **bold** <script>x</script>.",
      url: "https://arxiv.org/abs/2601.00001",
      graph: "extracted",
    },
    {
      added: "",
      title: "Undated read",
      id: "ARXIV:2512.00002",
      status: "read",
      tags: "",
      summary: "",
      graph: "extracted",
    },
    {
      added: "2025-12-31",
      title: "Earlier read",
      id: "ARXIV:2512.00001",
      status: "read",
      tags: "",
      summary: "",
      graph: "extracted",
    },
    {
      added: "2026-01-01",
      title: "Old",
      id: "DOI:10.1234/xyz",
      status: "archive",
      rating: "",
      tags: "",
      summary: "",
      url: "javascript:alert(1)",
      graph: "missing",
    },
    {
      added: "",
      title: "Odd",
      id: "https://example.com/post",
      status: "weird",
      tags: "",
      summary: "",
      url: "",
      graph: "unextracted",
    },
    { added: "2026-01-03", title: "No status", id: "local", status: "", tags: "", summary: "", graph: "__proto__" },
  ],
  pins: [
    { type: "tool", title: "T", body: "From ARXIV:2601.00001 and ARXIV:2699.00001.", added: "2026-01-02" },
    { type: "dataset", title: "D", body: "Data.", added: "2026-01-02" },
  ],
  insights: [
    {
      title: "First",
      id: "insight:first",
      kind: "practice",
      insight: "Do it.",
      sources: "`ARXIV:2601.00001`",
      users_view: "Agrees.",
      added: "2026-01-02",
      papers: ["ARXIV:2601.00001"],
    },
    { title: "Second", id: "insight:second", kind: "", papers: [] },
  ],
  facts: [
    { added: "2026-01-02", type: "question", text: "Asked about <i>it</i>" },
    { added: "2026-01-02", type: "interest", text: "Again" },
    { added: "2026-01-02", type: "<b>odd</b>", text: "Typed oddly" },
  ],
  graph: { entities: [{ id: "paper:x" }], relations: [], error: "" },
};

test("the page gets the functions as window.RecapLib", () => {
  const vm = require("node:vm");
  const file = require.resolve("./recap-lib.js");
  const source = require("node:fs").readFileSync(file, "utf8");
  for (const context of [{ window: {} }, { window: {}, module: { exports: null } }]) {
    vm.runInNewContext(source, context, { filename: file });
    assert.equal(typeof context.window.RecapLib.buildRecap, "function");
  }
});

test("esc escapes the five HTML characters and handles empty values", () => {
  assert.equal(lib.esc(`<a href="x">'&'</a>`), "&lt;a href=&quot;x&quot;&gt;&#39;&amp;&#39;&lt;/a&gt;");
  assert.equal(lib.esc(null), "");
  assert.equal(lib.esc(undefined), "");
  assert.equal(lib.esc(5), "5");
});

test("anchor makes a safe id", () => {
  assert.equal(lib.anchor("ARXIV:2601.00001"), "p-ARXIV-2601-00001");
  assert.equal(lib.anchor("<https://x.y/z>"), "p-https-x-y-z");
});

test("inline formats after escaping and links only known papers", () => {
  assert.equal(lib.inline("<b> `c` **s**"), "&lt;b&gt; <code>c</code> <strong>s</strong>");
  const out = lib.inline("ARXIV:2601.00001 and ARXIV:2699.00001.", new Set(["ARXIV:2601.00001"]));
  assert.equal(out, '<a href="#p-ARXIV-2601-00001">ARXIV:2601.00001</a> and ARXIV:2699.00001.');
});

test("safeUrl only allows http and https", () => {
  assert.equal(lib.safeUrl("https://a.b/?q=1&r=2"), "https://a.b/?q=1&amp;r=2");
  assert.equal(lib.safeUrl("http://a.b"), "http://a.b");
  for (const bad of ["javascript:alert(1)", "data:text/html,x", "", undefined]) assert.equal(lib.safeUrl(bad), "");
});

test("evidenceClass marks every link that isn't verified", () => {
  assert.equal(lib.evidenceClass("verified"), "evidence");
  for (const status of ["reported", "inferred", "", undefined])
    assert.equal(lib.evidenceClass(status), "evidence weaker");
});

test("needsExtraction lists papers missing from the graph, and finished papers with nothing extracted", () => {
  const paper = (status, graph) => ({ status, graph });
  assert.equal(lib.needsExtraction(paper("read", "missing")), true);
  assert.equal(lib.needsExtraction(paper("done", "unextracted")), true);
  assert.equal(lib.needsExtraction(paper("partial", "unextracted")), true);
  for (const status of ["read", "skim", "archive", "dropped", "unread-link", ""])
    assert.equal(lib.needsExtraction(paper(status, "unextracted")), false, status);
  assert.equal(lib.needsExtraction(paper("done", "extracted")), false);
  assert.equal(lib.needsExtraction(paper("done", undefined)), false);
});

test("staleStatus finds papers still to read or skim that already had things extracted", () => {
  const paper = (status, graph) => ({ status, graph });
  for (const status of ["read", "skim"]) {
    assert.equal(lib.staleStatus(paper(status, "extracted")), true, status);
    for (const graph of ["unextracted", "missing", undefined])
      assert.equal(lib.staleStatus(paper(status, graph)), false, `${status} ${graph}`);
  }
  for (const status of ["partial", "done", "archive", "dropped", "unread-link", ""])
    assert.equal(lib.staleStatus(paper(status, "extracted")), false, status);
});

test("the Activity tab counts papers to read, to skim, and read in part, and lists out-of-date statuses", () => {
  const paper = (id, status, graph) => ({ id, title: id, status, graph, tags: "", summary: "" });
  const data = {
    papers: [
      paper("a", "read", "extracted"),
      paper("b", "skim", "unextracted"),
      paper("c", "skim", "extracted"),
      paper("d", "partial", "unextracted"),
      paper("e", "partial", "extracted"),
      paper("f", "partial", "extracted"),
      paper("g", "PARTIAL", "extracted"), // a status counts only as written in the template
      paper("h", "done", "extracted"),
    ],
    pins: [],
    insights: [],
    facts: [],
    graph: { entities: [], relations: [] },
  };
  const { html } = lib.buildRecap(data);
  assert.match(html, /<b>1<\/b><span>to read<\/span>/);
  assert.match(html, /<b>2<\/b><span>to skim<\/span>/);
  assert.match(html, /<b>3<\/b><span>read in part<\/span>/);
  assert.match(html, /<b>8<\/b><span>papers<\/span>/);
  assert.match(html, /Needs graph extraction \(1\)<\/h3><ul><li><a href="#p-d">d<\/a>/);
  assert.match(
    html,
    /Status out of date \(2\)<\/h3><ul><li><a href="#p-a">a<\/a> <span class="tag warn">extracted, but still to read<\/span>/,
  );
  assert.match(html, /<li><a href="#p-c">c<\/a> <span class="tag warn">extracted, but still to skim<\/span>/);
  assert.match(html, /set each to done, or to partial if it was read only in part/);
});

test("a paper card shows the graph gap only when the paper needs extraction", () => {
  const card = (status, graph) =>
    lib.renderPaperList({ insights: [], papers: [{ id: "x", title: "X", status, graph }] }, "status");
  assert.match(card("done", "unextracted"), /<span class="tag warn">nothing extracted yet<\/span>/);
  assert.match(card("read", "missing"), /<span class="tag warn">not in graph<\/span>/);
  assert.ok(!card("read", "unextracted").includes("tag warn"));
  assert.match(card("skim", "extracted"), /<span class="tag warn">extracted, but still to skim<\/span>/);
});

const EMPTY = { pins: [], insights: [], facts: [], graph: { entities: [], relations: [] } };
const row = (id, status, graph, title = id) => ({ id, title, status, graph, tags: "", summary: "" });

test("a status or graph state the template doesn't list never breaks the counts or the lists", () => {
  const odd = [
    undefined,
    null,
    "",
    " partial",
    "PARTIAL",
    "__proto__",
    "constructor",
    "toString",
    5,
    ["partial"],
    { x: 1 },
  ];
  odd.push("<script>alert(1)</script>", "partial\u0000", "x".repeat(10000));
  for (const status of odd) {
    for (const graph of ["extracted", "unextracted", "missing", undefined, null, "__proto__", 7]) {
      const paper = row("a", status, graph);
      assert.equal(lib.staleStatus(paper), false, `${String(status).slice(0, 12)} ${graph}`);
      assert.equal(lib.needsExtraction(paper), graph === "missing");
    }
    const { html } = lib.buildRecap({ ...EMPTY, papers: [row("a", status, "extracted")] });
    assert.ok(!html.includes("<script>"), "a status must be escaped");
    assert.match(html, /<b>0<\/b><span>read in part<\/span>/);
  }
});

test("titles and ids in the lists of papers to fix are escaped, and a row with only a status doesn't break them", () => {
  const hostile = row('ARXIV:"><script>x</script>', "skim", "extracted", "<img src=x onerror=alert(1)>");
  // recap.py always gives a row an id, an empty one if the table has no ID column; the other fields can be missing.
  const sparse = { id: "", status: "read", graph: "extracted" };
  const { html } = lib.buildRecap({ ...EMPTY, papers: [hostile, sparse] });
  assert.ok(!html.includes("<img"), "a title must be escaped");
  assert.ok(!html.includes("<script>x"), "an id must be escaped");
  assert.match(html, /Status out of date \(2\)/);
  for (const [, href] of html.matchAll(/href="(#p-[^"]*)"/g)) assert.match(href, /^#p-[A-Za-z0-9-]*$/);
});

test("each paper is counted once as to read, to skim, or read in part, and never twice", () => {
  const statuses = ["read", "skim", "partial", "done", "archive", "dropped", "unread-link", ""];
  const papers = Array.from({ length: 200 }, (_, n) => row(`p${n}`, statuses[n % statuses.length], "extracted"));
  const { html } = lib.buildRecap({ ...EMPTY, papers });
  const count = (label) => Number(new RegExp(`<b>(\\d+)</b><span>${label}</span>`).exec(html)[1]);
  assert.deepEqual([count("papers"), count("to read"), count("to skim"), count("read in part")], [200, 25, 25, 25]);
});

test("gapLabel ignores object built-ins", () => {
  assert.equal(lib.gapLabel("missing"), "not in graph");
  assert.equal(lib.gapLabel("unextracted"), "nothing extracted yet");
  for (const other of ["extracted", "__proto__", "constructor", "toString", undefined])
    assert.equal(lib.gapLabel(other), "");
});

test("hashName decodes and survives malformed addresses", () => {
  assert.equal(lib.hashName("#insight%3Afirst"), "insight:first");
  assert.equal(lib.hashName("#%E0"), "");
  assert.equal(lib.hashName(""), "");
  assert.equal(lib.hashName(undefined), "");
});

test("groupBy keeps order within groups", () => {
  const groups = lib.groupBy([1, 2, 3, 4], (n) => n % 2);
  assert.deepEqual(
    [...groups],
    [
      [1, [1, 3]],
      [0, [2, 4]],
    ],
  );
});

test("buildRecap renders every view with escaped text", () => {
  const { html, counts } = lib.buildRecap(DATA);
  assert.deepEqual(counts, { papers: 6, insights: 2, pins: 2, graph: 1 });
  for (const view of ["activity", "papers", "insights", "pins"])
    assert.match(html, new RegExp(`data-view="${view}" id="${view}" hidden`));
  assert.ok(!html.includes("<script>"), "paper text must be escaped");
  assert.ok(!html.includes("<b>bold</b>"), "titles must be escaped");
  assert.ok(!html.includes("<i>it</i>"), "facts must be escaped");
  assert.ok(!html.includes("<b>odd</b>"), "types must be escaped");
  assert.ok(!html.includes("javascript:"), "unsafe links must be dropped");
  assert.match(html, /href="https:\/\/arxiv.org\/abs\/2601.00001" target="_blank" rel="noopener noreferrer"/);
  assert.match(html, /Needs graph extraction \(1\)/);
  assert.match(html, /<span class="tag warn">not in graph<\/span>/);
  assert.ok(!html.includes("nothing extracted yet"), "a paper nobody has finished isn't due for extraction");
  assert.ok(!html.includes("[object Object]"));
  assert.match(html, /<details open><summary><strong>2026-01-03<\/strong> · 1 paper<\/summary>/);
  assert.match(html, /1 &lt;b&gt;odd&lt;\/b&gt;, 1 insight, 1 interest, 1 paper, 2 pins, 1 question/);
  assert.match(html, /<strong>No date<\/strong>/);
  assert.match(html, /<h3 class="group">read \(3\)<\/h3>/);
  assert.ok(html.indexOf("A &lt;b&gt;bold") < html.indexOf("Earlier read"), "newest first");
  assert.match(html, /<h3 class="group">weird \(1\)<\/h3>/);
  assert.match(html, /<h3 class="group">no status \(1\)<\/h3>/);
  assert.ok(html.indexOf("archive (1)") < html.indexOf("no status (1)"));
  assert.match(html, /<p class="meta">link · added/);
  assert.match(html, /rating -/);
  assert.match(html, /<ul class="linked"><li><span class="tag">insight<\/span> <a href="#insight:first">First<\/a>/);
  assert.match(html, /<h3>First <span class="tag">practice<\/span><\/h3>/);
  assert.match(html, /<h3>Second<\/h3><dl><\/dl>/);
  assert.match(html, /<dt>User's view<\/dt><dd>Agrees.<\/dd>/);
  assert.match(html, /<code><a href="#p-ARXIV-2601-00001">ARXIV:2601.00001<\/a><\/code>/);
  assert.match(html, /<summary><strong>dataset<\/strong> \(1\)<\/summary>/);
  assert.ok(html.indexOf("<strong>dataset</strong>") < html.indexOf("<strong>tool</strong>"));
});

test("papers show their standing and their place in the collection", () => {
  const { html } = lib.buildRecap({
    ...DATA,
    papers: [
      {
        ...DATA.papers[0],
        standing: { citations: 1, influential: 1, venue: "<NeurIPS>", year: 2025, checked: "2026-01-03" },
        collection: { cited_by: 2, insights: 1, pins: 0 },
      },
      { ...DATA.papers[2], standing: { citations: 0, year: 2026, checked: "2026-01-03" } },
      { ...DATA.papers[1], standing: { checked: "2026-01-04" } },
      DATA.papers[3],
    ],
  });
  assert.match(html, /<p class="meta">no citation data · checked 2026-01-04<\/p>/);
  assert.ok(!html.includes("undefined"), "a missing count must not be printed");
  assert.match(
    html,
    /1 citation \(1 influential\) · &lt;NeurIPS&gt; · 2025 · checked 2026-01-03 · in your collection: cited by 2 of your papers, 1 insight</,
  );
  assert.match(html, /0 citations · 2026 · checked 2026-01-03 <span class="tag">new: too early to judge<\/span><\/p>/);
  assert.match(html, /<p class="meta">citations not checked yet<\/p>/);
  assert.match(html, /<select id="paper-order" aria-label="Sort papers"><option value="status">by reading status/);
  assert.ok(!lib.buildRecap({ ...DATA, papers: [] }).html.includes("paper-order"));
});

test("renderPaperList sorts by citations, citations per year, or the collection", () => {
  const paper = (id, added, standing, collection) => ({ id, title: id, added, status: "read", standing, collection });
  const data = {
    generated: "2026-06-01 10:00",
    insights: [],
    papers: [
      paper("old", "2026-01-01", { citations: 100, year: 2016, checked: "x" }, { cited_by: 1 }),
      paper("recent", "2026-01-02", { citations: 30, year: 2025, checked: "x" }, { insights: 2, pins: 2 }),
      paper("none", "2026-01-03", undefined, undefined),
      paper("tied", "2026-01-04", undefined, { cited_by: 1 }),
      // Semantic Scholar doesn't know this one, and the other has counts but no year to divide them by.
      paper("unknown", "2026-01-05", { checked: "x" }, undefined),
      paper("noyear", "2026-01-06", { citations: 500, checked: "x" }, undefined),
    ],
  };
  const order = (name, source = data) =>
    [...lib.renderPaperList(source, name).matchAll(/<article id="p-(\w+)"/g)].map((m) => m[1]);
  assert.deepEqual(order("cited"), ["noyear", "old", "recent", "unknown", "tied", "none"]);
  assert.deepEqual(order("per-year"), ["recent", "old", "noyear", "unknown", "tied", "none"]);
  assert.deepEqual(order("collection"), ["recent", "tied", "old", "noyear", "unknown", "none"]);
  assert.deepEqual(order("status"), ["noyear", "unknown", "tied", "none", "recent", "old"]);
  assert.deepEqual(order("toString"), order("status"));
  assert.deepEqual(order("per-year", { ...data, generated: undefined }), [
    "old",
    "recent",
    "noyear",
    "unknown",
    "tied",
    "none",
  ]);
  assert.equal(lib.renderPaperList({ ...data, papers: [] }, "cited"), '<p class="empty">No papers yet.</p>');
  const noDates = { ...data, papers: [paper("first"), paper("second", "2026-01-01"), paper("third")] };
  assert.match(lib.renderPaperList(noDates, "cited"), /p-second[\s\S]*p-first[\s\S]*p-third/);
});

test("buildRecap handles an empty research folder and a broken graph", () => {
  const empty = {
    papers: [],
    pins: [],
    insights: [],
    facts: [],
    graph: { entities: [], relations: [], error: "invalid <graph>" },
  };
  const { html, counts } = lib.buildRecap(empty);
  assert.deepEqual(counts, { papers: 0, insights: 0, pins: 0, graph: 0 });
  for (const text of ["Nothing recorded yet.", "No papers yet.", "No insights yet.", "No pins yet."])
    assert.ok(html.includes(text), text);
  assert.match(html, /The graph can't be shown: invalid &lt;graph&gt;/);
  assert.ok(!html.includes("Needs graph extraction"));
  assert.ok(!html.includes("Status out of date"));
});
