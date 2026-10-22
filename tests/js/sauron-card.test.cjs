/* SAUron card smoke tests — run with: node --test tests/js/sauron-card.test.cjs */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const registered = new Map();
class HTMLElement {
  attachShadow() {
    this.shadowRoot = {
      innerHTML: "",
      querySelector: () => null,
      querySelectorAll: () => [],
    };
  }
}
const context = {
  HTMLElement,
  customElements: {
    get: (name) => registered.get(name),
    define: (name, element) => registered.set(name, element),
  },
  window: {},
  Date,
};
vm.runInNewContext(
  fs.readFileSync(
    path.join(__dirname, "../../custom_components/sauron/www/sauron-card.js"),
    "utf8",
  ),
  context,
  { filename: "sauron-card.js" },
);
const Card = registered.get("sauron-card");

test("registers the Lovelace card and editor", () => {
  assert.equal(typeof Card, "function");
  assert.equal(typeof registered.get("sauron-card-editor"), "function");
});

test("Recorder Unix timestamps as strings produce correct October dates", () => {
  const card = new Card();
  card._stats = [
    { start: "1792540800", change: 0.05 },
    { start: "1792627200", change: 0.06 },
  ];
  const svg = card._chart();
  assert.match(svg, /2026|oct/i);
  assert.match(svg, /0[,.]05(?:0)? m³/);
  assert.match(svg, /0[,.]06(?:0)? m³/);
  assert.doesNotMatch(svg, /sept|juin|mars/i);
});

test("Recorder Unix timestamps as numbers produce the same dates", () => {
  const card = new Card();
  card._stats = [{ start: 1792627200, change: 0.06 }];
  assert.match(card._chart(), /oct/i);
});

test("Sections grid width adapts to detailed and compact modes", () => {
  const card = new Card();
  card.setConfig({ mode: "detailed" });
  assert.equal(card.getGridOptions().columns, 12);
  card.setConfig({ mode: "compact" });
  assert.equal(card.getGridOptions().columns, 4);
});

test("Recorder millisecond timestamps are not multiplied again", () => {
  const card = new Card();
  card._stats = [
    { start: 1792015200000, change: 0.09 },
    { start: 1792101600000, change: 0.75 },
  ];
  const svg = card._chart();
  assert.match(svg, /oct/i);
  assert.match(svg, /0[,.]75(?:0)? m³/);
  assert.doesNotMatch(svg, /sept|juin|mars/i);
});
