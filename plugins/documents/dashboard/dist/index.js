/* Documents Plugin — Dashboard component
   Uses the Hermes Plugin SDK (window.__HERMES_PLUGIN_SDK__) — no React import needed. */
(function () {
  "use strict";
  console.log("[documents] plugin script executing");
  try {
  var PLUGINS = window.__HERMES_PLUGINS__;
  if (!SDK) { console.error("[documents] Plugin SDK not available on window.__HERMES_PLUGIN_SDK__"); return; }
  if (!PLUGINS || !PLUGINS.register) { console.error("[documents] Plugin registry not available on window.__HERMES_PLUGINS__"); return; }
  console.log("[documents] SDK found, version:", SDK.sdkVersion);
  var React = SDK.React;
  var hooks = SDK.hooks;
  var useState = hooks.useState;
  var useEffect = hooks.useEffect;
  var useCallback = hooks.useCallback;
  var useMemo = hooks.useMemo;
  var C = SDK.components;
  var api = SDK.api;
  var fetchJSON = SDK.fetchJSON;
  var authedFetch = SDK.authedFetch;
  var Card = C.Card, CardHeader = C.CardHeader, CardTitle = C.CardTitle, CardContent = C.CardContent;
  var Badge = C.Badge, Button = C.Button, Input = C.Input, Label = C.Label;
  var Select = C.Select, SelectOption = C.SelectOption, Tabs = C.Tabs;
  var TabsList = C.TabsList, TabsTrigger = C.TabsTrigger, Separator = C.Separator;
  console.log("[documents] components:", Object.keys(C).join(","));

  var FORMATS = [
    { value: "pdf",  label: "PDF"  },
    { value: "docx", label: "Word" },
    { value: "html", label: "HTML" },
    { value: "md",   label: "Markdown" },
    { value: "csv",  label: "CSV" },
    { value: "xlsx", label: "Excel" }
  ];

  var TEMPLATES = [
    { value: "default",  label: "Default" },
    { value: "report",   label: "Report" },
    { value: "briefing", label: "Briefing" }
  ];

  var DEFAULT_MD = "# Hello\n\nWrite Markdown here, then pick a format and click **Generate**.\n\n## Section\n\n- bullet one\n- bullet two\n\n```js\nconsole.log('code blocks supported');\n```";

  /* ── Generate tab ───────────────────────────────────────── */
  function GenerateTab({ onCreated }) {
    var formatState = useState("pdf"); var fmt = formatState[0]; var setFmt = formatState[1];
    var tmplState = useState("default"); var tmpl = tmplState[0]; var setTmpl = tmplState[1];
    var titleState = useState(""); var title = titleState[0]; var setTitle = titleState[1];
    var contentState = useState(DEFAULT_MD); var content = contentState[0]; var setContent = contentState[1];
    var authorState = useState(""); var author = authorState[0]; var setAuthor = authorState[1];
    var busyState = useState(false); var busy = busyState[0]; var setBusy = busyState[1];
    var errState = useState(""); var err = errState[0]; var setErr = errState[1];
    var lastState = useState(null); var last = lastState[0]; var setLast = lastState[1];

    var submit = useCallback(function () {
      setErr(""); setBusy(true);
      var meta = {};
      if (author) meta.author = author;
      api.post("/plugins/documents/generate", {
        format: fmt, title: title || "Untitled", content: content,
        template: tmpl, metadata: meta
      })
        .then(function (r) { setLast(r.data || r); if (onCreated) onCreated(); })
        .catch(function (e) { setErr((e && e.message) || "generation failed"); })
        .finally(function () { setBusy(false); });
    }, [fmt, tmpl, title, content, author, onCreated]);

    return React.createElement("div", { className: "docs-tab" },
      React.createElement(Card, null,
        React.createElement(CardHeader, null,
          React.createElement(CardTitle, null, "Generate Document")
        ),
        React.createElement(CardContent, { className: "docs-form" },
          React.createElement("div", { className: "docs-row" },
            React.createElement("div", { className: "docs-field" },
              React.createElement(Label, null, "Format"),
              React.createElement(Select, { value: fmt, onValueChange: setFmt },
                FORMATS.map(function (f) {
                  return React.createElement(SelectOption, { key: f.value, value: f.value }, f.label);
                })
              )
            ),
            React.createElement("div", { className: "docs-field" },
              React.createElement(Label, null, "Template"),
              React.createElement(Select, { value: tmpl, onValueChange: setTmpl },
                TEMPLATES.map(function (t) {
                  return React.createElement(SelectOption, { key: t.value, value: t.value }, t.label);
                })
              )
            ),
            React.createElement("div", { className: "docs-field docs-field-grow" },
              React.createElement(Label, null, "Title"),
              React.createElement(Input, { value: title, onChange: function (e) { setTitle(e.target.value); }, placeholder: "My report" })
            )
          ),
          React.createElement("div", { className: "docs-field" },
            React.createElement(Label, null, "Author (optional)"),
            React.createElement(Input, { value: author, onChange: function (e) { setAuthor(e.target.value); }, placeholder: "Hermes" })
          ),
          React.createElement("div", { className: "docs-field" },
            React.createElement(Label, null, "Content (Markdown)"),
            React.createElement("textarea", {
              className: "docs-textarea",
              value: content,
              onChange: function (e) { setContent(e.target.value); },
              rows: 14
            })
          ),
          err ? React.createElement("div", { className: "docs-error" }, err) : null,
          React.createElement("div", { className: "docs-actions" },
            React.createElement(Button, { onClick: submit, disabled: busy },
              busy ? "Generating..." : "Generate " + fmt.toUpperCase()
            )
          )
        )
      ),
      last ? React.createElement(Card, { className: "docs-card-result" },
        React.createElement(CardContent, null,
          React.createElement("div", { className: "docs-result-row" },
            React.createElement("div", null,
              React.createElement("strong", null, last.title),
              React.createElement("div", { className: "docs-meta" },
                React.createElement(Badge, null, last.format),
                " ", humanSize(last.size), " · ",
                React.createElement("span", { className: "docs-time" }, formatTime(last.created_at))
              )
            ),
            React.createElement("div", { className: "docs-result-actions" },
              React.createElement(Button, {
                onClick: function () { window.open("/api/plugins/documents/" + last.id + "/download", "_blank"); }
              }, "Download"),
              React.createElement(Button, {
                onClick: function () { window.open("/api/plugins/documents/" + last.id + "/preview", "_blank"); },
                className: "docs-btn-secondary"
              }, "Preview")
            )
          )
        )
      ) : null
    );
  }

  /* ── Search tab ─────────────────────────────────────────── */
  function SearchTab() {
    var qState = useState(""); var q = qState[0]; var setQ = qState[1];
    var kState = useState(5); var topK = kState[0]; var setK = kState[1];
    var folderState = useState(""); var folder = folderState[0]; var setFolder = folderState[1];
    var busyState = useState(false); var busy = busyState[0]; var setBusy = busyState[1];
    var hitsState = useState([]); var hits = hitsState[0]; var setHits = hitsState[1];
    var errState = useState(""); var err = errState[0]; var setErr = errState[1];

    var run = useCallback(function () {
      if (!q.trim()) return;
      setBusy(true); setErr("");
      var body = { query: q, top_k: topK, with_citations: true };
      if (folder) body.folder = folder;
      api.post("/plugins/documents/search", body)
        .then(function (r) { setHits((r.data && r.data.hits) || r.hits || []); })
        .catch(function (e) { setErr((e && e.message) || "search failed"); setHits([]); })
        .finally(function () { setBusy(false); });
    }, [q, topK, folder]);

    return React.createElement("div", { className: "docs-tab" },
      React.createElement(Card, null,
        React.createElement(CardHeader, null, React.createElement(CardTitle, null, "RAG Search with Citations")),
        React.createElement(CardContent, { className: "docs-form" },
          React.createElement("div", { className: "docs-row" },
            React.createElement("div", { className: "docs-field docs-field-grow" },
              React.createElement(Label, null, "Query"),
              React.createElement(Input, {
                value: q, onChange: function (e) { setQ(e.target.value); },
                placeholder: "how to patch Hermes…",
                onKeyDown: function (e) { if (e.key === "Enter") run(); }
              })
            ),
            React.createElement("div", { className: "docs-field" },
              React.createElement(Label, null, "Top K"),
              React.createElement(Input, {
                type: "number", min: 1, max: 50, value: topK,
                onChange: function (e) { setK(parseInt(e.target.value, 10) || 5); }
              })
            ),
            React.createElement("div", { className: "docs-field" },
              React.createElement(Label, null, "Folder"),
              React.createElement(Input, {
                value: folder, onChange: function (e) { setFolder(e.target.value); },
                placeholder: "(any)"
              })
            ),
            React.createElement("div", { className: "docs-field docs-field-button" },
              React.createElement(Label, null, " "),
              React.createElement(Button, { onClick: run, disabled: busy }, busy ? "Searching…" : "Search")
            )
          ),
          err ? React.createElement("div", { className: "docs-error" }, err) : null
        )
      ),
      React.createElement("div", { className: "docs-hits" },
        hits.length === 0 && !busy ? React.createElement("div", { className: "docs-empty" },
          err ? "" : "Run a search to see results with paragraph citations."
        ) : null,
        hits.map(function (h, i) { return HitCard({ hit: h, key: i }); })
      )
    );
  }

  function HitCard({ hit }) {
    var c = hit.citation || {};
    var heading = (c.heading_path || []).join(" › ") || "(no heading)";
    return React.createElement(Card, { className: "docs-hit" },
      React.createElement(CardContent, null,
        React.createElement("div", { className: "docs-hit-header" },
          React.createElement("strong", null, hit.title || hit.source_path || "untitled"),
          React.createElement(Badge, { className: "docs-score" }, (hit.score || 0).toFixed(2))
        ),
        React.createElement("div", { className: "docs-hit-cite" },
          React.createElement("span", { className: "docs-cite-path" }, hit.source_path || ""),
          " › ",
          React.createElement("span", { className: "docs-cite-heading" }, heading),
          " › ¶ ",
          c.paragraph_index != null ? c.paragraph_index : "?"
        ),
        React.createElement("pre", { className: "docs-hit-text" }, hit.text || "")
      )
    );
  }

  /* ── Library tab ────────────────────────────────────────── */
  function LibraryTab() {
    var docsState = useState([]); var docs = docsState[0]; var setDocs = docsState[1];
    var spState = useState(""); var sp = spState[0]; var setSp = spState[1];
    var folderState = useState("default"); var folder = folderState[0]; var setFolder = folderState[1];
    var tagsState = useState(""); var tags = tagsState[0]; var setTags = tagsState[1];
    var contentState = useState(""); var content = contentState[0]; var setContent = contentState[1];
    var busyState = useState(false); var busy = busyState[0]; var setBusy = busyState[1];
    var msgState = useState(""); var msg = msgState[0]; var setMsg = msgState[1];

    var refresh = useCallback(function () {
      api.get("/plugins/documents?limit=50")
        .then(function (r) { setDocs((r.data && r.data.docs) || r.docs || []); })
        .catch(function () {});
    }, []);
    useEffect(function () { refresh(); }, [refresh]);

    var submit = useCallback(function () {
      if (!sp || !content) { setMsg("source_path and content are required"); return; }
      setBusy(true); setMsg("");
      var body = { source_path: sp, content: content, folder: folder };
      if (tags) body.tags = tags.split(",").map(function (s) { return s.trim(); }).filter(Boolean);
      api.post("/plugins/documents/index", body)
        .then(function (r) {
          setMsg("Indexed " + ((r.data && r.data.indexed) || r.indexed || 0) + " chunks");
          setContent("");
        })
        .catch(function (e) { setMsg("Error: " + ((e && e.message) || "index failed")); })
        .finally(function () { setBusy(false); });
    }, [sp, content, folder, tags]);

    return React.createElement("div", { className: "docs-tab" },
      React.createElement(Card, null,
        React.createElement(CardHeader, null, React.createElement(CardTitle, null, "Index Document for RAG")),
        React.createElement(CardContent, { className: "docs-form" },
          React.createElement("div", { className: "docs-field" },
            React.createElement(Label, null, "Source path"),
            React.createElement(Input, { value: sp, onChange: function (e) { setSp(e.target.value); }, placeholder: "~/notes/hermes.md" })
          ),
          React.createElement("div", { className: "docs-row" },
            React.createElement("div", { className: "docs-field" },
              React.createElement(Label, null, "Folder"),
              React.createElement(Input, { value: folder, onChange: function (e) { setFolder(e.target.value); } })
            ),
            React.createElement("div", { className: "docs-field docs-field-grow" },
              React.createElement(Label, null, "Tags (comma-separated)"),
              React.createElement(Input, { value: tags, onChange: function (e) { setTags(e.target.value); }, placeholder: "guide, hermes" })
            )
          ),
          React.createElement("div", { className: "docs-field" },
            React.createElement(Label, null, "Content (Markdown or plain text)"),
            React.createElement("textarea", {
              className: "docs-textarea",
              value: content,
              onChange: function (e) { setContent(e.target.value); },
              rows: 10
            })
          ),
          msg ? React.createElement("div", { className: "docs-msg" }, msg) : null,
          React.createElement("div", { className: "docs-actions" },
            React.createElement(Button, { onClick: submit, disabled: busy || !sp || !content },
              busy ? "Indexing…" : "Index for RAG"
            )
          )
        )
      ),
      React.createElement(Card, null,
        React.createElement(CardHeader, null,
          React.createElement(CardTitle, null, "Generated Documents"),
          React.createElement(Button, { onClick: refresh, className: "docs-btn-secondary" }, "Refresh")
        ),
        React.createElement(CardContent, null,
          docs.length === 0
            ? React.createElement("div", { className: "docs-empty" }, "No documents generated yet.")
            : React.createElement("div", { className: "docs-grid" },
                docs.map(function (d) {
                  return React.createElement("div", { key: d.id, className: "docs-grid-item" },
                    React.createElement("div", { className: "docs-grid-title" }, d.title || "(untitled)"),
                    React.createElement("div", { className: "docs-grid-meta" },
                      React.createElement(Badge, null, d.format),
                      " ", humanSize(d.size)
                    ),
                    React.createElement("div", { className: "docs-grid-time" }, formatTime(d.created_at)),
                    React.createElement("div", { className: "docs-grid-actions" },
                      React.createElement("a", { href: "/api/plugins/documents/" + d.id + "/download", target: "_blank", rel: "noreferrer" }, "Download"),
                      React.createElement("a", { href: "/api/plugins/documents/" + d.id + "/preview", target: "_blank", rel: "noreferrer" }, "Preview")
                    )
                  );
                })
              )
        )
      )
    );
  }

  /* ── Main component ─────────────────────────────────────── */
  function DocumentsApp() {
    var tabState = useState("generate"); var tab = tabState[0]; var setTab = tabState[1];
    var refreshTickState = useState(0); var tick = refreshTickState[0]; var setTick = refreshTickState[1];
    var onCreated = useCallback(function () { setTick(tick + 1); }, [tick]);

    return React.createElement("div", { className: "docs-root" },
      React.createElement("div", { className: "docs-header" },
        React.createElement("h2", null, "📄 Documents"),
        React.createElement("p", { className: "docs-subtitle" },
          "Generate documents in 6 formats · RAG search with paragraph citations"
        )
      ),
      React.createElement(Tabs, { value: tab, onValueChange: setTab },
        React.createElement(TabsList, null,
          React.createElement(TabsTrigger, { value: "generate" }, "Generate"),
          React.createElement(TabsTrigger, { value: "search" }, "Search"),
          React.createElement(TabsTrigger, { value: "library" }, "Library")
        ),
        tab === "generate" ? React.createElement(GenerateTab, { key: tick, onCreated: onCreated }) : null,
        tab === "search"   ? React.createElement(SearchTab,   { key: "s" }) : null,
        tab === "library"  ? React.createElement(LibraryTab,  { key: "l" }) : null
      )
    );
  }

  /* ── helpers ────────────────────────────────────────────── */
  function humanSize(n) {
    if (n == null) return "?";
    if (n < 1024) return n + " B";
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
    return (n / 1024 / 1024).toFixed(2) + " MB";
  }
  function formatTime(iso) {
    if (!iso) return "";
    try { var d = new Date(iso); return d.toLocaleString(); } catch (_e) { return iso; }
  }

  PLUGINS.register("documents", DocumentsApp);
  console.log("[documents] registered successfully");
  } catch (e) {
    console.error("[documents] plugin error:", e && e.message, e && e.stack);
  }
})();
