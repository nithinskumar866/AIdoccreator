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

  // replaceChildren, skipping empty values the way h() does, and accepting arrays.
  function put(node, ...children) {
    node.replaceChildren(...children.flat(Infinity).filter((c) => c !== undefined && c !== null && c !== false)
      .map((c) => (c.nodeType ? c : String(c))));
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

  const ROLE_LABEL = { textbook: "Textbook", notes: "Notes", homework: "Homework", answers: "Student work" };
  const TYPE_LABEL = { homework_check: "Homework check", homework_generated: "New homework", homework_bank: "From the bank",
    notes_correction: "Notes review", grading: "Grading" };
  const HOMEWORK_TYPES = ["homework_check", "homework_generated", "homework_bank"];

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
      const others = state.documents.filter((d) => d.role !== role && d.role !== "answers");
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
      tool("#/grade", "grade", "Grade answers", "Mark students' work with suggested marks and feedback you approve."),
      tool("#/bank", "bank", "Question bank", "Keep your best questions and build new assignments from them."),
      tool("#/ask", "chat", "Ask your documents", "Chat with follow-up questions and answers that cite their source."),
      tool("#/notes", "notes", "Review notes", "Separate real mistakes from content the textbook simply doesn't cover.")));
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
      [["all", "All"], ["homework_check", "Checks"], ["homework_generated", "New homework"], ["homework_bank", "From the bank"],
        ["grading", "Gradings"], ["notes_correction", "Notes"]].map(([value, label]) =>
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
      h("div", { class: "row" }, link,
        isHomework && h("a", { class: "btn", download: "", href: "/api/results/" + result.id + "/export?compare=1" }, icon("compare"), "Changes report")));
  }

  async function resultPage(id) {
    let result = await api("/results/" + id);
    if (result.type === "grading") return gradingPage(result);
    const node = h("div", { class: "page" });
    let filter = "all";
    let mode = "review";
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
      if (item.added) chips.push(h("span", { class: "chip info" }, "New"));
      const banked = (result.banked || []).includes(item.id);
      if (banked) chips.push(h("span", { class: "chip good" }, icon("bookmark"), "In bank"));
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
          inFinal(item) && !banked && h("button", { class: "btn ghost small", type: "button", onclick: () => saveToBank([item.id]) }, icon("bookmark"), "Save to bank"),
          h("button", { class: "btn ghost small", type: "button", onclick: async () => {
            if (await confirmDialog("Delete this question?", "It will be left out of the export.", "Delete")) patch({ entry_id: item.id, delete: true });
          } }, icon("trash"), "Delete")));
    }

    function inFinal(item) {
      if (item.type !== "question" || item.decision === "pending") return false;
      return !(item.verdict === "remove" && item.decision !== "rejected");
    }

    async function saveToBank(itemIds) {
      try {
        const out = await api("/bank", { method: "POST", json: { result_id: id, item_ids: itemIds } });
        result.banked = out.banked;
        toast(out.added ? "Saved " + plural(out.added, "question") + " to the bank" + (out.duplicates ? " (" + out.duplicates + " already there)" : "")
          : "Already in the bank");
        render();
      } catch (error) { failed(error); }
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
      const saveable = items.filter(inFinal);
      const unsaved = saveable.filter((i) => !(result.banked || []).includes(i.id)).length;
      const bankCard = h("section", { class: "card" }, h("h2", null, "Question bank"),
        h("p", { class: "muted small-text" }, (saveable.length - unsaved) + " of " + plural(saveable.length, "final question") + " saved" +
          (s.pending ? ". Decide the pending changes to save those too." : ".")),
        h("div", { class: "row" },
          h("button", { class: "btn", type: "button", disabled: !unsaved, onclick: () => saveToBank(null) }, icon("bookmark"), unsaved ? "Save all " + unsaved : "All saved"),
          h("a", { class: "btn ghost small", href: "#/bank" }, "Open bank")));
      const gradeCard = h("section", { class: "card" }, h("h2", null, "Grade student answers"),
        h("p", { class: "muted small-text" }, "Upload students' numbered answers to this homework and approve each suggested mark."),
        h("a", { class: "btn", href: "#/grade/" + id }, icon("grade"), "Grade answers"));
      aside.replaceChildren(exportControls(result), tools, bankCard, gradeCard, coverageChart(result.coverage) || "");
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

    const reviewArea = h("div", { class: "split" },
      h("div", { class: "grid" }, h("div", { class: "row" }, h("div", { class: "grow" }, seg), bulk), body),
      aside);
    const compareArea = h("div", { hidden: true });

    function render() {
      bulk.hidden = !result.stats.pending;
      reviewArea.hidden = mode !== "review";
      compareArea.hidden = mode !== "compare";
      if (isHomework) renderHomework(); else renderNotes();
      if (mode === "compare") compareArea.replaceChildren(compareView(result));
    }

    const modeSeg = isHomework && h("div", { class: "seg", role: "group", "aria-label": "View" },
      [["review", "Review", "check"], ["compare", "Compare versions", "compare"]].map(([value, label, iconName]) =>
        h("button", { type: "button", "aria-pressed": String(value === mode), onclick: (e) => {
          mode = value;
          modeSeg.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", "false"));
          e.currentTarget.setAttribute("aria-pressed", "true");
          render();
        } }, icon(iconName), label)));

    node.append(
      h("header", { class: "page-head" }, h("div", null,
        h("span", { class: "chip info" }, TYPE_LABEL[result.type]), title, analysisLine(result.data)), modeSeg || null),
      summary, reviewArea, compareArea);
    render();
    return node;
  }

  // ---------- compare versions ----------
  // Word-level difference, so a small edit shows as a small highlight rather than a new paragraph.
  function diffWords(before, after) {
    const a = before.split(/(\s+)/), b = after.split(/(\s+)/);
    if (a.length * b.length > 160000) return [[before], [after]];
    const rows = Array.from({ length: a.length + 1 }, () => new Uint16Array(b.length + 1));
    for (let i = a.length - 1; i >= 0; i -= 1) {
      for (let j = b.length - 1; j >= 0; j -= 1) {
        rows[i][j] = a[i] === b[j] ? rows[i + 1][j + 1] + 1 : Math.max(rows[i + 1][j], rows[i][j + 1]);
      }
    }
    const left = [], right = [];
    const push = (list, kind, text) => {
      const last = list[list.length - 1];
      if (last && last.kind === kind) last.text += text; else list.push({ kind, text });
    };
    let i = 0, j = 0;
    while (i < a.length && j < b.length) {
      if (a[i] === b[j]) { push(left, "same", a[i]); push(right, "same", b[j]); i += 1; j += 1; }
      else if (rows[i + 1][j] >= rows[i][j + 1]) push(left, "del", a[i++]);
      else push(right, "ins", b[j++]);
    }
    while (i < a.length) push(left, "del", a[i++]);
    while (j < b.length) push(right, "ins", b[j++]);
    // A space between two changed words joins them, so a rewritten phrase reads as one change.
    const merge = (list) => list.reduce((out, part, index) => {
      const prev = out[out.length - 1], next = list[index + 1];
      if (part.kind === "same" && !part.text.trim() && prev && next && prev.kind !== "same" && prev.kind === next.kind) {
        prev.text += part.text;
      } else if (prev && prev.kind === part.kind) {
        prev.text += part.text;
      } else {
        out.push({ ...part });
      }
      return out;
    }, []);
    const nodes = (list) => merge(list).flatMap((part) => {
      if (part.kind === "same" || !part.text.trim()) return [part.text];
      const [, lead, core, trail] = part.text.match(/^(\s*)([\s\S]*?)(\s*)$/);
      return [lead, h(part.kind, null, core), trail].filter((x) => x !== "");
    });
    return [nodes(left), nodes(right)];
  }

  const CHANGE = {
    unchanged: ["", "Unchanged"], edited: ["info", "Edited"], replaced: ["warn", "Replaced"],
    removed: ["bad", "Removed"], added: ["good", "Added"],
  };

  function compareView(result) {
    const report = result.changes;
    let onlyChanged = report.rows.some((r) => r.status !== "unchanged");
    const list = h("div", { class: "cmp-list" });
    const seg = h("div", { class: "seg", role: "group", "aria-label": "Rows to show" },
      [[true, "Changes only"], [false, "Everything"]].map(([value, label]) =>
        h("button", { type: "button", "aria-pressed": String(value === onlyChanged), onclick: (e) => {
          onlyChanged = value;
          seg.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", "false"));
          e.currentTarget.setAttribute("aria-pressed", "true");
          paint();
        } }, label)));

    function cell(number, text, other, side, status) {
      if (text === null) {
        return h("div", { class: "cmp-cell empty-cell" }, side === "before" ? "Not in the original" : "Left out of the final version");
      }
      let content = [text];
      if ((status === "edited" || status === "replaced") && other !== null) {
        content = diffWords(side === "before" ? text : other, side === "before" ? other : text)[side === "before" ? 0 : 1];
      }
      return h("div", { class: "cmp-cell" + (side === "after" ? " after" : ""), "data-label": side === "before" ? "Original" : "Now" },
        h("span", { class: "qnum" }, number + "."), h("span", { class: "qtext" }, content));
    }

    function paint() {
      const rows = report.rows.filter((r) => !onlyChanged || r.status !== "unchanged");
      list.replaceChildren(...(rows.length ? rows.map((r) => {
        const [tone, label] = CHANGE[r.status];
        return h("article", { class: "cmp-row " + r.status, "aria-label": label + (r.after_number ? ", question " + r.after_number : "") },
          cell(r.before_number, r.before, r.after, "before", r.status),
          cell(r.after_number, r.after, r.before, "after", r.status),
          h("div", { class: "cmp-meta" }, h("span", { class: "chip " + tone }, label), r.reason && h("span", { class: "reason" }, r.reason)));
      }) : [h("div", { class: "card" }, empty("yes", "Nothing has changed yet. Accept a suggestion or edit a question to see it here."))]));
    }
    paint();
    const counts = Object.entries(report.counts).filter(([, n]) => n)
      .map(([status, n]) => h("span", { class: "chip " + CHANGE[status][0] }, n + " " + CHANGE[status][1].toLowerCase()));
    return h("section", { class: "grid" },
      h("div", { class: "row" }, h("div", { class: "chips grow" }, counts), seg,
        h("a", { class: "btn small", download: "", href: "/api/results/" + result.id + "/export?compare=1" }, icon("download"), "Export to Word")),
      h("div", { class: "cmp-head", "aria-hidden": "true" }, h("span", null, "Original"), h("span", null, "Now")),
      list);
  }

  // ---------- grading ----------
  async function gradePage(homeworkId) {
    const [, { results }] = await Promise.all([loadDocuments(), api("/results")]);
    const node = page("Grade answers", "Upload each student's answers, numbered like the homework. You get a suggested mark and feedback for every answer, and you approve each one.", null, true);
    const homeworks = results.filter((r) => HOMEWORK_TYPES.includes(r.type));
    if (!homeworks.length) {
      node.append(h("div", { class: "card" }, empty("grade", "Create or check a homework first. Grading compares students' answers with its questions and answer key.",
        h("div", { class: "row" }, h("a", { class: "btn primary", href: "#/create" }, "Create homework"), h("a", { class: "btn", href: "#/check" }, "Check homework")))));
      return node;
    }
    const select = h("select", { name: "result_id" }, homeworks.map((r) => h("option", { value: r.id }, r.title + " · " + when(r.created_at))));
    if (homeworkId && homeworks.some((r) => r.id === homeworkId)) select.value = homeworkId;
    const chosen = new Set();
    const listBox = h("div", { class: "checks student-list" });

    function paintStudents() {
      const work = state.documents.filter((d) => d.role === "answers");
      listBox.replaceChildren(...(work.length ? work.map((d) => h("label", { class: "check-chip" },
        h("input", { type: "checkbox", value: d.id, checked: chosen.has(d.id),
          onchange: (e) => { if (e.currentTarget.checked) chosen.add(d.id); else chosen.delete(d.id); count.textContent = plural(chosen.size, "student") + " chosen"; } }),
        d.name)) : [h("p", { class: "muted small-text" }, "No student work yet. Upload one file per student.")]));
      count.textContent = plural(chosen.size, "student") + " chosen";
    }

    async function add(files) {
      if (!files.length) return;
      reading.hidden = false;
      try {
        const added = await uploadFiles(files, "answers");
        for (const d of added) chosen.add(d.id);
        await loadDocuments();
        paintStudents();
      } catch (error) { failed(error); }
      reading.hidden = true;
    }

    const count = h("span", { class: "muted small-text" });
    const reading = h("div", { class: "typing", hidden: true }, h("span", { class: "spinner" }), "Reading the files…");
    const drop = h("button", { class: "drop compact", type: "button",
      onclick: async () => add(await chooseFiles(true)),
      ondragover: (e) => { e.preventDefault(); drop.classList.add("over"); },
      ondragleave: () => drop.classList.remove("over"),
      ondrop: (e) => { e.preventDefault(); drop.classList.remove("over"); add([...e.dataTransfer.files]); } },
      icon("upload"), h("strong", null, "Add students' files"), h("span", { class: "muted small-text" }, "One .docx, .pdf, .txt or .md file per student. Drop several at once."));
    paintStudents();

    const params = (form) => {
      if (!chosen.size) throw new Error("Choose at least one student's work.");
      return { result_id: formValue(form, "result_id"), student_ids: [...chosen] };
    };
    node.append(keyBanner() || "", ...toolForm([
      h("label", { class: "field" }, "Homework", select, h("span", { class: "hint" }, "Missing answers in its answer key are written first, from the textbook.")),
      h("fieldset", null, h("legend", null, "Students' work"), drop, reading, listBox, count),
      h("details", { class: "help" }, h("summary", null, "How should students lay out their answers?"),
        h("div", { class: "md" },
          h("p", null, "Number each answer like the homework: ", h("code", null, "1."), ", ", h("code", null, "2)"), ", ", h("code", null, "Q3"), " or ", h("code", null, "Answer 4:"), ". Copying the question first is fine."),
          h("p", null, "A line such as ", h("code", null, "Name: Asha Rao"), " sets the student's name. Otherwise the file name is used."),
          h("p", null, "If an answer lands under the wrong number, you can move it when you review."))),
    ], "Grade answers", params, "grade_answers"));
    return node;
  }

  function scoreChart(questions) {
    if (!questions.length) return null;
    const tip = h("div", { class: "tooltip", hidden: true, role: "tooltip" });
    const describe = (q) => "Average " + q.average + "% · " + plural(q.struggled, "student") + " below half marks";
    const showTip = (q) => (e) => {
      tip.textContent = "Q" + q.number + ": " + describe(q);
      tip.hidden = false;
      const box = e.currentTarget.getBoundingClientRect();
      tip.style.left = Math.min(box.left, innerWidth - 280) + "px";
      tip.style.top = Math.max(8, box.top - 40) + "px";
    };
    const hardest = [...questions].sort((x, y) => x.average - y.average)[0];
    const chart = h("div", { class: "coverage" }, questions.map((q) => {
      const bar = h("span", { class: "cov-bar" });
      bar.style.width = Math.max(q.average, 0) + "%";
      return h("div", { class: "cov-row", tabIndex: 0, "aria-label": "Question " + q.number + ": " + describe(q),
        onmouseenter: showTip(q), onfocus: showTip(q),
        onmouseleave: () => { tip.hidden = true; }, onblur: () => { tip.hidden = true; } },
        h("div", { class: "cov-head" }, h("span", null, "Q" + q.number + " · " + q.text.split("\n")[0]), h("b", null, q.average + "%")),
        h("div", { class: "cov-track" }, q.average ? bar : h("span", { class: "cov-none" }, icon("warn"), "No marks")));
    }));
    return h("section", { class: "card" }, h("h2", null, "Average score per question"),
      h("p", { class: "muted small-text" }, "Lowest: Q" + hardest.number + " at " + hardest.average + "%. Suggested marks count until you confirm them."),
      chart, tip,
      h("details", null, h("summary", null, "View as table"),
        h("table", { class: "data" },
          h("thead", null, h("tr", null, h("th", null, "Question"), h("th", { class: "num" }, "Average"), h("th", { class: "num" }, "Below half"))),
          h("tbody", null, questions.map((q) => h("tr", null, h("td", null, "Q" + q.number + " " + q.text.split("\n")[0]),
            h("td", { class: "num" }, q.average + "%"), h("td", { class: "num" }, String(q.struggled))))))));
  }

  function gradingPage(initial) {
    let result = initial;
    const id = result.id;
    let selected = "class";
    const node = h("div", { class: "page" });
    const summary = h("div");
    const side = h("nav", { class: "chat-list", "aria-label": "Students" });
    const pane = h("div", { class: "grid" });
    const title = h("input", { class: "title-input", type: "text", value: result.title, "aria-label": "Title", maxLength: 160,
      onchange: async () => {
        try { await api("/results/" + id, { method: "PATCH", json: { title: title.value } }); }
        catch (error) { failed(error); title.value = result.title; }
      } });

    async function patch(payload) {
      try {
        result = await api("/results/" + id, { method: "PATCH", json: payload });
        render();
        return true;
      } catch (error) { failed(error); return false; }
    }

    function textDialog(heading, current, label, onSave) {
      const area = h("textarea", { rows: 6, value: current, "aria-label": heading });
      dialog.replaceChildren(h("div", { class: "dialog-body" }, h("h2", null, heading), label && h("p", { class: "muted small-text" }, label), area,
        h("div", { class: "dialog-actions" },
          h("button", { class: "btn", type: "button", onclick: () => dialog.close() }, "Cancel"),
          h("button", { class: "btn primary", type: "button", onclick: () => { dialog.close(); onSave(area.value); } }, "Save"))));
      dialog.showModal();
      area.focus();
    }

    async function regrade(student, button) {
      const panel = progressPanel();
      button.replaceWith(panel.node);
      try {
        await runJob("regrade", { student_id: student.id }, panel.update, "/results/" + id + "/regrade");
        result = await api("/results/" + id);
        toast("Marked " + student.name);
      } catch (error) { failed(error); }
      render();
    }

    const questions = () => Object.fromEntries(result.data.questions.map((q) => [q.id, q]));
    const lineFor = (sid) => result.summary.students.find((s) => s.id === sid);

    function answerCard(student, entry, question) {
      const pending = entry.decision === "pending";
      const chips = [];
      const tone = { correct: ["good", "Correct"], partial: ["warn", "Partly correct"], incorrect: ["bad", "Incorrect"] }[entry.verdict];
      if (entry.flagged) chips.push(h("span", { class: "chip bad" }, icon("warn"), "Asks for marks or gives instructions"));
      if (tone && entry.graded) chips.push(h("span", { class: "chip " + tone[0] }, tone[1]));
      if (!entry.graded) chips.push(h("span", { class: "chip warn" }, "Not marked yet"));
      if (pending) chips.push(h("span", { class: "chip" }, "Needs your decision"));
      else chips.push(h("span", { class: "chip good" }, icon("yes"), entry.overridden ? "Your mark" : "Confirmed"));
      if (entry.edited) chips.push(h("span", { class: "chip info" }, "Answer edited"));

      const value = entry.decision === "accepted" ? entry.mark : entry.suggested;
      const input = h("input", { type: "number", class: "mark-input", min: 0, max: question.marks, step: 0.5,
        value: value === null ? "" : value, "aria-label": "Mark for question " + question.number });
      const save = () => {
        if (input.value === "") return toast("Enter a mark first.", "bad");
        patch({ student_id: student.id, question_id: question.id, mark: Number(input.value) });
      };
      input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); save(); } });
      return h("article", { class: "card item" + (entry.flagged && pending ? " flagged" : pending ? " pending" : ""), "aria-label": "Answer " + question.number },
        h("div", { class: "item-top" }, h("span", { class: "qnum" }, "Q" + question.number), h("div", { class: "chips grow" }, chips)),
        h("p", { class: "qtext muted" }, question.text),
        h("div", { class: "answer-box" }, h("span", { class: "tag" }, "Student's answer"),
          h("span", { class: "qtext" }, entry.answer || "No answer found under this number.")),
        entry.feedback && h("p", { class: "reason" }, entry.feedback),
        question.answer && h("details", null, h("summary", null, "Answer key"), h("div", { class: "source" }, markdown(question.answer))),
        sourcesBlock(entry.sources),
        h("div", { class: "actions mark-actions" },
          h("label", { class: "mark-field" }, input, h("span", null, "/ " + question.marks)),
          h("button", { class: "btn small primary", type: "button", onclick: save }, icon("yes"), pending ? "Confirm mark" : "Update mark"),
          !pending && h("button", { class: "btn ghost small", type: "button", onclick: () => patch({ student_id: student.id, question_id: question.id, decision: "pending" }) }, "Undo"),
          h("button", { class: "btn ghost small", type: "button", onclick: () => textDialog("Edit feedback", entry.feedback, null,
            (text) => patch({ student_id: student.id, question_id: question.id, feedback: text })) }, icon("edit"), "Feedback"),
          h("button", { class: "btn ghost small", type: "button", onclick: () => textDialog("Fix the student's answer", entry.answer,
            "Use this when an answer was matched to the wrong number. The answer will need marking again.",
            (text) => patch({ student_id: student.id, question_id: question.id, answer: text })) }, icon("edit"), "Fix answer")));
    }

    function studentPane(student) {
      const line = lineFor(student.id);
      const qs = questions();
      const parts = [];
      const unmarked = student.answers.filter((a) => !a.graded && a.decision === "pending").length;
      parts.push(h("div", { class: "card student-head" },
        h("div", { class: "row" },
          h("div", { class: "grow" }, h("h2", null, student.name), h("p", { class: "muted small-text" }, student.document)),
          h("button", { class: "btn ghost small", type: "button", onclick: () => textDialog("Rename student", student.name, null, (text) => patch({ student_id: student.id, name: text })) }, icon("edit"), "Rename"),
          h("button", { class: "btn ghost small icon-only", type: "button", title: "Remove student", "aria-label": "Remove " + student.name, onclick: async () => {
            if (!(await confirmDialog("Remove this student?", student.name + " will be removed from this grading. Their file stays in your library.", "Remove"))) return;
            selected = "class";
            patch({ student_id: student.id, delete: true });
          } }, icon("trash"))),
        student.error ? null : tiles([[line.score + " / " + line.max, "score"], [line.percent + "%", "percent"], [line.pending, "to confirm"]]),
        h("div", { class: "row" },
          line.pending ? h("button", { class: "btn small", type: "button", onclick: () => patch({ bulk: "accepted", student_id: student.id }) }, icon("yes"), "Confirm all suggested marks") : null,
          line.flagged ? h("span", { class: "muted small-text" }, plural(line.flagged, "flagged answer") + " must be confirmed one by one.") : null)));
      if (student.error || unmarked) {
        const button = h("button", { class: "btn small", type: "button", onclick: (e) => regrade(student, e.currentTarget) }, icon("spark"), student.error ? "Try again" : "Mark " + plural(unmarked, "answer"));
        parts.push(h("div", { class: "banner" + (student.error ? " bad" : ""), role: student.error ? "alert" : null }, icon("warn"),
          h("div", { class: "grow" }, student.error ? "This student's work couldn't be marked: " + student.error : plural(unmarked, "answer") + " still need marking."), button));
      }
      if (!student.numbered) {
        parts.push(h("div", { class: "banner" }, icon("warn"), h("div", null, "No numbered answers were found in this file, so every answer is empty. Check the file, or use Fix answer on each question.")));
      }
      if (student.unmatched) {
        parts.push(h("details", { class: "card" }, h("summary", null, "Text not matched to a question"), h("div", { class: "preview-box" }, student.unmatched)));
      }
      for (const entry of student.answers) parts.push(answerCard(student, entry, qs[entry.question_id]));
      return parts;
    }

    function classPane() {
      const rows = result.summary.students;
      return [
        h("section", { class: "card" }, h("h2", null, "Students"),
          h("table", { class: "data students" },
            h("thead", null, h("tr", null, h("th", null, "Student"), h("th", { class: "num" }, "Score"), h("th", { class: "num" }, "%"), h("th", { class: "num" }, "To confirm"))),
            h("tbody", null, rows.map((s) => h("tr", null,
              h("td", null, h("button", { class: "link-button", type: "button", onclick: () => { selected = s.id; render(); } }, s.name),
                s.flagged ? h("span", { class: "chip bad" }, icon("warn"), plural(s.flagged, "flag")) : null),
              h("td", { class: "num" }, s.error ? "Not marked" : s.score + " / " + s.max),
              h("td", { class: "num" }, s.error ? "–" : String(s.percent)),
              h("td", { class: "num" }, String(s.pending))))))),
        scoreChart(result.summary.questions) || "",
      ];
    }

    function exportCard() {
      const s = result.stats;
      return h("section", { class: "card" }, h("h2", null, "Export"),
        s.pending ? h("p", { class: "muted small-text" }, plural(s.pending, "mark") + " still to confirm. The Word report labels them as suggested; the spreadsheet leaves them blank.") : null,
        h("div", { class: "row" },
          h("a", { class: "btn primary", download: "", href: "/api/results/" + id + "/export" }, icon("download"), "Word report"),
          h("a", { class: "btn", download: "", href: "/api/results/" + id + "/export?format=csv" }, icon("download"), "Spreadsheet (CSV)")));
    }

    function render() {
      const s = result.stats;
      summary.replaceChildren(tiles([[s.students, "students"], [s.average + "%", "class average"], [s.pending, "marks to confirm"], [s.flagged, "flagged answers"]]));
      if (selected !== "class" && !result.data.students.some((st) => st.id === selected)) selected = "class";
      put(side,
        h("a", { href: "#", "aria-current": String(selected === "class"), onclick: (e) => { e.preventDefault(); selected = "class"; render(); } }, "Whole class"),
        result.summary.students.map((st) => h("a", { href: "#", "aria-current": String(selected === st.id), class: "student-link",
          onclick: (e) => { e.preventDefault(); selected = st.id; render(); window.scrollTo(0, 0); } },
          h("span", { class: "grow" }, st.name),
          h("span", { class: "chip" + (st.error ? " bad" : st.pending ? "" : " good") }, st.error ? "Failed" : st.pending ? st.pending + " left" : st.percent + "%"))));
      const student = result.data.students.find((st) => st.id === selected);
      put(pane, student ? studentPane(student) : classPane());
    }

    const bulkAll = h("button", { class: "btn small", type: "button", onclick: () => patch({ bulk: "accepted" }) }, icon("yes"), "Confirm all suggested marks");
    node.append(
      h("header", { class: "page-head" }, h("div", null,
        h("span", { class: "chip info" }, "Grading"), title,
        h("p", { class: "muted small-text" }, "Against ", h("a", { href: "#/result/" + result.data.homework_result_id }, result.data.homework_title)))),
      summary,
      result.stats.default_marks ? h("div", { class: "banner info" }, icon("warn"), h("div", null, "This homework has no marks set, so each question is worth 1 mark. Set marks on the homework and grade again to change this.")) : "",
      h("div", { class: "grade-layout" },
        h("div", { class: "grid sticky" }, h("div", { class: "card" }, side), h("div", { class: "card" }, bulkAll), exportCard()),
        pane));
    render();
    return node;
  }

  // ---------- question bank ----------
  async function bankPage() {
    const [listing] = await Promise.all([api("/bank"), loadDocuments()]);
    let questions = listing.questions;
    const node = page("Question bank", "Questions you chose to keep. Filter and tick them, or let the bank pick by topic and difficulty, then turn them into a new assignment.");
    if (!questions.length) {
      node.append(h("div", { class: "card" }, empty("bank", "Your bank is empty. Open any homework in History and choose Save to bank on the questions you like.",
        h("a", { class: "btn primary", href: "#/history" }, "Go to History"))));
      return node;
    }
    const chosen = new Set();
    const filters = { term: "", topic: "", difficulty: "" };
    const listCard = h("section", { class: "card" });
    const topicNames = () => [...new Set(questions.map((q) => q.topic).filter(Boolean))].sort((a, b) => a.localeCompare(b));
    const search = h("input", { type: "search", placeholder: "Search questions", "aria-label": "Search questions", oninput: () => { filters.term = search.value.trim().toLowerCase(); paint(); } });
    const topicSelect = h("select", { "aria-label": "Topic", onchange: () => { filters.topic = topicSelect.value; paint(); } });
    const diffSelect = h("select", { "aria-label": "Difficulty", onchange: () => { filters.difficulty = diffSelect.value; paint(); } },
      h("option", { value: "" }, "Any difficulty"), listing.difficulties.map((d) => h("option", { value: d }, d[0].toUpperCase() + d.slice(1))));

    function fillTopics() {
      const current = topicSelect.value;
      put(topicSelect, h("option", { value: "" }, "All topics"), topicNames().map((t) => h("option", { value: t }, t)));
      topicSelect.value = topicNames().includes(current) ? current : "";
    }

    function visible() {
      return questions.filter((q) => (!filters.topic || q.topic === filters.topic) && (!filters.difficulty || q.difficulty === filters.difficulty) &&
        (!filters.term || (q.text + " " + q.topic + " " + q.answer).toLowerCase().includes(filters.term)));
    }

    function editQuestion(q) {
      const text = h("textarea", { rows: 4, value: q.text, "aria-label": "Question" });
      const topic = h("input", { type: "text", value: q.topic, maxLength: 80, list: "bank-topics" });
      const diff = h("select", null, h("option", { value: "" }, "Not set"), listing.difficulties.map((d) => h("option", { value: d }, d)));
      diff.value = q.difficulty;
      const marks = h("input", { type: "number", min: 1, max: 100, value: q.marks || "" });
      const answer = h("textarea", { rows: 4, value: q.answer, "aria-label": "Answer" });
      const options = h("datalist", { id: "bank-topics" }, topicNames().map((t) => h("option", { value: t })));
      dialog.replaceChildren(h("div", { class: "dialog-body" }, h("h2", null, "Edit question"),
        h("label", { class: "field" }, "Question", text),
        h("div", { class: "grid three" }, h("label", { class: "field" }, "Topic", topic, options), h("label", { class: "field" }, "Difficulty", diff), h("label", { class: "field" }, "Marks", marks)),
        h("label", { class: "field" }, "Answer", answer),
        h("div", { class: "dialog-actions" },
          h("button", { class: "btn", type: "button", onclick: () => dialog.close() }, "Cancel"),
          h("button", { class: "btn primary", type: "button", onclick: async () => {
            try {
              const saved = await api("/bank/" + q.id, { method: "PATCH", json: { text: text.value, topic: topic.value, difficulty: diff.value, marks: marks.value || null, answer: answer.value } });
              Object.assign(q, saved);
              dialog.close();
              fillTopics();
              paint();
            } catch (error) { failed(error); }
          } }, "Save"))));
      dialog.showModal();
      text.focus();
    }

    function questionRow(q) {
      const box = h("input", { type: "checkbox", checked: chosen.has(q.id), "aria-label": "Use this question",
        onchange: () => {
          if (box.checked) chosen.add(q.id); else chosen.delete(q.id);
          box.closest(".bank-row").classList.toggle("chosen", box.checked);
          paintBuilder();
        } });
      const chips = [];
      if (q.topic) chips.push(h("span", { class: "chip info" }, q.topic));
      if (q.difficulty) chips.push(h("span", { class: "chip" }, q.difficulty));
      if (q.marks) chips.push(h("span", { class: "chip" }, plural(q.marks, "mark")));
      if (q.used) chips.push(h("span", { class: "chip" }, "Used " + (q.used === 1 ? "once" : q.used + " times")));
      return h("article", { class: "bank-row" + (chosen.has(q.id) ? " chosen" : "") },
        h("label", { class: "bank-check" }, box),
        h("div", { class: "grow bank-body" },
          h("p", { class: "qtext" }, q.text),
          q.options && q.options.length ? h("ol", { type: "a" }, q.options.map((o) => h("li", null, o))) : null,
          h("div", { class: "chips" }, chips),
          q.answer && h("details", null, h("summary", null, "Answer"), h("div", { class: "source" }, markdown(q.answer))),
          h("p", { class: "muted small-text" }, "From " + (q.origin ? q.origin.title : "an earlier homework") + (q.textbook ? " · " + q.textbook : ""))),
        h("div", { class: "bank-actions" },
          h("button", { class: "btn ghost small icon-only", type: "button", title: "Edit", "aria-label": "Edit question", onclick: () => editQuestion(q) }, icon("edit")),
          h("button", { class: "btn ghost small icon-only", type: "button", title: "Delete", "aria-label": "Delete question", onclick: async () => {
            if (!(await confirmDialog("Delete this question?", "It will be removed from the bank. Homework that already uses it keeps it.", "Delete"))) return;
            try {
              await api("/bank/" + q.id, { method: "DELETE" });
              questions = questions.filter((x) => x.id !== q.id);
              chosen.delete(q.id);
              fillTopics();
              paint();
            } catch (error) { failed(error); }
          } }, icon("trash"))));
    }

    function paint() {
      const rows = visible();
      const allTicked = rows.length && rows.every((q) => chosen.has(q.id));
      listCard.replaceChildren(
        h("div", { class: "row" }, h("span", { class: "muted small-text grow" }, rows.length === questions.length ? plural(questions.length, "question") : rows.length + " of " + plural(questions.length, "question")),
          rows.length ? h("button", { class: "btn ghost small", type: "button", onclick: () => {
            for (const q of rows) { if (allTicked) chosen.delete(q.id); else chosen.add(q.id); }
            paint();
          } }, allTicked ? "Untick these" : "Tick all shown") : null),
        rows.length ? h("div", { class: "list" }, rows.map(questionRow)) : empty("bank", "No questions match these filters."));
      paintBuilder();
    }

    // Builder: what's ticked, automatic picking and the optional top-up.
    const rules = [{ topic: "any", difficulty: "any", count: 5 }];
    let shortfall = [];
    const builder = h("form", { class: "card", novalidate: true, onsubmit: (e) => e.preventDefault() });
    const titleInput = h("input", { type: "text", placeholder: "Title (optional)", maxLength: 160, "aria-label": "Assignment title" });
    const topUp = h("input", { type: "checkbox" });
    const bookPicker = picker("Textbook for new questions", "textbook");
    const ruleBox = h("div", { class: "grid rules" });

    function paintRules() {
      ruleBox.replaceChildren(...rules.map((rule, index) => {
        const count = h("input", { type: "number", min: 1, max: 50, value: rule.count, "aria-label": "How many", oninput: () => { rule.count = Number(count.value) || 1; } });
        const topic = h("select", { "aria-label": "Topic", onchange: () => { rule.topic = topic.value; } },
          h("option", { value: "any" }, "Any topic"), topicNames().map((t) => h("option", { value: t }, t)));
        topic.value = rule.topic;
        const diff = h("select", { "aria-label": "Difficulty", onchange: () => { rule.difficulty = diff.value; } },
          h("option", { value: "any" }, "Any"), listing.difficulties.map((d) => h("option", { value: d }, d)));
        diff.value = rule.difficulty;
        return h("div", { class: "rule" }, count, diff, topic,
          rules.length > 1 && h("button", { class: "btn ghost small icon-only", type: "button", "aria-label": "Remove rule", title: "Remove rule",
            onclick: () => { rules.splice(index, 1); paintRules(); } }, icon("no")));
      }));
    }

    async function autoPick(button) {
      button.disabled = true;
      try {
        const out = await api("/bank/pick", { method: "POST", json: { rules, exclude: [...chosen] } });
        for (const qid of out.picked) chosen.add(qid);
        shortfall = out.shortfall;
        toast(out.picked.length ? "Picked " + plural(out.picked.length, "question") : "No more questions match those rules", out.picked.length ? null : "bad");
        paint();
      } catch (error) { failed(error); }
      button.disabled = false;
    }

    function paintBuilder() {
      const picked = questions.filter((q) => chosen.has(q.id));
      const marks = picked.reduce((sum, q) => sum + (q.marks || 0), 0);
      const missing = shortfall.reduce((sum, r) => sum + r.missing, 0);
      const pickButton = h("button", { class: "btn", type: "button", onclick: (e) => autoPick(e.currentTarget) }, icon("spark"), "Pick for me");
      const create = h("button", { class: "btn primary", type: "button", disabled: !picked.length && !(topUp.checked && missing) }, icon("plus"), "Create assignment");
      const slot = h("div");
      create.addEventListener("click", async () => {
        const params = { question_ids: [...chosen], title: titleInput.value };
        if (topUp.checked && missing) {
          params.top_up = shortfall.map((r) => ({ topic: r.topic, difficulty: r.difficulty, count: r.missing }));
          params.textbook_id = formValue(builder, "textbook_id");
          if (!params.textbook_id || params.textbook_id === "__upload") return toast("Choose a textbook for the new questions.", "bad");
        }
        const panel = progressPanel();
        slot.replaceChildren(panel.node);
        create.disabled = true;
        try {
          const output = await runJob("bank_assignment", params, panel.update);
          location.hash = "#/result/" + output.result_id;
        } catch (error) {
          slot.replaceChildren(h("div", { class: "banner bad", role: "alert" }, icon("warn"), h("div", null, error.message)));
          create.disabled = false;
        }
      });
      put(builder,
        h("h2", null, "New assignment"),
        tiles([[picked.length, "chosen"], [marks, "marks"]]),
        titleInput,
        h("details", { class: "picker-rules", open: !picked.length },
          h("summary", null, "Pick automatically"),
          h("p", { class: "muted small-text" }, "Least-used questions come first. This uses no AI."),
          ruleBox,
          h("div", { class: "row" },
            h("button", { class: "btn ghost small", type: "button", onclick: () => { rules.push({ topic: "any", difficulty: "any", count: 2 }); paintRules(); } }, icon("plus"), "Add rule"),
            pickButton)),
        missing ? h("div", { class: "banner" }, icon("warn"), h("div", { class: "grid" },
          h("span", null, "The bank is short of " + shortfall.map((r) => r.missing + " " + (r.difficulty === "any" ? "" : r.difficulty + " ") + "question" + (r.missing === 1 ? "" : "s") +
            (r.topic === "any" ? "" : " on " + r.topic)).join(", ") + "."),
          h("label", { class: "check-chip" }, topUp, "Write the missing ones with AI"))) : null,
        missing && topUp.checked ? bookPicker : null,
        h("div", { class: "row" }, create,
          picked.length ? h("button", { class: "btn ghost small", type: "button", onclick: () => { chosen.clear(); shortfall = []; paint(); } }, "Clear") : null),
        slot);
    }
    topUp.addEventListener("change", paintBuilder);

    fillTopics();
    paintRules();
    node.append(h("div", { class: "split" },
      h("div", { class: "grid" }, h("div", { class: "row filters" }, h("div", { class: "grow" }, search), topicSelect, diffSelect), listCard),
      h("div", { class: "grid sticky" }, builder)));
    paint();
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
  const routes = { "": homePage, library: libraryPage, check: checkPage, create: createPage, notes: notesPage, history: historyPage, bank: bankPage };
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
      else if (first === "grade") node = await gradePage(second);
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
