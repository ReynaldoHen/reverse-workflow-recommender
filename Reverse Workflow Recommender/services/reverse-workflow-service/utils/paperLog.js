const LINE = "═".repeat(72);
const SUB  = "─".repeat(72);

function banner(tag) {
  console.log("\n" + LINE);
  console.log(tag);
  console.log(LINE);
}
function endblock() { console.log(LINE + "\n"); }

function summarizeParams(parameters, maxLen = 80) {
  if (!Array.isArray(parameters) || parameters.length === 0) return "(tanpa parameter)";
  const parts = [];
  for (const p of parameters) {
    const name = (p && p.name) ? String(p.name) : "?";
    if (/large_image/i.test(name)) continue;
    let v = p ? p.value : "";
    if (typeof v !== "string") { try { v = JSON.stringify(v); } catch { v = String(v); } }
    v = String(v).replace(/\s+/g, " ").trim();
    if (v === "") continue;
    if (v.length > 36) v = v.slice(0, 36) + "…";
    parts.push(`${name}=${v}`);
  }
  let s = parts.join("; ");
  if (s === "") return "(tanpa parameter)";
  if (s.length > maxLen) s = s.slice(0, maxLen) + "…";
  return s;
}

function truncateMiddle(str, head = 1000, tail = 380) {
  const s = String(str || "");
  if (s.length <= head + tail + 40) return s;
  const omitted = s.length - head - tail;
  return s.slice(0, head) + `\n\n…[${omitted} karakter dihilangkan]…\n\n` + s.slice(-tail);
}

function logParsing(workflowName, nodes, edges) {
  const byId = {};
  (nodes || []).forEach(n => { byId[n.id] = n; });

  const nextMap = {};
  (edges || []).forEach(e => {
    const tgt = byId[e.target];
    const name = tgt ? (tgt.action_name || tgt.label || e.target) : e.target;
    (nextMap[e.source] = nextMap[e.source] || []).push(name);
  });

  banner(`[4.2.3] HASIL PARSING WORKFLOW — ${workflowName}  (${(nodes || []).length} action)`);
  console.log("| Action ID | App | Action | Parameter | Next Action |");
  console.log("|---|---|---|---|---|");
  (nodes || []).forEach(n => {
    const id   = n.id || "-";
    const app  = n.app_name || "-";
    const act  = n.action_name || n.label || "-";
    const par  = summarizeParams(n.parameters);
    const next = (nextMap[n.id] && nextMap[n.id].length) ? nextMap[n.id].join(", ") : "(end)";
    console.log(`| ${id} | ${app} | ${act} | ${par} | ${next} |`);
  });
  endblock();
}

function logPromptAndOutput(prompt, workflow) {
  banner("[4.2.5] HASIL PROMPT DAN OUTPUT LLM");

  console.log(SUB);
  console.log("PROMPT (ringkas):");
  console.log(SUB);
  if (prompt) {
    console.log(truncateMiddle(prompt));
  } else {
    console.log("(prompt tidak tersedia — LLM tidak dipanggil pada kasus ini)");
  }

  console.log("\n" + SUB);
  console.log("OUTPUT REVERSE WORKFLOW (ringkas):");
  console.log(SUB);
  const acts = (workflow && Array.isArray(workflow.actions)) ? workflow.actions : [];
  console.log(`Nama       : ${workflow ? workflow.name : "-"}`);
  console.log(`Start node : ${workflow ? (workflow.start || "(action pertama)") : "-"}`);
  console.log(`Jumlah     : ${acts.length} action, ${(workflow && workflow.comments ? workflow.comments.length : 0)} komentar`);
  console.log("| # | App | Action | Parameter (ringkas) | Manual? |");
  console.log("|---|---|---|---|---|");
  acts.forEach((a, i) => {
    const manual = a.requires_manual_review ? "ya" : "-";
    console.log(`| ${i + 1} | ${a.app_name || "-"} | ${a.name || "-"} | ${summarizeParams(a.parameters)} | ${manual} |`);
  });
  endblock();
}

function logValidationStart(validation) {
  banner("[4.2.6] HASIL VALIDASI WORKFLOW");

  const errs = (validation && Array.isArray(validation.errors)) ? validation.errors : [];
  const structural = errs.filter(e => e.level === "structural");
  const semantic   = errs.filter(e => e.level === "semantic");

  const printLevel = (label, list) => {
    const status = list.length === 0 ? "PASS" : "FAIL";
    console.log(`${label} : ${status}`);
    list.forEach(e => {
      console.log(`    - [${e.code}] ${e.message}` + (e.location ? `  (lokasi: ${e.location})` : ""));
    });
  };

  printLevel("[A] Structural Validation", structural);
  printLevel("[B] Semantic Validation  ", semantic);
}

function logImportResult(ok, info) {
  if (ok) {
    console.log(`[Import] Import Validation : SUCCESS`);
    console.log(`    - workflow_id : ${info && info.id ? info.id : "-"}`);
    console.log(`    - nama        : ${info && info.name ? info.name : "-"}`);
  } else {
    console.log(`[Import] Import Validation : FAILED`);
    console.log(`    - alasan : ${info || "-"}`);
  }
  endblock();
}

module.exports = {
  summarizeParams,
  logParsing,
  logPromptAndOutput,
  logValidationStart,
  logImportResult,
};
