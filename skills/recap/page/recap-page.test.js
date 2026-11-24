// Tests for the wiring in recap.html: its inline script runs against a stub page, with the real
// library and sample data. Run: node --test skills/recap/page/recap-page.test.js
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const HTML = fs.readFileSync(path.join(__dirname, "recap.html"), "utf8");
const LIB = fs.readFileSync(path.join(__dirname, "recap-lib.js"), "utf8");
const DATA = {
  generated: "2026-01-04 10:00",
  papers: [
    {
      added: "2026-01-02",
      title: "A paper",
      id: "ARXIV:2601.00001",
      status: "read",
      rating: "",
      tags: "",
      summary: "",
      url: "",
      graph: "extracted",
    },
  ],
  pins: [],
  insights: [],
  facts: [],
  graph: { entities: [{ id: "paper:x", type: "paper", name: "X", aliases: [] }], relations: [], error: "" },
};

function inlineScript() {
  const start = HTML.lastIndexOf("<script>");
  const end = HTML.lastIndexOf("</script>");
  assert.ok(start !== -1 && end > start, "the page needs an inline script");
  return HTML.slice(start + "<script>".length, end);
}

// A page made of stub elements, created on demand by id.
function stubPage(hash, extra = {}) {
  const elements = new Map();
  const listeners = {};
  const toggled = [];
  function element(id) {
    if (!elements.has(id)) {
      elements.set(id, {
        id,
        innerHTML: "",
        textContent: "",
        hidden: false,
        scrolled: false,
        dataset: { view: id === "graph-view" ? "graph" : id },
        classList: {
          toggle(name, on) {
            toggled.push([id, name, on]);
          },
        },
        closest() {
          return this;
        },
        scrollIntoView() {
          this.scrolled = true;
        },
        value: "0",
        append() {},
        addEventListener() {},
      });
    }
    return elements.get(id);
  }
  const views = ["activity", "papers", "insights", "pins", "graph-view"].map(element);
  const tabs = ["activity", "papers", "graph"].map((name) => ({
    dataset: { tab: name },
    classList: {
      toggle(cls, on) {
        toggled.push([name, cls, on]);
      },
    },
  }));
  const scrolls = [];
  const context = {
    window: {
      addEventListener(type, fn) {
        listeners[type] = fn;
      },
      scrollTo(...args) {
        scrolls.push(args);
      },
    },
    document: {
      getElementById: (id) => (id === "no-such-thing" ? null : element(id)),
      querySelectorAll: (selector) => (selector === "[data-view]" ? views : tabs),
      createElement: () => ({ className: "", textContent: "", style: {}, append() {}, addEventListener() {} }),
      createTextNode: (text) => ({ textContent: text }),
    },
    location: { hash },
    getComputedStyle: () => ({ getPropertyValue: () => "#000" }),
    console,
    ...extra,
  };
  context.window.window = context.window;
  return { context, element, listeners, toggled, scrolls, views };
}

function loadPage(hash, options = {}) {
  const { data, withLibrary, withCytoscape, cytoscape } = {
    data: DATA,
    withLibrary: true,
    withCytoscape: false,
    ...options,
  };
  const stub = withCytoscape ? { cytoscape: () => ({ resize() {} }) } : {};
  const page = stubPage(hash, cytoscape ? { cytoscape } : stub);
  vm.createContext(page.context);
  if (withLibrary) vm.runInContext(LIB, page.context, { filename: "recap-lib.js" });
  page.context.RecapLib = page.context.window.RecapLib;
  page.context.RECAP_DATA = data;
  const script = inlineScript().replace("window.RecapLib", "RecapLib").replace("window.RECAP_DATA", "RECAP_DATA");
  vm.runInContext(script, page.context, { filename: "recap.html" });
  return page;
}

test("the page loads its scripts from its own folder, in the right order", () => {
  const sources = [...HTML.matchAll(/<script src="([^"]+)"/g)].map((m) => m[1]);
  assert.deepEqual(sources, ["cytoscape-3.30.4.min.js", "recap-lib.js", "recap-data.js"]);
});

test("the inline script is valid JavaScript", () => {
  assert.doesNotThrow(() => new vm.Script(inlineScript(), { filename: "recap.html" }));
});

test("the recap fills the tab counts and the views, and shows the first view", () => {
  const page = loadPage("");
  assert.equal(page.element("n-papers").textContent, 1);
  assert.equal(page.element("n-graph").textContent, 1);
  assert.equal(page.element("generated").textContent, "Data from 2026-01-04 10:00");
  assert.match(page.element("recap-views").innerHTML, /id="papers"/);
  assert.equal(page.element("activity").hidden, false);
  assert.equal(page.element("papers").hidden, true);
  assert.deepEqual(page.scrolls.at(-1), [0, 0]);
});

test("an address picks the view, and scrolls to something inside a view", () => {
  const page = loadPage("#papers");
  assert.equal(page.element("papers").hidden, false);
  assert.equal(page.element("activity").hidden, true);
  const paper = loadPage("#p-ARXIV-2601-00001");
  assert.equal(paper.element("p-ARXIV-2601-00001").scrolled, false, "the view itself is not scrolled to");
});

test("an unknown or malformed address shows the first view", () => {
  for (const hash of ["#no-such-thing", "#%E0"]) {
    const page = loadPage(hash);
    assert.equal(page.element("activity").hidden, false, hash);
  }
});

test("changing the address switches views", () => {
  const page = loadPage("");
  page.context.location.hash = "#pins";
  page.listeners.hashchange();
  assert.equal(page.element("pins").hidden, false);
  assert.equal(page.element("activity").hidden, true);
});

