"use strict";

// ── helpers ───────────────────────────────────────────────────────────────────

function fmtBytes(n) {
  if (n === null || n === undefined) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 ** 2).toFixed(1)} MB`;
}

function statusTag(status) {
  const map = {
    OK: "tag-ok",
    LARGER: "tag-warn",
    FAILED: "tag-accent",
    SKIPPED: "tag-neutral",
    "DRY-RUN": "tag-neutral",
  };
  return `<span class="tag ${map[status] || "tag-neutral"}">${status}</span>`;
}

function numOrNull(id) {
  const v = document.getElementById(id).value;
  return v ? Number(v) : null;
}

async function postJSON(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `${res.status} ${res.statusText}`);
  }
  return res.json();
}

async function browsePath(mode, filetypes) {
  try {
    const res = await fetch("/api/browse", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode, filetypes: filetypes || null }),
    });
    if (res.status === 501) {
      return window.prompt(`tkinter is unavailable — enter a ${mode} path:`) || null;
    }
    if (!res.ok) return null;
    const data = await res.json();
    return data.path || null;
  } catch {
    return window.prompt(`Enter a ${mode} path:`) || null;
  }
}

async function browseFiles(filetypes) {
  try {
    const res = await fetch("/api/browse", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: "files", filetypes: filetypes || null }),
    });
    if (res.status === 501) {
      const path = window.prompt("tkinter is unavailable — enter a file path:");
      return path ? [path] : [];
    }
    if (!res.ok) return [];
    const data = await res.json();
    return data.paths || [];
  } catch {
    const path = window.prompt("Enter a file path:");
    return path ? [path] : [];
  }
}

function pathsSummary(paths) {
  if (!paths.length) return "not selected";
  if (paths.length <= 3) {
    return paths.map((p) => p.split(/[\\/]/).pop()).join(", ");
  }
  return `${paths.length} files selected`;
}

function subscribeJob(jobId, { onUpdate, onDone }) {
  const es = new EventSource(`/api/jobs/${jobId}/events`);
  es.onmessage = (evt) => {
    const payload = JSON.parse(evt.data);
    onUpdate(payload);
    if (payload.status === "done" || payload.status === "failed") {
      onDone(payload);
      es.close();
    }
  };
  es.onerror = () => es.close();
}

// Renders one block per unit of work so completion reads as discrete steps
// lighting up left-to-right, not just a percentage sweeping across a bar.

function initStepProgress(prefix, total) {
  const track = document.getElementById(`${prefix}-progress-steps`);
  track.innerHTML = "";
  track.setAttribute("role", "progressbar");
  track.setAttribute("aria-valuemin", "0");
  track.setAttribute("aria-valuenow", "0");
  track.setAttribute("aria-valuemax", String(total));
  for (let i = 0; i < total; i++) {
    track.appendChild(document.createElement("div")).className = "step";
  }
  document.getElementById(`${prefix}-progress-file`).textContent = "";
  document.getElementById(`${prefix}-progress-count`).textContent = `0 / ${total}`;
  document.getElementById(`${prefix}-progress`).hidden = false;
}

function updateStepProgress(prefix, payload) {
  const track = document.getElementById(`${prefix}-progress-steps`);
  const results = payload.results || [];
  const done = results.length;
  const running = payload.status === "running" || payload.status === "queued";

  // Some jobs (e.g. font weight-pin expansion) can reveal more steps than
  // were predicted up front: grow the bar rather than losing a step.
  const needed = done + (running ? 1 : 0);
  while (track.children.length < needed) {
    track.appendChild(document.createElement("div")).className = "step";
  }

  const steps = track.children;
  const activeIndex = running ? done : -1;
  for (let i = 0; i < steps.length; i++) {
    const step = steps[i];
    if (i < done) {
      const failed = results[i].status === "FAILED";
      step.classList.remove(failed ? "is-done" : "is-failed");
      step.classList.add(failed ? "is-failed" : "is-done");
      step.classList.remove("is-active");
    } else if (i === activeIndex) {
      if (!step.classList.contains("is-active")) step.classList.add("is-active");
    } else {
      step.classList.remove("is-active", "is-done", "is-failed");
    }
  }

  track.setAttribute("aria-valuemax", String(steps.length));
  track.setAttribute("aria-valuenow", String(done));
  document.getElementById(`${prefix}-progress-file`).textContent = payload.current_file || "";
  document.getElementById(`${prefix}-progress-count`).textContent = `${done} / ${steps.length}`;
}

function setButtonLoading(id, loading) {
  const btn = document.getElementById(id);
  btn.disabled = loading;
  btn.classList.toggle("is-loading", loading);
  btn.querySelector(".btn-label").textContent = loading ? "Optimizing" : "Optimize";
  // SVGElement.hidden doesn't reliably reflect to the content attribute in
  // every browser, so toggle visibility with a class instead of `.hidden`.
  btn.querySelector(".btn-icon-arrow").classList.toggle("is-hidden", loading);
  btn.querySelector(".btn-icon-spinner").classList.toggle("is-hidden", !loading);
}

function summaryText(payload) {
  const s = payload.summary || {};
  if (s.message) return s.message;
  const parts = [];
  if (s.net_saved) parts.push(`Net saved: ${fmtBytes(s.net_saved)}`);
  if (s.failures) parts.push(`${s.failures} failed`);
  if (payload.error) parts.push(payload.error);
  return parts.join(" · ");
}

function initQualitySlider(rangeId, labelId) {
  const range = document.getElementById(rangeId);
  const label = document.getElementById(labelId);
  range.addEventListener("input", () => {
    label.textContent = range.value;
  });
}

// ── tabs ──────────────────────────────────────────────────────────────────────

function initTabs() {
  const buttons = document.querySelectorAll(".tab-btn");
  buttons.forEach((btn) => {
    btn.addEventListener("click", () => {
      buttons.forEach((b) => b.setAttribute("aria-selected", "false"));
      btn.setAttribute("aria-selected", "true");
      document.querySelectorAll("[data-panel]").forEach((panel) => {
        panel.hidden = panel.dataset.panel !== btn.dataset.tab;
      });
    });
  });
}

// ── images tab ────────────────────────────────────────────────────────────────

let imgInputPaths = [];

function renderImgResults(results) {
  const body = document.getElementById("img-results-body");
  if (!results.length) {
    body.innerHTML = '<tr><td colspan="5" class="mono" style="opacity:0.5;">No results yet.</td></tr>';
    return;
  }
  body.innerHTML = results
    .map(
      (r) => `
    <tr>
      <td class="mono">${r.file}</td>
      <td class="mono">${fmtBytes(r.input_size)}</td>
      <td class="mono">${r.output_size != null ? fmtBytes(r.output_size) : "—"}</td>
      <td class="mono">${r.saved_pct != null ? r.saved_pct + "%" : "—"}</td>
      <td>${statusTag(r.status)}</td>
    </tr>`
    )
    .join("");
}

async function runImageJob() {
  if (!imgInputPaths.length) {
    alert("Choose one or more input files first.");
    return;
  }
  const body = {
    input: imgInputPaths,
    output: document.getElementById("img-output").value || null,
    quality: Number(document.getElementById("img-quality").value),
    format: document.querySelector('input[name="img-format"]:checked').value,
    max_width: numOrNull("img-max-width"),
    max_height: numOrNull("img-max-height"),
    keep_exif: document.getElementById("img-keep-exif").checked,
    overwrite: document.getElementById("img-overwrite").checked,
    dry_run: document.getElementById("img-dry-run").checked,
  };

  setButtonLoading("img-run", true);
  initStepProgress("img", imgInputPaths.length);
  renderImgResults([]);
  document.getElementById("img-summary").textContent = "";

  try {
    const { job_id } = await postJSON("/api/imgopt/jobs", body);
    subscribeJob(job_id, {
      onUpdate: (payload) => {
        renderImgResults(payload.results);
        updateStepProgress("img", payload);
      },
      onDone: (payload) => {
        setButtonLoading("img-run", false);
        updateStepProgress("img", payload);
        renderImgResults(payload.results);
        document.getElementById("img-summary").textContent = summaryText(payload);
      },
    });
  } catch (err) {
    setButtonLoading("img-run", false);
    document.getElementById("img-progress").hidden = true;
    alert(`Failed to start job: ${err.message}`);
  }
}

function initImagesTab() {
  initQualitySlider("img-quality", "img-quality-value");

  document.getElementById("img-dropzone").addEventListener("click", async () => {
    const filetypes = [["Images", "*.jpg *.jpeg *.png *.webp *.gif *.bmp *.tiff *.tif"]];
    const paths = await browseFiles(filetypes);
    if (paths.length) {
      imgInputPaths = paths;
      document.getElementById("img-input-path").textContent = pathsSummary(paths);
    }
  });

  document.getElementById("img-output-browse").addEventListener("click", async () => {
    const path = await browsePath("folder");
    if (path) document.getElementById("img-output").value = path;
  });

  document.getElementById("img-run").addEventListener("click", runImageJob);
}

// ── videos tab ────────────────────────────────────────────────────────────────

let vidInputPaths = [];

function renderVidResults(results) {
  const body = document.getElementById("vid-results-body");
  if (!results.length) {
    body.innerHTML = '<tr><td colspan="6" class="mono" style="opacity:0.5;">No results yet.</td></tr>';
    return;
  }
  body.innerHTML = results
    .map(
      (r) => `
    <tr>
      <td class="mono">${r.file}</td>
      <td class="mono">${fmtBytes(r.input_size)}</td>
      <td class="mono">${r.output_size != null ? fmtBytes(r.output_size) : "—"}</td>
      <td class="mono">${r.saved_pct != null ? r.saved_pct + "%" : "—"}</td>
      <td class="mono">${r.resolution || "—"}</td>
      <td>${statusTag(r.status)}</td>
    </tr>`
    )
    .join("");
}

async function runVideoJob() {
  if (!vidInputPaths.length) {
    alert("Choose one or more input files first.");
    return;
  }
  const body = {
    input: vidInputPaths,
    output: document.getElementById("vid-output").value || null,
    quality: Number(document.getElementById("vid-quality").value),
    speed: document.querySelector('input[name="vid-speed"]:checked').value,
    h265: document.querySelector('input[name="vid-codec"]:checked').value === "h265",
    max_width: numOrNull("vid-max-width"),
    overwrite: document.getElementById("vid-overwrite").checked,
    dry_run: document.getElementById("vid-dry-run").checked,
  };

  setButtonLoading("vid-run", true);
  initStepProgress("vid", vidInputPaths.length);
  renderVidResults([]);
  document.getElementById("vid-summary").textContent = "";

  try {
    const { job_id } = await postJSON("/api/vidopt/jobs", body);
    subscribeJob(job_id, {
      onUpdate: (payload) => {
        renderVidResults(payload.results);
        updateStepProgress("vid", payload);
      },
      onDone: (payload) => {
        setButtonLoading("vid-run", false);
        updateStepProgress("vid", payload);
        renderVidResults(payload.results);
        document.getElementById("vid-summary").textContent = summaryText(payload);
      },
    });
  } catch (err) {
    setButtonLoading("vid-run", false);
    document.getElementById("vid-progress").hidden = true;
    alert(`Failed to start job: ${err.message}`);
  }
}

function initVideosTab() {
  initQualitySlider("vid-quality", "vid-quality-value");

  document.getElementById("vid-dropzone").addEventListener("click", async () => {
    const filetypes = [["Videos", "*.mp4 *.mov"]];
    const paths = await browseFiles(filetypes);
    if (paths.length) {
      vidInputPaths = paths;
      document.getElementById("vid-input-path").textContent = pathsSummary(paths);
    }
  });

  document.getElementById("vid-output-browse").addEventListener("click", async () => {
    const path = await browsePath("folder");
    if (path) document.getElementById("vid-output").value = path;
  });

  document.getElementById("vid-run").addEventListener("click", runVideoJob);
}

// ── fonts tab ─────────────────────────────────────────────────────────────────

let fontsList = [];
let fontsDirValue = null;
let fontsConfigValue = null;
let fontsDirOverride = null;
let fontsConfigOverride = null;
let fontsTextFile = null;

function fontExt(path) {
  const m = /\.([a-z0-9]+)$/i.exec(path);
  return m ? m[1].toLowerCase() : "";
}

function renderFontsTable() {
  const body = document.getElementById("fonts-table-body");
  const runBtn = document.getElementById("fonts-run");

  if (!fontsList.length) {
    body.innerHTML = '<tr><td colspan="8" class="mono" style="opacity:0.5;">No fonts found in this folder.</td></tr>';
    runBtn.disabled = true;
    return;
  }

  body.innerHTML = fontsList
    .map((f, i) => {
      const ext = fontExt(f.font_path);
      const defaultChecked = ext === "ttf";
      const defaultOverride = f.weight_min === f.weight_max ? f.weight_min : `${f.weight_min}-${f.weight_max}`;
      const statusCls = f.status === "UP_TO_DATE" ? "tag-ok" : "tag-warn";
      return `
      <tr>
        <td><label class="checkbox-row" style="justify-content:center;"><input type="checkbox" class="fonts-include" data-idx="${i}" ${defaultChecked ? "checked" : ""} /><span class="checkbox-box"></span></label></td>
        <td class="mono">${f.basename}</td>
        <td>${f.family_name}</td>
        <td class="mono">${f.weight_min}</td>
        <td class="mono">${f.weight_max}</td>
        <td class="mono">${f.opsz || "—"}</td>
        <td><input class="input mono fonts-weight-override" data-idx="${i}" style="min-height:30px;font-size:13px;width:120px;" value="${defaultOverride}" /></td>
        <td><span class="tag ${statusCls}">${f.status}</span></td>
      </tr>`;
    })
    .join("");

  runBtn.disabled = false;
}

async function scanFonts(dir) {
  const params = new URLSearchParams();
  if (dir) params.set("dir", dir);
  if (fontsDirOverride) params.set("fonts_dir", fontsDirOverride);
  if (fontsConfigOverride) params.set("config", fontsConfigOverride);

  try {
    const res = await fetch(`/api/fontslice/scan?${params.toString()}`);
    if (!res.ok) {
      const detail = await res.json().catch(() => ({}));
      alert(`Scan failed: ${detail.detail || res.statusText}`);
      return;
    }
    const data = await res.json();
    fontsDirValue = data.fonts_dir;
    fontsConfigValue = data.config_path;
    fontsList = data.fonts;
    document.getElementById("fonts-dir-display").textContent = fontsDirValue;
    document.getElementById("fonts-config-display").textContent =
      fontsConfigValue === "NONE" ? "not found" : fontsConfigValue;
    renderFontsTable();
  } catch (err) {
    alert(`Scan failed: ${err.message}`);
  }
}

function selectedFonts() {
  const rows = [];
  document.querySelectorAll(".fonts-include").forEach((cb) => {
    if (!cb.checked) return;
    const idx = Number(cb.dataset.idx);
    const font = fontsList[idx];
    const overrideInput = document.querySelector(`.fonts-weight-override[data-idx="${idx}"]`);
    rows.push({
      font_path: font.font_path,
      basename: font.basename,
      family_name: font.family_name,
      weight_min: font.weight_min,
      weight_max: font.weight_max,
      opsz: font.opsz || "",
      weight_override: overrideInput.value || null,
    });
  });
  return rows;
}

function selectedSubsets() {
  return Array.from(document.querySelectorAll('#fonts-subsets input[type="checkbox"]:checked'))
    .map((cb) => cb.value)
    .filter((v) => v !== "all");
}

function renderFontsResults(results) {
  const card = document.getElementById("fonts-results-card");
  const body = document.getElementById("fonts-results-body");
  card.hidden = false;
  body.innerHTML = results
    .map(
      (r) => `
    <tr>
      <td class="mono">${r.file}</td>
      <td class="mono">${fmtBytes(r.input_size)}</td>
      <td class="mono">${r.output_size != null ? fmtBytes(r.output_size) : "—"}</td>
      <td class="mono">${r.saved_pct != null ? r.saved_pct + "%" : "—"}</td>
      <td>${statusTag(r.status)}</td>
    </tr>`
    )
    .join("");
}

async function runFontsJob() {
  const fonts = selectedFonts();
  if (!fonts.length) {
    alert("Select at least one font.");
    return;
  }

  const body = {
    fonts_dir: fontsDirOverride || fontsDirValue,
    fonts,
    subsets: fontsTextFile ? null : selectedSubsets(),
    text_file: fontsTextFile,
  };

  setButtonLoading("fonts-run", true);
  initStepProgress("fonts", fonts.length);
  renderFontsResults([]);
  document.getElementById("fonts-summary").textContent = "";

  try {
    const { job_id } = await postJSON("/api/fontslice/jobs", body);
    subscribeJob(job_id, {
      onUpdate: (payload) => {
        renderFontsResults(payload.results);
        updateStepProgress("fonts", payload);
      },
      onDone: (payload) => {
        setButtonLoading("fonts-run", false);
        updateStepProgress("fonts", payload);
        renderFontsResults(payload.results);
        document.getElementById("fonts-summary").textContent = summaryText(payload);
        if (payload.summary && payload.summary.font_face_css) {
          document.getElementById("fontcss-code").textContent = payload.summary.font_face_css;
        }
      },
    });
  } catch (err) {
    setButtonLoading("fonts-run", false);
    document.getElementById("fonts-progress").hidden = true;
    alert(`Failed to start job: ${err.message}`);
  }
}

function initFontsTab() {
  document.getElementById("fonts-dropzone").addEventListener("click", async () => {
    const path = await browsePath("folder");
    if (path) {
      fontsDirOverride = null;
      fontsConfigOverride = null;
      await scanFonts(path);
    }
  });

  document.getElementById("fonts-override-dir").addEventListener("click", async () => {
    const path = await browsePath("folder");
    if (path) {
      fontsDirOverride = path;
      await scanFonts(null);
    }
  });

  document.getElementById("fonts-override-config").addEventListener("click", async () => {
    const path = await browsePath("file", [["SCSS", "*.scss"]]);
    if (path) {
      fontsConfigOverride = path;
      await scanFonts(null);
    }
  });

  document.getElementById("fonts-textfile-browse").addEventListener("click", async () => {
    const path = await browsePath("file", [["Text files", "*.txt"]]);
    if (path) {
      fontsTextFile = path;
      document.getElementById("fonts-textfile-display").textContent = path;
      document.getElementById("fonts-textfile-clear").hidden = false;
    }
  });

  document.getElementById("fonts-textfile-clear").addEventListener("click", () => {
    fontsTextFile = null;
    document.getElementById("fonts-textfile-display").textContent = "no file selected";
    document.getElementById("fonts-textfile-clear").hidden = true;
  });

  document.getElementById("fonts-subset-all").addEventListener("change", (e) => {
    document.querySelectorAll('#fonts-subsets input[type="checkbox"]').forEach((cb) => {
      if (cb.id !== "fonts-subset-all") cb.checked = e.target.checked;
    });
  });

  document.getElementById("fontcss-toggle").addEventListener("click", () => {
    const panel = document.getElementById("fontcss-panel");
    panel.hidden = !panel.hidden;
    document.getElementById("fontcss-chevron").style.transform = panel.hidden ? "" : "rotate(180deg)";
  });

  document.getElementById("fontcss-copy").addEventListener("click", () => {
    const text = document.getElementById("fontcss-code").textContent;
    navigator.clipboard.writeText(text);
  });

  document.getElementById("fonts-run").addEventListener("click", runFontsJob);
}

// ── init ──────────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  initTabs();
  initImagesTab();
  initVideosTab();
  initFontsTab();
});
