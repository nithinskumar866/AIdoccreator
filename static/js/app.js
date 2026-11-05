/* DocuMentor single-page interface. All text is placed with DOM text nodes, never as HTML,
   so nothing inside an uploaded document or an AI answer can run in the page. */
(function () {
  "use strict";

  const view = document.getElementById("view");
  const dialog = document.getElementById("dialog");
  const fileInput = document.getElementById("file-input");
  const state = { status: null, documents: [], navToken: 0 };

  // ---------- small helpers ----------
  function h(tag, props, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(props || {})) {
      if (value === undefined || value === null || value === false) continue;
      if (key === "class") node.className = value;
      else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
      else if (key in node && key !== "list" && key !== "form") node[key] = value;
      else node.setAttribute(key, value === true ? "" : value);
    }
    for (const child of children.flat(Infinity)) {
      if (child === undefined || child === null || child === false) continue;
      node.append(child.nodeType ? child : String(child));
    }
    return node;
  }

  function icon(name) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "icon");
    svg.setAttribute("aria-hidden", "true");
    const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
    use.setAttribute("href", "#i-" + name);
    svg.append(use);
    return svg;
  }

  async function api(path, options) {
    const opts = options || {};
    const init = { method: opts.method || "GET", headers: {} };
    if (opts.json !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(opts.json);
    } else if (opts.body) {
      init.body = opts.body;
    }
    let response;
    try {
      response = await fetch("/api" + path, init);
    } catch (error) {
      throw new Error("Couldn't reach DocuMentor. Is the app still running?");
    }
    let data = null;
    try { data = await response.json(); } catch (error) { /* handled below */ }
    if (!response.ok && !(opts.allowPartial && data)) {
      throw new Error((data && data.error) || "Something went wrong. Please try again.");
    }
    return data || {};
  }

  function toast(message, kind) {
    const node = h("div", { class: "toast" + (kind === "bad" ? " bad" : "") }, message);
    document.getElementById("toasts").append(node);
    setTimeout(() => node.remove(), kind === "bad" ? 8000 : 3800);
  }

  function failed(error) { toast(error.message || String(error), "bad"); }

  function stripNumber(text) { return text.replace(/^\s*(?:q(?:uestion)?\s*\.?\s*)?\d{1,3}\s*[.):|-]\s*(?=\S)/i, ""); }

  function plural(n, word) { return n + " " + word + (n === 1 ? "" : "s"); }

  function when(seconds) {
    return new Date(seconds * 1000).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
  }

  function size(doc) {
    const parts = [doc.kind.toUpperCase()];
    if (doc.pages) parts.push(plural(doc.pages, "page"));
    parts.push(doc.chars.toLocaleString() + " characters");
    return parts.join(" · ");
  }

  function confirmDialog(title, message, actionLabel) {
    return new Promise((resolve) => {
      const close = (value) => { dialog.close(); resolve(value); };
      dialog.replaceChildren(h("div", { class: "dialog-body" },
        h("h2", null, title), h("p", { class: "lead" }, message),
        h("div", { class: "dialog-actions" },
          h("button", { class: "btn", type: "button", onclick: () => close(false) }, "Cancel"),
          h("button", { class: "btn bad", type: "button", onclick: () => close(true) }, actionLabel))));
      dialog.oncancel = () => resolve(false);
      dialog.showModal();
    });
  }

  function page(title, lead, actions, narrow) {
    return h("div", { class: "page" + (narrow ? " narrow" : "") },
      h("header", { class: "page-head" },
        h("div", null, h("h1", null, title), lead && h("p", { class: "lead" }, lead)),
        actions && h("div", { class: "row" }, actions)));
  }

  function empty(iconName, text, action) {
    return h("div", { class: "empty" }, icon(iconName), h("p", null, text), action);
  }

  const ROLE_LABEL = { textbook: "Textbook", notes: "Notes", homework: "Homework" };
  const TYPE_LABEL = { homework_check: "Homework check", homework_generated: "New homework", notes_correction: "Notes review" };

  // ---------- safe Markdown (builds DOM nodes, never HTML) ----------
  function inline(text) {
    const out = [];
    const pattern = /(\*\*[^*]+\*\*|__[^_]+__|`[^`]+`|\*[^*\s][^*]*\*)/g;
    let last = 0, match;
    while ((match = pattern.exec(text))) {
      if (match.index > last) out.push(text.slice(last, match.index));
      const token = match[0];
      if (token.startsWith("**") || token.startsWith("__")) out.push(h("strong", null, token.slice(2, -2)));
      else if (token.startsWith("`")) out.push(h("code", null, token.slice(1, -1)));
      else out.push(h("em", null, token.slice(1, -1)));
      last = match.index + token.length;
    }
    if (last < text.length) out.push(text.slice(last));
    return out;
  }

  function markdown(source) {
    const root = h("div", { class: "md" });
    const lines = source.split("\n");
    const cells = (line) => line.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
    let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      if (!line.trim() || /^\s*([-*_])\1{2,}\s*$/.test(line)) { i += 1; continue; }
      if (line.startsWith("```")) {
        const code = [];
        i += 1;
        while (i < lines.length && !lines[i].startsWith("```")) code.push(lines[i++]);
        i += 1;
        root.append(h("pre", null, h("code", null, code.join("\n"))));
        continue;
      }
      const heading = line.match(/^#{1,6}\s+(.*)$/);
      if (heading) { root.append(h("h3", null, inline(heading[1]))); i += 1; continue; }
      if (line.trim().startsWith("|") && lines[i + 1] && /^\s*\|?[\s:|-]+\|?\s*$/.test(lines[i + 1])) {
        const head = h("tr", null, cells(line).map((c) => h("th", null, inline(c))));
        const rows = [];
        i += 2;
        while (i < lines.length && lines[i].trim().startsWith("|")) {
          rows.push(h("tr", null, cells(lines[i]).map((c) => h("td", null, inline(c)))));
          i += 1;
        }
        root.append(h("table", null, h("thead", null, head), h("tbody", null, rows)));
        continue;
      }
      const isBullet = /^\s*[-*•]\s+/, isNumber = /^\s*\d+[.)]\s+/;
      if (isBullet.test(line) || isNumber.test(line)) {
        const test = isBullet.test(line) ? isBullet : isNumber;
        const list = h(test === isBullet ? "ul" : "ol");
        while (i < lines.length && test.test(lines[i])) {
          list.append(h("li", null, inline(lines[i].replace(test, ""))));
          i += 1;
        }
        root.append(list);
        continue;
      }
      const para = [line];
      i += 1;
      while (i < lines.length && lines[i].trim() && !/^(#{1,6}\s|```|\s*[-*•]\s|\s*\d+[.)]\s|\s*\|)/.test(lines[i])) para.push(lines[i++]);
      root.append(h("p", null, inline(para.join(" "))));
    }
    return root;
  }

  // ---------- data and jobs ----------
  async function loadDocuments() {
    state.documents = (await api("/documents")).documents;
    return state.documents;
  }

  function uploadFiles(files, role) {
    const form = new FormData();
    for (const file of files) form.append("files", file);
    if (role) form.append("role", role);
    return api("/documents", { method: "POST", body: form, allowPartial: true }).then((data) => {
      for (const item of data.failed || []) toast(item.name + ": " + item.error, "bad");
      const added = data.uploaded || [];
      if (added.length) {
        const fresh = added.filter((d) => !d.duplicate).length;
        toast(fresh === added.length ? "Added " + plural(added.length, "document") : "Already in your library, so it was reused");
      }
      return added;
    });
  }

  function chooseFiles(multiple) {
    return new Promise((resolve) => {
      fileInput.multiple = multiple;
      fileInput.value = "";
      fileInput.onchange = () => resolve([...fileInput.files]);
      fileInput.oncancel = () => resolve([]);
      fileInput.click();
    });
  }

  function progressPanel() {
    const fill = h("i");
    const text = h("span", null, "Starting");
    const node = h("div", { class: "card progress", role: "status", "aria-live": "polite" },
      h("div", { class: "typing" }, h("span", { class: "spinner" }), text),
      h("div", { class: "bar" }, fill));
    return { node, update(job) { fill.style.width = job.progress + "%"; text.textContent = job.message; } };
  }

  async function runJob(type, params, onProgress, path) {
    const start = await api(path || "/jobs/" + type, { method: "POST", json: params });
    for (;;) {
      await new Promise((resolve) => setTimeout(resolve, 700));
      const job = await api("/jobs/" + start.job_id);
      if (onProgress) onProgress(job);
      if (job.status === "done") return job.output;
      if (job.status === "failed") throw new Error(job.error || "That task failed. Please try again.");
    }
  }

  async function refreshStatus() {
    try {
      state.status = await api("/status");
    } catch (error) {
      state.status = null;
    }
    const box = document.getElementById("model-status");
    box.replaceChildren();
    const ok = state.status && state.status.ai_configured;
    box.append(h("span", { class: "dot" + (ok ? "" : " off") }),
      state.status ? (ok ? state.status.model : "No API key set") : "Not connected");
    return state.status;
  }

  function keyBanner() {
    if (!state.status || state.status.ai_configured) return null;
    return h("div", { class: "banner" }, icon("key"), h("div", null,
      h("strong", null, "Add your Gemini API key to use the AI tools. "),
      "Copy ", h("code", null, ".env.example"), " to ", h("code", null, ".env"),
      ", set ", h("code", null, "GEMINI_API_KEY"), ", then restart DocuMentor."));
  }

  // ---------- document picker ----------
  function picker(label, role, opts) {
    const options = opts || {};
    const select = h("select", { name: role + "_id" });
    function fill(selected) {
      select.replaceChildren();
      if (options.optional) select.append(h("option", { value: "" }, "None"));
      else select.append(h("option", { value: "", disabled: true }, "Choose a document"));
      const matching = state.documents.filter((d) => d.role === role);
      const others = state.documents.filter((d) => d.role !== role);
      const add = (d) => h("option", { value: d.id }, d.name);
      if (matching.length) select.append(h("optgroup", { label: ROLE_LABEL[role] }, matching.map(add)));
      if (others.length) select.append(h("optgroup", { label: "Other documents" }, others.map(add)));
      select.append(h("option", { value: "__upload" }, "Upload a file…"));
      select.value = selected || (matching[0] ? matching[0].id : "");
      if (select.selectedIndex < 0) select.value = "";
      select.dataset.previous = select.value;
    }
    fill();
    select.addEventListener("change", async () => {
      if (select.value !== "__upload") { select.dataset.previous = select.value; return; }
      const files = await chooseFiles(false);
      if (!files.length) { select.value = select.dataset.previous || ""; return; }
      try {
        const added = await uploadFiles(files, role);
        await loadDocuments();
        fill(added[0] ? added[0].id : select.dataset.previous);
      } catch (error) {
        failed(error);
        select.value = select.dataset.previous || "";
      }
    });
    return h("label", { class: "field" },
      h("span", null, label, options.optional ? h("span", { class: "hint" }, " (optional)") : null),
      select, options.hint && h("span", { class: "hint" }, options.hint));
  }

  function formValue(form, name) { return form.elements[name] ? form.elements[name].value : ""; }

  function needLibrary() {
    if (state.documents.length) return null;
    return h("div", { class: "banner info" }, icon("upload"), h("div", null,
      "Your library is empty. Choose ", h("strong", null, "Upload a file…"),
      " in a list below, or add several at once in the ", h("a", { href: "#/library" }, "Library"), "."));
  }

  // Shared shell for the tools: a form that becomes a progress panel, then opens the review.
  function toolForm(fields, submitLabel, buildParams, jobType) {
    const button = h("button", { class: "btn primary", type: "submit" }, icon("spark"), submitLabel);
    const slot = h("div");
    const form = h("form", { class: "card", novalidate: true }, fields, h("div", { class: "row" }, button));
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      let params;
      try {
        params = buildParams(form);
      } catch (error) {
        return failed(error);
      }
      const panel = progressPanel();
      slot.replaceChildren(panel.node);
      button.disabled = true;
      try {
        const output = await runJob(jobType, params, panel.update);
        location.hash = "#/result/" + output.result_id;
      } catch (error) {
        slot.replaceChildren(h("div", { class: "banner bad", role: "alert" }, icon("warn"), h("div", null, error.message)));
      } finally {
        button.disabled = false;
      }
    });
    return [form, slot];
  }

  function requireValue(value, message) {
    if (!value || value === "__upload") throw new Error(message);
    return value;
  }

  // ---------- pages ----------
  async function homePage() {
    const [docs, results] = await Promise.all([loadDocuments(), api("/results")]);
    const hasBook = docs.some((d) => d.role === "textbook");
    const node = h("div", { class: "page" });
    node.append(h("section", { class: "hero" },
      h("h1", null, "Homework and notes, checked against your textbook"),
      h("p", { class: "lead" }, "Every change comes with a reason and a textbook passage, and nothing is applied until you accept it.")));
    const banner = keyBanner();
    if (banner) node.append(banner);
    const tool = (href, iconName, title, text) => h("a", { class: "card tool", href },
      h("span", { class: "tool-icon" }, icon(iconName)), h("h2", null, title), h("p", null, text));
    node.append(h("section", { class: "grid two" },
      tool("#/check", "check", "Check homework", "Find off-topic questions and approve each replacement."),
      tool("#/create", "spark", "Create homework", "Write a new assignment with marks, difficulty and an answer key."),
      tool("#/notes", "notes", "Review notes", "Separate real mistakes from content the textbook simply doesn't cover."),
      tool("#/ask", "chat", "Ask your documents", "Chat with follow-up questions and answers that cite their source.")));
    if (!docs.length) {
      node.append(h("section", { class: "card" }, h("h2", null, "Getting started"),
        h("ol", { class: "steps" },
          h("li", { class: state.status && state.status.ai_configured ? "done" : "" }, h("span", null, "Connect Gemini with your API key")),
          h("li", { class: hasBook ? "done" : "" }, h("span", null, h("a", { href: "#/library" }, "Add a textbook"), " in .docx, .pdf, .txt or .md")),
          h("li", null, h("span", null, "Choose a tool and review the results")))));
    }
    const recent = results.results.slice(0, 5);
    if (recent.length) {
      node.append(h("section", { class: "card" }, h("div", { class: "row" }, h("h2", { class: "grow" }, "Recent work"),
        h("a", { class: "btn ghost small", href: "#/history" }, "See all")),
        h("div", { class: "list" }, recent.map(resultRow))));
    }
    return node;
  }

  function resultRow(result) {
    return h("div", { class: "list-row" },
      h("a", { class: "list-link grow", href: "#/result/" + result.id },
        h("div", { class: "name" }, result.title),
        h("div", { class: "muted small-text" }, TYPE_LABEL[result.type] + " · " + when(result.created_at))));
  }

  async function libraryPage() {
    await loadDocuments();
    const node = page("Library", "Add a document once and use it in every tool. Only the extracted text is kept, on this computer.");
    const listCard = h("section", { class: "card" });

    function renderList() {
      listCard.replaceChildren();
      if (!state.documents.length) {
        listCard.append(empty("book", "No documents yet. Add a textbook to get started."));
        return;
      }
      listCard.append(h("div", { class: "list" }, state.documents.map(documentRow)));
    }

    function documentRow(doc) {
      const role = h("select", { "aria-label": "Type of " + doc.name, onchange: async () => {
        try {
          await api("/documents/" + doc.id, { method: "PATCH", json: { role: role.value } });
          doc.role = role.value;
          toast("Marked as " + ROLE_LABEL[role.value].toLowerCase());
        } catch (error) { failed(error); role.value = doc.role; }
      } }, Object.keys(ROLE_LABEL).map((k) => h("option", { value: k }, ROLE_LABEL[k])));
      role.value = doc.role;
      return h("div", { class: "list-row" },
        h("div", { class: "grow" }, h("div", { class: "name" }, doc.name),
          h("div", { class: "muted small-text" }, size(doc))),
        role,
        h("button", { class: "btn ghost small", type: "button", onclick: () => previewDocument(doc) }, icon("eye"), "Preview"),
        h("button", { class: "btn ghost small icon-only", type: "button", title: "Delete " + doc.name, "aria-label": "Delete " + doc.name,
          onclick: async () => {
            if (!(await confirmDialog("Delete this document?", doc.name + " will be removed from your library. Saved results stay.", "Delete"))) return;
            try {
              await api("/documents/" + doc.id, { method: "DELETE" });
              await loadDocuments();
              renderList();
            } catch (error) { failed(error); }
          } }, icon("trash")));
    }

    async function add(files) {
      if (!files.length) return;
      status.hidden = false;
      try {
        await uploadFiles(files);
        await loadDocuments();
        renderList();
      } catch (error) { failed(error); }
      status.hidden = true;
    }

    const status = h("div", { class: "typing", hidden: true }, h("span", { class: "spinner" }), "Reading your files…");
    const drop = h("button", { class: "drop", type: "button",
      onclick: async () => add(await chooseFiles(true)),
      ondragover: (e) => { e.preventDefault(); drop.classList.add("over"); },
      ondragleave: () => drop.classList.remove("over"),
      ondrop: (e) => { e.preventDefault(); drop.classList.remove("over"); add([...e.dataTransfer.files]); } },
      icon("upload"), h("strong", null, "Drop files here or click to choose"),
      h("span", { class: "muted small-text" }, ".docx, .pdf, .txt or .md, up to " + (state.status ? state.status.max_upload_mb : 25) + " MB in total. The type is guessed from the file name."));
    node.append(drop, status, listCard);
    renderList();
    return node;
  }

  async function previewDocument(doc) {
    try {
      const data = await api("/documents/" + doc.id);
      dialog.replaceChildren(h("div", { class: "dialog-body" },
        h("h2", null, data.name),
        h("p", { class: "muted small-text" }, size(data) + " · " + plural(data.sections, "section")),
        h("div", { class: "preview-box" }, data.preview + (data.chars > data.preview.length ? "\n\n… preview only; the whole document is searched." : "")),
        h("div", { class: "dialog-actions" }, h("button", { class: "btn", type: "button", onclick: () => dialog.close() }, "Close"))));
      dialog.showModal();
    } catch (error) { failed(error); }
  }

  async function checkPage() {
    await loadDocuments();
    const node = page("Check homework", "Each question is compared with the textbook. You decide which changes to keep.", null, true);
    const params = (form) => ({
      textbook_id: requireValue(formValue(form, "textbook_id"), "Choose a textbook first."),
      homework_id: requireValue(formValue(form, "homework_id"), "Choose the homework to check."),
      notes_id: formValue(form, "notes_id") === "__upload" ? "" : formValue(form, "notes_id"),
    });
    node.append(keyBanner() || "", needLibrary() || "", ...toolForm([
      picker("Textbook", "textbook"),
      picker("Homework", "homework"),
      picker("Class notes", "notes", { optional: true, hint: "Helps match questions to what was taught." }),
    ], "Check homework", params, "check_homework"));
    return node;
  }

  async function createPage() {
    await loadDocuments();
    const node = page("Create homework", "Write an assignment from your material, with marks, difficulty and answers.", null, true);
    const types = state.status ? state.status.question_types : [];
    const params = (form) => ({
      textbook_id: requireValue(formValue(form, "textbook_id"), "Choose a textbook first."),
      notes_id: formValue(form, "notes_id") === "__upload" ? "" : formValue(form, "notes_id"),
      count: Number(formValue(form, "count")),
      difficulty: formValue(form, "difficulty"),
      total_marks: formValue(form, "total_marks") || null,
      question_types: [...form.querySelectorAll('input[name="qtype"]:checked')].map((box) => box.value),
      instructions: formValue(form, "instructions"),
    });
    const max = state.status ? state.status.max_questions : 50;
    node.append(keyBanner() || "", needLibrary() || "", ...toolForm([
      picker("Textbook", "textbook"),
      picker("Class notes", "notes", { optional: true, hint: "Focuses questions on what was taught." }),
      h("div", { class: "grid three" },
        h("label", { class: "field" }, "Questions", h("input", { type: "number", name: "count", min: 1, max, value: 5 })),
        h("label", { class: "field" }, "Difficulty", h("select", { name: "difficulty" },
          ["mixed", "easy", "medium", "hard"].map((d) => h("option", { value: d }, d[0].toUpperCase() + d.slice(1))))),
        h("label", { class: "field" }, h("span", null, "Total marks", h("span", { class: "hint" }, " (optional)")),
          h("input", { type: "number", name: "total_marks", min: 1, max: 100 }))),
      h("fieldset", null, h("legend", null, "Question types"),
        h("div", { class: "checks" }, types.map((t) => h("label", { class: "check-chip" },
          h("input", { type: "checkbox", name: "qtype", value: t }), t[0].toUpperCase() + t.slice(1))))),
      h("label", { class: "field" }, h("span", null, "Special requests", h("span", { class: "hint" }, " (optional)")),
        h("textarea", { name: "instructions", maxLength: 2000, placeholder: "For example: 2 multiple choice questions on clustering, then 3 problems that compare algorithms." })),
    ], "Create homework", params, "generate_homework"));
    return node;
  }

  async function notesPage() {
    await loadDocuments();
    const node = page("Review notes", "Mistakes are kept apart from content the textbook just doesn't mention, so correct notes aren't rewritten.", null, true);
    const params = (form) => ({
      textbook_id: requireValue(formValue(form, "textbook_id"), "Choose a textbook first."),
      notes_id: requireValue(formValue(form, "notes_id"), "Choose the notes to review."),
    });
    node.append(keyBanner() || "", needLibrary() || "", ...toolForm([
      picker("Textbook", "textbook"), picker("Notes", "notes"),
    ], "Review notes", params, "correct_notes"));
    return node;
  }

  async function historyPage() {
    const { results } = await api("/results");
    const node = page("History", "Everything you've made is saved here. Reopen it to keep reviewing or export it again.");
    const card = h("section", { class: "card" });
    const search = h("input", { type: "search", placeholder: "Search by title", "aria-label": "Search history", oninput: render });
    let filter = "all";
    const seg = h("div", { class: "seg", role: "group", "aria-label": "Filter by type" },
      [["all", "All"], ["homework_check", "Checks"], ["homework_generated", "New homework"], ["notes_correction", "Notes"]].map(([value, label]) =>
        h("button", { type: "button", "aria-pressed": String(value === "all"), onclick: (e) => {
          filter = value;
          seg.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", "false"));
          e.currentTarget.setAttribute("aria-pressed", "true");
          render();
        } }, label)));

    function render() {
      const term = search.value.trim().toLowerCase();
      const rows = results.filter((r) => (filter === "all" || r.type === filter) && r.title.toLowerCase().includes(term));
      card.replaceChildren(rows.length
        ? h("div", { class: "list" }, rows.map((r) => {
            const row = resultRow(r);
            row.append(h("button", { class: "btn ghost small icon-only", type: "button", title: "Delete", "aria-label": "Delete " + r.title,
              onclick: async () => {
                if (!(await confirmDialog("Delete this result?", r.title, "Delete"))) return;
                try {
                  await api("/results/" + r.id, { method: "DELETE" });
                  results.splice(results.indexOf(r), 1);
                  render();
                } catch (error) { failed(error); }
              } }, icon("trash")));
            return row;
          }))
        : empty("clock", results.length ? "Nothing matches that search." : "Nothing saved yet. Results from the tools appear here."));
    }
    render();
    node.append(h("div", { class: "row" }, h("div", { class: "grow" }, search), seg), card);
    return node;
  }

  // ---------- review ----------
  function sourcesBlock(sources) {
    if (!sources || !sources.length) return null;
    return h("details", null, h("summary", null, "Textbook passages (" + sources.length + ")"),
      sources.map((s) => h("div", { class: "source" }, h("b", null, s.document + " · " + s.label), s.excerpt + (s.excerpt.length >= 400 ? "…" : ""))));
  }

  function tiles(list) {
    return h("div", { class: "tiles" }, list.map(([value, label]) => h("div", { class: "tile" }, h("b", null, value), h("span", null, label))));
  }

  function analysisLine(data) {
    const a = data.analysis;
    if (!a) return null;
    return h("p", { class: "muted small-text" }, "Searched all " + a.chars.toLocaleString() + " characters of " + a.document +
      " and used the " + plural(a.passages_used, "most relevant passage") + " of " + a.passages_total + ".");
  }

  function coverageChart(rows) {
    if (!rows || !rows.length) return null;
    const max = Math.max(1, ...rows.map((r) => r.count));
    const tip = h("div", { class: "tooltip", hidden: true, role: "tooltip" });
    const describe = (r) => r.count ? "Question" + (r.count === 1 ? " " : "s ") + r.questions.join(", ") : "No question covers this topic";
    const showTip = (r) => (e) => {
      tip.textContent = r.topic + ": " + describe(r);
      tip.hidden = false;
      const box = e.currentTarget.getBoundingClientRect();
      tip.style.left = Math.min(box.left, innerWidth - 280) + "px";
      tip.style.top = Math.max(8, box.top - 40) + "px";
    };
    const chart = h("div", { class: "coverage" }, rows.map((r) => {
      const bar = h("span", { class: "cov-bar" });
      bar.style.width = (r.count / max) * 100 + "%";
      return h("div", { class: "cov-row", tabIndex: 0, "aria-label": r.topic + ": " + describe(r),
        onmouseenter: showTip(r), onfocus: showTip(r),
        onmouseleave: () => { tip.hidden = true; }, onblur: () => { tip.hidden = true; } },
        h("div", { class: "cov-head" }, h("span", null, r.topic), h("b", null, String(r.count))),
        h("div", { class: "cov-track" }, r.count ? bar : h("span", { class: "cov-none" }, icon("warn"), "Not covered")));
    }));
    const missing = rows.filter((r) => !r.count).length;
    return h("section", { class: "card" }, h("h2", null, "Questions per topic"),
      h("p", { class: "muted small-text" }, missing ? plural(missing, "topic") + " with no question" : "Every topic has at least one question"),
      chart, tip,
      h("details", null, h("summary", null, "View as table"),
        h("table", { class: "data" },
          h("thead", null, h("tr", null, h("th", null, "Topic"), h("th", { class: "num" }, "Questions"), h("th", null, "Numbers"))),
          h("tbody", null, rows.map((r) => h("tr", null, h("td", null, r.topic), h("td", { class: "num" }, String(r.count)), h("td", null, r.questions.join(", ") || "–")))))));
  }

  function exportControls(result) {
    const isHomework = result.type !== "notes_correction";
    const answers = h("input", { type: "checkbox" });
    const tags = h("input", { type: "checkbox" });
    const link = h("a", { class: "btn primary", download: "" }, icon("download"), "Export to Word");
    const update = () => {
      const query = new URLSearchParams();
      if (answers.checked) query.set("answers", "1");
      if (tags.checked) query.set("tags", "1");
      link.href = "/api/results/" + result.id + "/export?" + query;
    };
    answers.addEventListener("change", update);
    tags.addEventListener("change", update);
    update();
    return h("section", { class: "card" }, h("h2", null, "Export"),
      result.stats.pending ? h("p", { class: "muted small-text" }, plural(result.stats.pending, "change") + " still undecided; originals are used until you accept.") : null,
      isHomework && h("div", { class: "checks" },
        h("label", { class: "check-chip" }, answers, "Answer key"),
        h("label", { class: "check-chip" }, tags, "Marks and difficulty")),
      link);
  }

  async function resultPage(id) {
    const node = h("div", { class: "page" });
    let result = await api("/results/" + id);
    let filter = "all";
    const body = h("div", { class: "grid" });
    const aside = h("div", { class: "grid sticky" });
    const summary = h("div");
    const title = h("input", { class: "title-input", type: "text", value: result.title, "aria-label": "Title", maxLength: 160,
      onchange: async () => {
        try { await api("/results/" + id, { method: "PATCH", json: { title: title.value } }); }
        catch (error) { failed(error); title.value = result.title; }
      } });

    async function patch(payload) {
      try {
        result = await api("/results/" + id, { method: "PATCH", json: payload });
        render();
      } catch (error) { failed(error); }
    }

    function editDialog(heading, current, onSave) {
      const area = h("textarea", { rows: 5, value: current, "aria-label": heading });
      dialog.replaceChildren(h("div", { class: "dialog-body" }, h("h2", null, heading), area,
        h("div", { class: "dialog-actions" },
          h("button", { class: "btn", type: "button", onclick: () => dialog.close() }, "Cancel"),
          h("button", { class: "btn primary", type: "button", onclick: () => { dialog.close(); onSave(area.value); } }, "Save"))));
      dialog.showModal();
      area.focus();
    }

    function decisionButtons(entry, acceptLabel, rejectLabel) {
      return [
        h("button", { class: "btn small good" + (entry.decision === "accepted" ? " on" : ""), type: "button", "aria-pressed": String(entry.decision === "accepted"),
          onclick: () => patch({ entry_id: entry.id, decision: "accepted" }) }, icon("yes"), acceptLabel),
        h("button", { class: "btn small bad" + (entry.decision === "rejected" ? " on" : ""), type: "button", "aria-pressed": String(entry.decision === "rejected"),
          onclick: () => patch({ entry_id: entry.id, decision: "rejected" }) }, icon("no"), rejectLabel),
      ];
    }

    function itemCard(item, number) {
      if (item.type === "text" && item.verdict === "keep") {
        return h("div", { class: "item is-text" }, h("strong", null, item.original));
      }
      const pending = item.decision === "pending";
      const chips = [];
      if (item.flagged) chips.push(h("span", { class: "chip bad" }, icon("warn"), "Looks like AI instructions"));
      else if (item.verdict === "replace") chips.push(h("span", { class: "chip warn" }, "Off topic"));
      else if (item.verdict === "remove") chips.push(h("span", { class: "chip warn" }, "Not a question"));
      if (pending) chips.push(h("span", { class: "chip" }, "Needs your decision"));
      if (item.decision === "accepted" && item.verdict !== "keep") chips.push(h("span", { class: "chip good" }, icon("yes"), "Accepted"));
      if (item.decision === "rejected") chips.push(h("span", { class: "chip" }, "Original kept"));
      if (item.edited) chips.push(h("span", { class: "chip info" }, "Edited"));
      if (item.difficulty) chips.push(h("span", { class: "chip" }, item.difficulty));
      if (item.marks) chips.push(h("span", { class: "chip" }, plural(item.marks, "mark")));
      for (const topic of item.topics || []) chips.push(h("span", { class: "chip info" }, topic));

      const options = (item.options || []).length ? h("ol", { type: "a" }, item.options.map((o) => h("li", null, o))) : null;
      const content = item.verdict === "replace"
        ? h("div", { class: "compare" },
            h("div", null, h("span", { class: "tag" }, "Original"), h("span", { class: "qtext" + (item.decision === "accepted" ? " was" : "") }, stripNumber(item.original))),
            h("div", { class: "now-box" }, h("span", { class: "tag" }, "Suggested"), h("span", { class: "qtext" }, item.replacement)))
        : h("div", null, h("p", { class: "qtext" + (item.verdict === "remove" && item.decision !== "rejected" ? " muted" : "") }, stripNumber(item.original)), options);

      const acceptLabel = item.verdict === "replace" ? "Use suggestion" : "Remove";
      return h("article", { class: "card item" + (item.flagged && pending ? " flagged" : pending ? " pending" : ""), "aria-label": "Question " + number },
        h("div", { class: "item-top" }, h("span", { class: "qnum" }, "Q" + number), h("div", { class: "chips grow" }, chips)),
        content,
        item.reason && h("p", { class: "reason" }, item.reason),
        item.answer && h("details", null, h("summary", null, "Answer"), h("div", { class: "source" }, markdown(item.answer))),
        sourcesBlock(item.sources),
        h("div", { class: "actions" },
          item.verdict !== "keep" ? decisionButtons(item, acceptLabel, "Keep original") : null,
          h("button", { class: "btn ghost small", type: "button", onclick: () => editDialog("Edit question", item.verdict === "replace" ? item.replacement : item.original,
            (text) => patch({ entry_id: item.id, text })) }, icon("edit"), "Edit"),
          h("button", { class: "btn ghost small", type: "button", onclick: async () => {
            if (await confirmDialog("Delete this question?", "It will be left out of the export.", "Delete")) patch({ entry_id: item.id, delete: true });
          } }, icon("trash"), "Delete")));
    }

    function renderHomework() {
      const items = result.data.items.filter((i) => i.verdict !== "deleted");
      const s = result.stats;
      const stats = result.type === "homework_check"
        ? [[s.final_questions, "questions"], [s.changes, "suggested changes"], [s.pending, "to decide"]]
        : [[s.final_questions, "questions"]];
      if (s.marks) stats.push([s.marks, result.type === "homework_check" ? "suggested marks" : "total marks"]);
      summary.replaceChildren(tiles(stats));

      let number = 0;
      const numbered = items.map((item) => {
        if (!(item.type === "text" && item.verdict === "keep")) number += 1;
        return { item, number };
      });
      const shown = numbered.filter(({ item }) =>
        filter === "all" || (filter === "pending" && item.decision === "pending") ||
        (filter === "changes" && item.verdict !== "keep") || (filter === "flagged" && item.flagged));
      body.replaceChildren(...(shown.length
        ? shown.map(({ item, number: n }) => itemCard(item, n))
        : [h("div", { class: "card" }, empty("yes", "Nothing here."))]));

      const answerButton = h("button", { class: "btn", type: "button", onclick: async () => {
        const panel = progressPanel();
        answerButton.replaceWith(panel.node);
        try {
          await runJob("answer_key", { result_id: id }, panel.update);
          result = await api("/results/" + id);
          toast("Answer key ready");
          render();
        } catch (error) { failed(error); render(); }
      } }, icon("spark"), s.answers ? "Rewrite answer key" : "Write answer key");
      const tools = h("section", { class: "card" }, h("h2", null, "Answer key"),
        h("p", { class: "muted small-text" }, s.answers + " of " + s.final_questions + " questions answered"), answerButton);
      aside.replaceChildren(exportControls(result), tools, coverageChart(result.coverage) || "");
    }

    function issueCard(issue) {
      const label = { incorrect: ["bad", "Contradicts textbook"], unsupported: ["info", "Not in textbook"], incomplete: ["warn", "Missing from notes"] }[issue.category];
      const pending = issue.decision === "pending";
      const chips = [h("span", { class: "chip " + label[0] }, label[1])];
      if (pending) chips.push(h("span", { class: "chip" }, "Needs your decision"));
      if (issue.decision === "accepted") chips.push(h("span", { class: "chip good" }, icon("yes"), "Applied"));
      if (issue.decision === "rejected") chips.push(h("span", { class: "chip" }, "Original kept"));
      if (issue.original && !issue.matched) chips.push(h("span", { class: "chip warn" }, "Couldn't find this wording in the notes"));
      return h("article", { class: "card item" + (pending ? " pending" : "") },
        h("div", { class: "chips" }, chips),
        issue.category === "incomplete"
          ? h("div", { class: "compare" }, h("div", { class: "now-box" }, h("span", { class: "tag" }, "Suggested addition"), h("span", { class: "qtext" }, issue.correction)))
          : issue.correction
            ? h("div", { class: "compare" },
                h("div", null, h("span", { class: "tag" }, "In your notes"), h("span", { class: "qtext" }, issue.original)),
                h("div", { class: "now-box" }, h("span", { class: "tag" }, "Suggested"), h("span", { class: "qtext" }, issue.correction)))
            : h("p", { class: "qtext" }, issue.original),
        h("p", { class: "reason" }, issue.reason),
        sourcesBlock(issue.sources),
        issue.applicable && h("div", { class: "actions" },
          decisionButtons(issue, issue.category === "incomplete" ? "Add to notes" : "Apply fix", "Skip"),
          h("button", { class: "btn ghost small", type: "button", onclick: () => editDialog("Edit suggestion", issue.correction, (text) => patch({ entry_id: issue.id, text })) }, icon("edit"), "Edit")));
    }

    function renderNotes() {
      const s = result.stats;
      summary.replaceChildren(tiles([[s.incorrect, "contradict textbook"], [s.unsupported, "not in textbook"], [s.incomplete, "missing"], [s.pending, "to decide"]]));
      const issues = result.data.issues.filter((i) => filter === "all" || (filter === "pending" && i.decision === "pending"));
      body.replaceChildren(...(issues.length ? issues.map(issueCard)
        : [h("div", { class: "card" }, empty("yes", result.data.issues.length ? "Nothing here." : "No problems found. These notes match the textbook."))]));
      aside.replaceChildren(exportControls(result), h("section", { class: "card" }, h("h2", null, "Notes with your changes"),
        h("div", { class: "preview-box" }, result.final_text)));
    }

    const isHomework = result.type !== "notes_correction";
    const filters = isHomework
      ? [["all", "All"], ["pending", "To decide"], ["changes", "Changes"], ["flagged", "Flagged"]]
      : [["all", "All"], ["pending", "To decide"]];
    const seg = h("div", { class: "seg", role: "group", "aria-label": "Filter" }, filters.map(([value, label]) =>
      h("button", { type: "button", "aria-pressed": String(value === "all"), onclick: (e) => {
        filter = value;
        seg.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", "false"));
        e.currentTarget.setAttribute("aria-pressed", "true");
        render();
      } }, label)));
    const bulk = h("div", { class: "row" },
      h("button", { class: "btn small", type: "button", onclick: () => patch({ bulk: "accepted" }) }, "Accept all"),
      h("button", { class: "btn small", type: "button", onclick: () => patch({ bulk: "rejected" }) }, "Reject all"));

    function render() {
      bulk.hidden = !result.stats.pending;
      if (isHomework) renderHomework(); else renderNotes();
    }

    node.append(
      h("header", { class: "page-head" }, h("div", null,
        h("span", { class: "chip info" }, TYPE_LABEL[result.type]), title, analysisLine(result.data))),
      summary,
      h("div", { class: "split" },
        h("div", { class: "grid" }, h("div", { class: "row" }, h("div", { class: "grow" }, seg), bulk), body),
        aside));
    render();
    return node;
  }

  // ---------- chat ----------
  async function askPage(chatId) {
    await loadDocuments();
    const { chats } = await api("/chats");
    const node = page("Ask your documents", "Answers come only from your documents, and say so when the answer isn't there.");
    const banner = keyBanner();
    if (banner) node.append(banner);
    const list = h("nav", { class: "chat-list", "aria-label": "Conversations" },
      h("a", { href: "#/ask", "aria-current": String(!chatId) }, "+ New conversation"),
      chats.map((c) => h("a", { href: "#/ask/" + c.id, "aria-current": String(c.id === chatId) }, c.title)));
    node.append(h("div", { class: "chat-layout" }, h("div", { class: "card" }, list), chatId ? await chatPane(chatId) : newChat()));
    return node;
  }

  function newChat() {
    if (!state.documents.length) {
      return h("div", { class: "card" }, empty("book", "Add a document to start asking questions.", h("a", { class: "btn primary", href: "#/library" }, "Go to Library")));
    }
    const boxes = state.documents.map((d) => h("label", { class: "check-chip" },
      h("input", { type: "checkbox", value: d.id, checked: state.documents.length <= 2 || d.role === "textbook" }), d.name));
    return h("form", { class: "card", onsubmit: async (event) => {
      event.preventDefault();
      const ids = [...event.currentTarget.querySelectorAll("input:checked")].map((b) => b.value);
      if (!ids.length) return toast("Choose at least one document.", "bad");
      try {
        const { chat_id: id } = await api("/chats", { method: "POST", json: { document_ids: ids } });
        location.hash = "#/ask/" + id;
      } catch (error) { failed(error); }
    } },
      h("h2", null, "Which documents should I use?"), h("div", { class: "checks" }, boxes),
      h("div", { class: "row" }, h("button", { class: "btn primary", type: "submit" }, "Start conversation")));
  }

  async function chatPane(chatId) {
    const chat = await api("/chats/" + chatId);
    const messages = h("div", { class: "messages", "aria-live": "polite" });
    const area = h("textarea", { placeholder: "Ask a question", rows: 1, maxLength: 4000, "aria-label": "Your question",
      onkeydown: (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } } });
    const button = h("button", { class: "btn primary", type: "button", onclick: () => send() }, icon("send"), "Send");

    function bubble(message) {
      if (message.role === "user") return h("div", { class: "msg user" }, message.content);
      return h("div", { class: "msg assistant" }, markdown(message.content), sourcesBlock(message.sources));
    }
    function scroll() { messages.scrollTop = messages.scrollHeight; }
    function paint() {
      messages.replaceChildren(...(chat.messages.length ? chat.messages.map(bubble) : [starter()]));
      scroll();
    }
    function starter() {
      const suggestions = ["Summarise the main topics", "What should I revise first?", "Explain the hardest concept simply"];
      return h("div", { class: "empty" }, icon("chat"), h("p", null, "Ask anything about " + chat.title + "."),
        h("div", { class: "chips" }, suggestions.map((s) => h("button", { class: "btn small", type: "button", onclick: () => { area.value = s; send(); } }, s))));
    }
    async function send() {
      const question = area.value.trim();
      if (!question || button.disabled) return;
      button.disabled = true;
      area.value = "";
      const status = h("span", null, "Searching your documents");
      if (!chat.messages.length) messages.replaceChildren();
      messages.append(h("div", { class: "msg user" }, question), h("div", { class: "typing" }, h("span", { class: "spinner" }), status));
      scroll();
      try {
        await runJob("chat", { question }, (job) => { status.textContent = job.message; }, "/chats/" + chatId + "/messages");
        Object.assign(chat, await api("/chats/" + chatId));
        paint();
      } catch (error) {
        area.value = question;  // keep what they typed so they can retry
        paint();
        messages.append(h("div", { class: "banner bad", role: "alert" }, icon("warn"), h("div", null, error.message)));
        scroll();
      } finally {
        button.disabled = false;
        area.focus();
      }
    }
    paint();
    return h("section", { class: "card chat-main" },
      h("div", { class: "chat-title row" }, h("h2", { class: "grow" }, chat.title),
        h("button", { class: "btn ghost small icon-only", type: "button", title: "Delete conversation", "aria-label": "Delete conversation",
          onclick: async () => {
            if (!(await confirmDialog("Delete this conversation?", chat.title, "Delete"))) return;
            try { await api("/chats/" + chatId, { method: "DELETE" }); location.hash = "#/ask"; }
            catch (error) { failed(error); }
          } }, icon("trash"))),
      messages, h("div", { class: "composer" }, area, button));
  }

  // ---------- routing and theme ----------
  const routes = { "": homePage, library: libraryPage, check: checkPage, create: createPage, notes: notesPage, history: historyPage };
  const navFor = { "": "home", result: "history" };

  async function route() {
    const [, first = "", second] = location.hash.replace(/^#/, "").split("/");
    const token = ++state.navToken;
    const active = navFor[first] || first;
    document.querySelectorAll("#nav a").forEach((link) => {
      if (link.dataset.route === active) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
    let node;
    try {
      if (!state.status) await refreshStatus();
      if (first === "result" && second) node = await resultPage(second);
      else if (first === "ask") node = await askPage(second);
      else if (routes[first]) node = await routes[first]();
      else node = h("div", { class: "page" }, h("div", { class: "card" }, empty("warn", "That page doesn't exist.", h("a", { class: "btn", href: "#/" }, "Go home"))));
    } catch (error) {
      node = h("div", { class: "page" }, h("div", { class: "banner bad", role: "alert" }, icon("warn"), h("div", null, error.message)),
        h("div", null, h("a", { class: "btn", href: "#/" }, "Go home")));
    }
    if (token !== state.navToken) return;  // a newer navigation won
    view.replaceChildren(node);
    window.scrollTo(0, 0);
    if (first) view.focus({ preventScroll: true });
    const heading = view.querySelector("h1");
    const titleInput = view.querySelector(".title-input");
    const pageTitle = heading ? heading.textContent : titleInput ? titleInput.value : "";
    document.title = (pageTitle ? pageTitle + " · " : "") + "DocuMentor";
  }

  function setupTheme() {
    const button = document.getElementById("theme-toggle");
    const modes = [["auto", "auto", "Theme: system"], ["light", "sun", "Theme: light"], ["dark", "moon", "Theme: dark"]];
    const read = () => { try { return localStorage.getItem("documentor-theme") || "auto"; } catch (e) { return "auto"; } };
    const paint = () => {
      const mode = modes.find((m) => m[0] === read()) || modes[0];
      button.replaceChildren(icon(mode[1]), mode[2]);
    };
    button.addEventListener("click", () => {
      const next = modes[(modes.findIndex((m) => m[0] === read()) + 1) % modes.length][0];
      try { localStorage.setItem("documentor-theme", next); } catch (e) { /* private mode */ }
      if (next === "auto") delete document.documentElement.dataset.theme;
      else document.documentElement.dataset.theme = next;
      paint();
    });
    paint();
  }

  window.addEventListener("hashchange", route);
  setupTheme();
  refreshStatus().then(route);
})();
