"use strict";

const el = (id) => document.getElementById(id);
const q = (selector) => document.querySelector(selector);
const format = new Intl.NumberFormat("zh-CN");
const node = (tag, label) => {
  const item = document.createElement(tag);
  if (label !== undefined) item.textContent = label;
  return item;
};

const labels = {
  route: "缩略扫描",
  whole: "整页读取",
  focus: "局部补读",
  confirm: "数字核验",
  "pdf-line": "PDF 候选核验",
};
const statusLabels = {
  conflict: "同一字段读到不同数值",
  needs_review: "仍有候选需要核验",
  answered: "证据齐全",
  partial: "只找到部分证据",
  unresolved: "证据不足",
};

let fixtures = [];
let current = null;
let selectedEvidence = null;
let selectedStep = null;

function switchSource() {
  const own = q('input[name="source"]:checked').value === "files";
  el("file-panel").hidden = !own;
  el("example-panel").hidden = own;
  el("files").required = own;
  switchOperation();
}

function switchOperation() {
  const op = el("op").value;
  const own = !el("file-panel").hidden;
  const numeric = ["extract", "compare", "difference"].includes(op);
  const second = ["verify", "compare", "difference"].includes(op);
  el("field-b").hidden = !second;
  el("numbers-a").hidden = !numeric;
  el("numbers-b").hidden = !numeric;
  el("unit-panel").hidden = !numeric;
  el("anchor-a").required = own;
  el("anchor-b").required = own && second;
  for (const side of ["a", "b"]) {
    for (const control of ["window", "ordinal", "direction"]) {
      el(control + "-" + side).disabled = !own || !numeric || (side === "b" && !second);
    }
  }
}

function exampleDescription() {
  const fixture = fixtures.find((row) => row.id === el("example").value);
  el("example-description").textContent = fixture ? fixture.description : "";
}

function showMessage(title, detail, error = false) {
  el("message").replaceChildren(node("h2", title), node("p", detail));
  el("message").classList.toggle("error", error);
  el("message").hidden = false;
  el("results").hidden = true;
}

function fileData(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => resolve({name: file.name, data: String(reader.result).split(",")[1]}));
    reader.addEventListener("error", () => reject(new Error("无法读取文件 " + file.name)));
    reader.readAsDataURL(file);
  });
}

function field(side, op) {
  const output = {anchor: el("anchor-" + side).value};
  const scope = el("scope-" + side).value.trim();
  if (scope) output.pages = scope.split(",").map((value) => value.trim()).filter(Boolean);
  if (["extract", "compare", "difference"].includes(op)) {
    output.direction = el("direction-" + side).value;
    output.window = el("window-" + side).valueAsNumber;
    output.ordinal = el("ordinal-" + side).valueAsNumber;
  }
  return output;
}

async function makeRequest() {
  const shared = {budget: el("budget").valueAsNumber, strategy: el("strategy").value};
  if (!el("example-panel").hidden) {
    if (!el("example").value) throw new Error("请选择样例");
    return {...shared, example: el("example").value};
  }
  const files = Array.from(el("files").files);
  if (!files.length || files.length > 24) throw new Error("请选择 1–24 个文件");
  if (files.some((f) => f.size > 16 * 1024 * 1024) ||
      files.reduce((sum, f) => sum + f.size, 0) > 32 * 1024 * 1024) {
    throw new Error("单个文件最多 16 MiB，单次合计最多 32 MiB");
  }
  const op = el("op").value;
  const fields = [field("a", op)];
  if (!el("field-b").hidden) fields.push(field("b", op));
  const unit = !el("unit-panel").hidden ? el("unit").value : "";
  return {...shared, pages: el("pages").value, task: {op, fields, unit},
    files: await Promise.all(files.map(fileData))};
}