test("without data the page says how to get it", () => {
  const page = loadPage("", { data: null });
  assert.match(page.element("recap-views").innerHTML, /No data found/);
});

test("the graph tab says so when the drawing library did not load", () => {
  const page = loadPage("#graph");
  assert.match(page.element("details").innerHTML, /drawing library didn/);
});

test("the graph tab reports a broken or empty graph instead of drawing", () => {
  const broken = loadPage("#graph", {
    data: { ...DATA, graph: { entities: [], relations: [], error: "bad <graph>" } },
    withCytoscape: true,
  });
  assert.match(broken.element("details").innerHTML, /can't be shown: bad &lt;graph&gt;/);
  const empty = loadPage("#graph", {
    data: { ...DATA, graph: { entities: [], relations: [], error: "" } },
    withCytoscape: true,
  });
  assert.match(empty.element("details").innerHTML, /No graph yet/);
});

// The graph is drawn by the real Cytoscape library, run without a screen, so styles and classes are the real ones.
const cytoscapeLib = require("./cytoscape-3.30.4.min.js");
const GRAPH = {
  entities: [
    { id: "paper:a", type: "paper", name: "Paper A", aliases: [] },
    { id: "concept:b", type: "concept", name: "Concept B", aliases: [] },
    { id: "method:c", type: "method", name: "Method C", aliases: [] },
    { id: "tool:d", type: "tool", name: "Tool D", aliases: [] },
  ],
  relations: [
    { from: "paper:a", rel: "proposes", to: "concept:b", source: "S", status: "verified" },
    { from: "paper:a", rel: "uses", to: "method:c", source: "S", status: "verified" },
  ],
  error: "",
};

// The page runs in its own realm, whose arrays and objects Cytoscape doesn't recognise: rebuild them in this one.
const inThisRealm = (value) => {
  if (Array.isArray(value)) return value.map(inThisRealm);
  if (value === null || typeof value !== "object") return value;
  return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, inThisRealm(item)]));
};

function drawGraph(t, graph = GRAPH) {
  const drawn = [];
  const cytoscape = (config) => {
    const { elements, style, minZoom, maxZoom } = inThisRealm(config);
    const cy = cytoscapeLib({ elements, style, minZoom, maxZoom, headless: true, styleEnabled: true });
    drawn.push(cy);
    return cy;
  };
  t.after(() => drawn.forEach((cy) => cy.destroy()));
  loadPage("#graph", { data: { ...DATA, graph }, cytoscape });
  return drawn[0];
}

const ids = (nodes) => nodes.map((node) => node.id()).sort();
const alwaysLabelled = (cy) => ids(cy.nodes().filter((node) => node.style("min-zoomed-font-size") === "0px"));

test("graph labels are drawn at 13px, and shown only where they would be at least 8px on screen", (t) => {
  const cy = drawGraph(t);
  assert.equal(cy.nodes().length, 4);
  for (const node of cy.nodes()) {
    assert.equal(node.style("font-size"), "13px", node.id());
    assert.equal(node.style("min-zoomed-font-size"), "8px", node.id());
  }
});

test("the selected entity and its neighbours keep their labels at any zoom, and no other does", (t) => {
  const cy = drawGraph(t);
  assert.deepEqual(alwaysLabelled(cy), [], "nothing is selected yet");
  cy.getElementById("paper:a").emit("tap");
  assert.deepEqual(ids(cy.nodes(".selected")), ["paper:a"]);
  assert.deepEqual(ids(cy.nodes(".near")), ["concept:b", "method:c"]);
  assert.deepEqual(alwaysLabelled(cy), ["concept:b", "method:c", "paper:a"]);
});

test("selecting another entity moves the labels with it, and an entity with no links has no neighbours", (t) => {
  const cy = drawGraph(t);
  cy.getElementById("paper:a").emit("tap");
  cy.getElementById("tool:d").emit("tap");
  assert.deepEqual([ids(cy.nodes(".selected")), ids(cy.nodes(".near"))], [["tool:d"], []]);
  assert.deepEqual(alwaysLabelled(cy), ["tool:d"]);
  cy.getElementById("concept:b").emit("tap");
  assert.deepEqual([ids(cy.nodes(".selected")), ids(cy.nodes(".near"))], [["concept:b"], ["paper:a"]]);
  assert.deepEqual(alwaysLabelled(cy), ["concept:b", "paper:a"]);
});

test("a graph with hostile names is drawn, and each label is the name as text", (t) => {
  const names = ["<img src=x onerror=alert(1)>", "__proto__", "x".repeat(5000), "‮evil​", 'A "quote" & <b>'];
  const entities = names.map((name, n) => ({ id: `concept:n${n}`, type: "concept", name, aliases: [] }));
  entities.push({ id: "paper:p", type: "paper", name: "P", aliases: ["<b>alias</b>"] }); // a paper shows its alias
  entities.push({ id: "tool:x", type: "tool", name: "No aliases key" }); // a record with no aliases at all
  const cy = drawGraph(t, { entities, relations: [], error: "" });
  assert.equal(cy.nodes().length, names.length + 2);
  names.forEach((name, n) => assert.equal(cy.getElementById(`concept:n${n}`).data("label"), name));
  assert.equal(cy.getElementById("paper:p").data("label"), "<b>alias</b>");
  cy.getElementById("concept:n0").emit("tap");
  assert.deepEqual(alwaysLabelled(cy), ["concept:n0"]);
});
