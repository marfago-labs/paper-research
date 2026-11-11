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
  questions: [
    { added: "2026-01-02", text: "Asked about <i>it</i>" },
    { added: "2026-01-02", text: "Again" },
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

test("gapLabel ignores object built-ins", () => {
  assert.equal(lib.gapLabel("missing"), "not in graph");
  assert.equal(lib.gapLabel("unextracted"), "only authors or citations in graph");
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
  assert.ok(!html.includes("<i>it</i>"), "questions must be escaped");
  assert.ok(!html.includes("javascript:"), "unsafe links must be dropped");
  assert.match(html, /href="https:\/\/arxiv.org\/abs\/2601.00001" target="_blank" rel="noopener noreferrer"/);
  assert.match(html, /Needs graph extraction \(2\)/);
  assert.match(html, /<span class="tag warn">not in graph<\/span>/);
  assert.match(html, /<span class="tag warn">only authors or citations in graph<\/span>/);
  assert.ok(!html.includes("[object Object]"));
  assert.match(html, /<details open><summary><strong>2026-01-03<\/strong> · 1 paper<\/summary>/);
  assert.match(html, /1 insight, 1 paper, 2 pins, 2 questions/);
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

test("buildRecap handles an empty research folder and a broken graph", () => {
  const empty = {
    papers: [],
    pins: [],
    insights: [],
    questions: [],
    graph: { entities: [], relations: [], error: "invalid <graph>" },
  };
  const { html, counts } = lib.buildRecap(empty);
  assert.deepEqual(counts, { papers: 0, insights: 0, pins: 0, graph: 0 });
  for (const text of ["Nothing recorded yet.", "No papers yet.", "No insights yet.", "No pins yet."])
    assert.ok(html.includes(text), text);
  assert.match(html, /The graph can't be shown: invalid &lt;graph&gt;/);
  assert.ok(!html.includes("Needs graph extraction"));
});