function resultText(result) {
  const value = result.answer;
  if (result.status === "conflict") return ["字段存在数值冲突", "查看各处原文后，用字段页面 ID 或更完整的锚点限定所需记录。"];
  if (result.status === "needs_review") return ["候选核验尚未完成", "部分候选未读清或超过预算，请核对现有证据并限定任务范围。"];
  if (!value) return ["等待更多证据", "本次读取范围内只显示已经核对的内容。"];
  const unit = value.unit ? " " + value.unit : "";
  switch (result.op) {
    case "locate": return ["定位到原文", "页码和锚点位置见证据区。"];
    case "verify": return ["已定位两处证据", "点开任一证据，查看来源页和命中的文字。"];
    case "extract": return [value.value + unit, "原文数值已定位。"];
    case "compare":
      return [value.larger === "equal" ? "两值相等" : "字段 " + value.larger + " 较大",
        "A = " + value.values[0] + unit + " · B = " + value.values[1] + unit];
    case "difference":
      return ["差值 " + value.difference + unit,
        "A = " + value.values[0] + unit + " · B = " + value.values[1] + unit];
    default: return ["取证完成", ""];
  }
}

function evidenceBox(coords, dimensions, numeric, selected) {
  const [x0, y0, x1, y1] = coords;
  const [width, height] = dimensions;
  const box = node("div");
  box.className = "box" + (numeric ? " value" : "") + (selected ? " selected" : "");
  box.style.left = 100 * x0 / width + "%";
  box.style.top = 100 * y0 / height + "%";
  box.style.width = 100 * (x1 - x0) / width + "%";
  box.style.height = 100 * (y1 - y0) / height + "%";
  return box;
}

function showPage(pageId) {
  const result = current.result;
  const visibleEvidence = [...result.evidence, ...Object.values(result.field_assessments ?? {}).filter((item) => item.status !== "accepted").flatMap((item) => item.evidence)];
  const page = result.pages.find((item) => item.id === pageId);
  if (!page) return;
  el("page-select").value = page.id;
  el("page-image").src = current.previews[page.id];
  el("page-image").alt = page.name;
  const boxes = [];
  for (const evidence of visibleEvidence.filter((item) => item.page === page.id)) {
    const selected = evidence.field === selectedEvidence;
    boxes.push(evidenceBox(evidence.anchor_box, page.size, false, selected));
    if (evidence.value_box) boxes.push(evidenceBox(evidence.value_box, page.size, true, selected));
  }
  el("boxes").replaceChildren(...boxes);
  for (const button of el("evidence").querySelectorAll("button")) {
    button.setAttribute("aria-pressed", String(button.dataset.field === selectedEvidence));
  }
}

function showStep(index, jump) {
  const step = current.result.steps[index];
  if (!step) return;
  selectedStep = index;
  for (const button of el("steps").querySelectorAll("button")) {
    button.setAttribute("aria-pressed", String(Number(button.dataset.index) === selectedStep));
  }
  const [width, height] = step.size;
  el("view-caption").textContent = "第 " + step.step + " 步 · " + width + " × " + height + " · "
    + step.ocr_lines + " 行 OCR · " + step.reason;
  el("view-image").src = current.views[index];
  el("view-figure").hidden = false;
  if (jump) showPage(step.page);
}

function render(payload) {
  current = payload;
  const result = payload.result;
  const visibleEvidence = [...result.evidence, ...Object.values(result.field_assessments ?? {}).filter((item) => item.status !== "accepted").flatMap((item) => item.evidence)];
  selectedEvidence = result.evidence[0]?.field ?? null;
  el("message").hidden = true;
  el("results").hidden = false;
  el("status").textContent = statusLabels[result.status];
  el("status").dataset.state = result.status;
  const [title, meta] = resultText(result);
  el("answer").textContent = title;
  el("answer-meta").textContent = meta;
  const ambiguous = result.possible_ambiguities;
  el("ambiguities").hidden = !ambiguous.length;
  el("ambiguities").textContent = ambiguous.length
    ? "字段 " + ambiguous.join("、") + " 还有其他 PDF 候选。锚点重复时，可补充上下文或缩小页码范围。"
    : "";
  el("pixel-count").textContent = format.format(result.spent) + " / " + format.format(result.budget);
  el("call-count").textContent = format.format(result.ocr_calls);
  el("duration").textContent = (payload.request_ms / 1000).toFixed(2) + " s";
  const percent = Math.min(100, 100 * result.spent / result.budget);
  el("bar").setAttribute("aria-valuenow", String(Math.round(percent)));
  q("#bar span").style.width = percent + "%";
  const pages = new Map(result.pages.map((item) => [item.id, item.name]));
  el("page-select").replaceChildren(...result.pages.map((item) => {
    const option = node("option", item.name + " · " + item.id);
    option.value = item.id;
    return option;
  }));
  el("evidence").replaceChildren(...visibleEvidence.map((item) => {
    const button = node("button");
    button.type = "button";
    button.dataset.field = item.field;
    const summary = item.field + " · " + pages.get(item.page) + " · " + item.page
      + (item.value === null ? "" : " · " + item.value)
      + (item.revised_from === undefined ? "" : "（核验前 " + item.revised_from + "）");
    button.append(node("strong", summary), node("span", item.line));
    button.addEventListener("click", () => {
      selectedEvidence = item.field;
      showPage(item.page);
      showStep(result.steps.findIndex((step) => step.page === item.page && step.view === item.view), false);
    });
    return button;
  }));
  el("trace-total").textContent = format.format(result.steps.length) + " 步";
  el("steps").replaceChildren(...result.steps.map((step, index) => {
    const button = node("button");
    button.className = "step";
    button.type = "button";
    button.dataset.index = String(index);
    button.append(node("b", String(step.step).padStart(2, "0")),
      node("span", (labels[step.mode] ?? step.mode) + " · " + pages.get(step.page)),
      node("small", format.format(step.pixels) + " px"));
    button.addEventListener("click", () => showStep(index, true));
    return button;
  }));
  showPage(result.evidence[0]?.page ?? result.pages[0].id);
  const last = result.evidence[0];
  const matching = last ? result.steps.findIndex((step) => step.page === last.page && step.view === last.view) : -1;
  if (result.steps.length) showStep(Math.max(0, matching), false);
  else el("view-figure").hidden = true;
}

async function submit(event) {
  event.preventDefault();
  el("run").disabled = true;
  showMessage("正在读取文档", "本机 OCR 会逐次读取页面和局部区域。");
  try {
    const request = await makeRequest();
    const response = await fetch("/api/search", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(request),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error ?? "请求失败");
    render(data);
  } catch (error) {
    showMessage("这次运行未完成", error.message, true);
  } finally {
    el("run").disabled = false;
  }
}

function download() {
  if (!current) return;
  const bytes = new Blob([JSON.stringify({task: current.task, ...current.result}, null, 2)], {type: "application/json"});
  const url = URL.createObjectURL(bytes);
  const link = node("a");
  link.href = url;
  link.download = "document-evidence.json";
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 3000);
}

el("request").addEventListener("submit", submit);
el("request").addEventListener("change", (event) => {
  if (event.target.name === "source") switchSource();
  if (event.target.id === "op") switchOperation();
  if (event.target.id === "example") exampleDescription();
});
el("page-select").addEventListener("change", (event) => {
  selectedEvidence = null;
  showPage(event.target.value);
});
el("download").addEventListener("click", download);
switchSource();
fetch("/api/examples").then(async (response) => {
  if (!response.ok) throw new Error("样例加载失败");
  const data = await response.json();
  fixtures = data.examples;
  el("example").replaceChildren(...fixtures.map((row) => {
    const item = node("option", row.label);
    item.value = row.id;
    return item;
  }));
  el("strategy").value = data.strategy;
  el("budget").value = data.budget;
  exampleDescription();
}).catch((error) => showMessage("无法加载样例", error.message, true));
