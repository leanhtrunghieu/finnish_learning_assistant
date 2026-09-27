import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { Presentation, PresentationFile } from "@oai/artifact-tool";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const workspaceDir = path.resolve(scriptDir, "../..");
const SKILL_DIR = process.env.PRESENTATIONS_SKILL_DIR;
const TMP_DIR = path.join(workspaceDir, "tmp/phase12_presentation");
const FINAL_PPTX = path.join(workspaceDir, "docs/presentation/final_presentation.pptx");
const RUNTIME_PYTHON = process.env.RUNTIME_PYTHON;

if (!SKILL_DIR || !RUNTIME_PYTHON || !process.env.RUNTIME_NODE || !process.env.RUNTIME_NODE_MODULES) {
  throw new Error(
    "Set PRESENTATIONS_SKILL_DIR, RUNTIME_PYTHON, RUNTIME_NODE, and RUNTIME_NODE_MODULES before rebuilding the deck.",
  );
}

const { applyPresentationChartFont, finalizePresentation, makeNativeBulletParagraphs } = await import(
  pathToFileURL(path.join(SKILL_DIR, "container_tools/artifact_tool_utils.mjs")).href,
);

await fs.mkdir(TMP_DIR, { recursive: true });
await fs.mkdir(path.dirname(FINAL_PPTX), { recursive: true });

const report = JSON.parse(
  await fs.readFile(path.join(workspaceDir, "reports/final_evaluation_v1.json"), "utf8"),
);

const FONT = "Segoe UI";
const C = {
  ink: "#13213C",
  blue: "#155EEF",
  ice: "#EAF2FF",
  sky: "#6EA8FE",
  mint: "#DDF7EA",
  green: "#0A7A4B",
  coral: "#F05B5B",
  gold: "#E9A23B",
  paper: "#F8FAFC",
  white: "#FFFFFF",
  gray: "#5F6B7A",
  line: "#CBD5E1",
  light: "#EEF2F7",
};

const presentation = Presentation.create({ slideSize: { width: 1280, height: 720 } });

function box(slide, left, top, width, height, fill = C.white, radius = 18, line = "none") {
  return slide.shapes.add({
    geometry: "rect",
    position: { left, top, width, height },
    fill,
    line: line === "none" ? { fill: "none", width: 0 } : { fill: line, width: 1 },
    borderRadius: radius,
  });
}

function textBox(slide, text, left, top, width, height, options = {}) {
  const shape = slide.shapes.add({
    geometry: "textbox",
    position: { left, top, width, height },
    fill: options.fill ?? "none",
    line: { fill: "none", width: 0 },
  });
  shape.text = text;
  shape.text.style = {
    typeface: FONT,
    fontSize: options.size ?? 22,
    bold: options.bold ?? false,
    color: options.color ?? C.ink,
    autoFit: "none",
    textAlign: options.align ?? "left",
    verticalAlignment: options.valign ?? "middle",
  };
  return shape;
}

function addTitle(slide, title, subtitle = null, section = null) {
  if (section) textBox(slide, section.toUpperCase(), 72, 28, 400, 30, { size: 14, bold: true, color: C.blue });
  textBox(slide, title, 72, section ? 56 : 44, 1136, 60, { size: 34, bold: true });
  if (subtitle) textBox(slide, subtitle, 72, section ? 114 : 104, 1080, 36, { size: 18, color: C.gray });
}

function addFooter(slide, number, source = "") {
  slide.shapes.add({
    geometry: "line",
    position: { left: 72, top: 680, width: 1136, height: 0 },
    fill: "none",
    line: { fill: C.line, width: 1 },
  });
  if (source) textBox(slide, source, 72, 684, 980, 22, { size: 11, color: C.gray });
  textBox(slide, String(number).padStart(2, "0"), 1140, 684, 68, 22, { size: 12, bold: true, color: C.blue, align: "right" });
}

function addBullets(slide, items, left, top, width, height, options = {}) {
  const shape = slide.shapes.add({
    geometry: "textbox",
    position: { left, top, width, height },
    fill: "none",
    line: { fill: "none", width: 0 },
  });
  shape.text = makeNativeBulletParagraphs(items, {
    marginLeftPoints: options.marginLeft ?? 18,
    hangingPoints: options.hanging ?? 9,
    spaceAfterPoints: options.spaceAfter ?? 10,
  });
  shape.text.style = {
    typeface: FONT,
    fontSize: options.size ?? 21,
    color: options.color ?? C.ink,
    autoFit: "none",
  };
  return shape;
}

async function addImage(slide, relPath, position, alt, fit = "cover", crop = undefined) {
  const bytes = await fs.readFile(path.join(workspaceDir, relPath));
  return slide.images.add({
    blob: bytes,
    contentType: "image/png",
    alt,
    fit,
    position,
    ...(crop ? { crop } : {}),
    geometry: "roundRect",
    borderRadius: 18,
  });
}

function note(slide, text) {
  slide.speakerNotes.textFrame.setText(text);
}

// Slide 1
{
  const slide = presentation.slides.add();
  slide.background.fill = C.paper;
  box(slide, 0, 0, 1280, 720, C.ink, 0);
  box(slide, 760, 0, 520, 720, C.blue, 0);
  textBox(slide, "FINNISH LEARNING ASSISTANT", 80, 184, 640, 120, { size: 44, bold: true, color: C.white });
  textBox(slide, "Grammar feedback that becomes targeted practice", 80, 310, 620, 74, { size: 25, color: "#D7E4FF" });
  textBox(slide, "Final project presentation", 82, 510, 420, 34, { size: 17, bold: true, color: C.sky });
  textBox(slide, "AI-assisted Finnish learning loop", 816, 250, 380, 54, { size: 26, bold: true, color: C.white, align: "center" });
  textBox(slide, "WRITE\nCHECK\nUNDERSTAND\nPRACTICE", 850, 330, 310, 210, { size: 23, bold: true, color: C.white, align: "center" });
  note(slide, "Introduce the project as a local educational MVP that connects grammar checking, history, weakness detection, vocabulary, and targeted practice.");
}

// Slide 2
{
  const slide = presentation.slides.add();
  slide.background.fill = C.paper;
  addTitle(slide, "Finnish learners need more than a correction", "The learning problem is recurring structure, not a single typo", "Problem");
  textBox(slide, "15", 82, 184, 190, 110, { size: 82, bold: true, color: C.blue });
  textBox(slide, "productive cases", 84, 288, 220, 38, { size: 20, bold: true });
  textBox(slide, "Rich inflection makes one surface error hard to diagnose without context.", 84, 336, 330, 110, { size: 22, color: C.gray });
  box(slide, 472, 170, 676, 400, C.white, 22, C.line);
  textBox(slide, "A learner may receive the right form and still repeat the same mistake", 512, 204, 588, 72, { size: 28, bold: true });
  addBullets(slide, [
    "Immediate feedback should identify the grammar category.",
    "A useful explanation should connect the form to a Finnish rule.",
    "Stored mistakes should guide the next practice task.",
  ], 512, 308, 574, 190, { size: 21, spaceAfter: 14 });
  textBox(slide, "Project goal: turn correction into a repeatable learning loop.", 512, 512, 580, 38, { size: 18, bold: true, color: C.blue });
  addFooter(slide, 2, "Source: docs/PROJECT_SPEC.md");
  note(slide, "Source: docs/PROJECT_SPEC.md. The number of Finnish cases is general linguistic context, not an evaluated project metric.");
}

// Slide 3
{
  const slide = presentation.slides.add();
  slide.background.fill = C.white;
  addTitle(slide, "The personalized learning loop", "Each step is implemented as an explicit application action", "Solution");
  const labels = ["WRITE", "CHECK", "UNDERSTAND", "REMEMBER", "ANALYZE", "PRACTICE"];
  const colors = [C.ice, "#DDE9FF", C.mint, "#FFF2D9", "#FDE6E6", "#EDE7FF"];
  const nodes = [];
  labels.forEach((label, index) => {
    const left = 72 + index * 190;
    const node = box(slide, left, 255, 150, 112, colors[index], 22, colors[index]);
    node.text = label;
    node.text.style = { typeface: FONT, fontSize: label === "UNDERSTAND" ? 17 : 21, bold: true, color: C.ink, autoFit: "none", textAlign: "center", verticalAlignment: "middle" };
    nodes.push(node);
  });
  for (let i = 0; i < nodes.length - 1; i += 1) {
    slide.shapes.connect(nodes[i], nodes[i + 1], { kind: "straight", fromSide: "right", toSide: "left", line: { fill: C.blue, width: 3 }, tail: { type: "arrow", width: "med", length: "med" } });
  }
  textBox(slide, "Grammar results become learner history. Learner history becomes a ranked weakness. The weakness selects a practice target.", 150, 430, 980, 88, { size: 24, color: C.gray, align: "center" });
  addFooter(slide, 3, "Source: docs/PROJECT_SPEC.md and app/ui");
  note(slide, "The loop is the product's central differentiator. Demonstrate it in the same order during the live walkthrough.");
}

// Slide 4
{
  const slide = presentation.slides.add();
  slide.background.fill = C.paper;
  addTitle(slide, "Implemented system architecture", "Production grammar and exercise flows share one provider-isolated LLM transport", "Architecture");
  const ui = box(slide, 70, 220, 185, 116, C.ink, 18);
  ui.text = "STREAMLIT UI\n6 pages";
  ui.text.style = { typeface: FONT, fontSize: 21, bold: true, color: C.white, autoFit: "none", textAlign: "center", verticalAlignment: "middle" };
  const grammar = box(slide, 340, 160, 190, 78, C.ice, 16, C.sky);
  const vocab = box(slide, 340, 270, 190, 78, C.mint, 16, "#8ED8B4");
  const history = box(slide, 340, 380, 190, 78, "#FFF2D9", 16, "#F2C66D");
  for (const [shape, label] of [[grammar, "Grammar Service"], [vocab, "Vocabulary Service"], [history, "Database + Profile"]]) {
    shape.text = label;
    shape.text.style = { typeface: FONT, fontSize: 19, bold: true, color: C.ink, autoFit: "none", textAlign: "center", verticalAlignment: "middle" };
    slide.shapes.connect(ui, shape, { kind: "elbow", fromSide: "right", toSide: "left", line: { fill: C.gray, width: 2 }, tail: { type: "arrow", width: "sm", length: "sm" } });
  }
  const llm = box(slide, 650, 160, 200, 100, C.blue, 18);
  llm.text = "LLM Service\nChat Completions";
  llm.text.style = { typeface: FONT, fontSize: 19, bold: true, color: C.white, autoFit: "none", textAlign: "center", verticalAlignment: "middle" };
  const lex = box(slide, 650, 290, 200, 100, C.green, 18);
  lex.text = "Lexical index\nUD + FinnWordNet";
  lex.text.style = { typeface: FONT, fontSize: 19, bold: true, color: C.white, autoFit: "none", textAlign: "center", verticalAlignment: "middle" };
  const exercise = box(slide, 650, 420, 200, 100, "#7B61C9", 18);
  exercise.text = "Exercise Service\nvalidated output";
  exercise.text.style = { typeface: FONT, fontSize: 19, bold: true, color: C.white, autoFit: "none", textAlign: "center", verticalAlignment: "middle" };
  slide.shapes.connect(grammar, llm, { kind: "straight", fromSide: "right", toSide: "left", line: { fill: C.blue, width: 2 }, tail: { type: "arrow", width: "sm", length: "sm" } });
  slide.shapes.connect(vocab, lex, { kind: "straight", fromSide: "right", toSide: "left", line: { fill: C.green, width: 2 }, tail: { type: "arrow", width: "sm", length: "sm" } });
  slide.shapes.connect(history, exercise, { kind: "elbow", fromSide: "right", toSide: "left", line: { fill: "#7B61C9", width: 2 }, tail: { type: "arrow", width: "sm", length: "sm" } });
  slide.shapes.connect(exercise, llm, { kind: "elbow", fromSide: "top", toSide: "bottom", line: { fill: "#7B61C9", width: 2 }, tail: { type: "arrow", width: "sm", length: "sm" } });
  box(slide, 942, 194, 250, 256, C.white, 18, C.line);
  textBox(slide, "Experimental ML baseline", 970, 222, 196, 56, { size: 20, bold: true, align: "center" });
  textBox(slide, "TF-IDF + Logistic Regression", 970, 296, 196, 44, { size: 18, color: C.blue, bold: true, align: "center" });
  textBox(slide, "Evaluation component\nIt does not power the production grammar flow.", 970, 358, 196, 76, { size: 16, color: C.gray, align: "center" });
  addFooter(slide, 4, "Source: docs/ARCHITECTURE.md");
  note(slide, "Source: docs/ARCHITECTURE.md. Emphasize that the Phase 5 model is an experimental comparison artifact, not the production checker.");
}

// Slide 5
{
  const slide = presentation.slides.add();
  slide.background.fill = C.white;
  addTitle(slide, "Traceable Finnish data pipeline", "Public treebanks remain distinct from derived learner-error and evaluation artifacts", "Data");
  const tdt = box(slide, 72, 178, 280, 108, C.ice, 20);
  tdt.text = "UD Finnish-TDT\nCC BY-SA 4.0";
  tdt.text.style = { typeface: FONT, fontSize: 23, bold: true, color: C.ink, autoFit: "none", textAlign: "center", verticalAlignment: "middle" };
  const ftb = box(slide, 72, 330, 280, 108, C.mint, 20);
  ftb.text = "UD Finnish-FTB\nCC BY 4.0";
  ftb.text.style = { typeface: FONT, fontSize: 23, bold: true, color: C.ink, autoFit: "none", textAlign: "center", verticalAlignment: "middle" };
  const parsed = box(slide, 455, 220, 280, 140, C.paper, 20, C.line);
  parsed.text = "Strict CoNLL-U parsing\n33,859 sentences\n361,818 word tokens";
  parsed.text.style = { typeface: FONT, fontSize: 21, bold: true, color: C.ink, autoFit: "none", textAlign: "center", verticalAlignment: "middle" };
  const derived = box(slide, 838, 220, 350, 140, "#FFF2D9", 20);
  derived.text = "Controlled synthetic errors\nsource IDs + leakage_group_id\nversioned manifests and hashes";
  derived.text.style = { typeface: FONT, fontSize: 20, bold: true, color: C.ink, autoFit: "none", textAlign: "center", verticalAlignment: "middle" };
  slide.shapes.connect(tdt, parsed, { kind: "elbow", fromSide: "right", toSide: "left", line: { fill: C.blue, width: 2 }, tail: { type: "arrow", width: "sm", length: "sm" } });
  slide.shapes.connect(ftb, parsed, { kind: "elbow", fromSide: "right", toSide: "left", line: { fill: C.green, width: 2 }, tail: { type: "arrow", width: "sm", length: "sm" } });
  slide.shapes.connect(parsed, derived, { kind: "straight", fromSide: "right", toSide: "left", line: { fill: C.gold, width: 2 }, tail: { type: "arrow", width: "sm", length: "sm" } });
  textBox(slide, "FinnWordNet adds English sense candidates to the separate vocabulary index. It does not label grammar errors.", 274, 500, 740, 66, { size: 20, color: C.gray, align: "center" });
  addFooter(slide, 5, "Sources and licenses: docs/DATA_SOURCES.md");
  note(slide, "Sources: https://github.com/UniversalDependencies/UD_Finnish-TDT and https://github.com/UniversalDependencies/UD_Finnish-FTB. Counts come from the Phase 3 preprocessing manifest documented in docs/DATA_SOURCES.md.");
}

// Slide 6
{
  const slide = presentation.slides.add();
  slide.background.fill = C.paper;
  addTitle(slide, "Controlled synthetic learner errors", "A narrow, reproducible proxy for the classical baseline", "Data transformation");
  textBox(slide, "CORRECT", 84, 188, 180, 28, { size: 14, bold: true, color: C.green });
  box(slide, 72, 224, 480, 104, C.mint, 20);
  textBox(slide, "Minä menen kouluun.", 104, 246, 420, 60, { size: 30, bold: true });
  textBox(slide, "TRANSFORMATION", 84, 382, 180, 28, { size: 14, bold: true, color: C.coral });
  box(slide, 72, 418, 480, 104, "#FDE6E6", 20);
  textBox(slide, "minä + 3rd person verb", 104, 442, 420, 56, { size: 25, bold: true, color: C.coral });
  const wrong = box(slide, 680, 250, 500, 176, C.white, 22, C.line);
  textBox(slide, "SYNTHETIC ERROR", 718, 270, 230, 28, { size: 14, bold: true, color: C.coral });
  textBox(slide, "Minä menee kouluun.", 718, 312, 420, 54, { size: 30, bold: true });
  textBox(slide, "VERB_CONJUGATION", 718, 376, 280, 34, { size: 17, bold: true, color: C.blue });
  textBox(slide, "Why synthetic data: reproducible transformations were feasible within scope, while suitable authentic learner data was not available. The result does not prove real-learner generalization.", 664, 476, 520, 106, { size: 20, color: C.gray });
  addFooter(slide, 6, "Source: data/errors/error_generation_manifest_v1.json");
  note(slide, "The production generator uses corpus-observed compatible forms and records the exact transformation. The presentation example is the project’s canonical verb-agreement example.");
}

// Slide 7
{
  const slide = presentation.slides.add();
  slide.background.fill = C.white;
  addTitle(slide, "Classical ML baseline", "Character TF-IDF and Logistic Regression on three synthetic error classes", "Machine learning");
  const metrics = report.ml_baseline.metrics;
  const chart = slide.charts.add("bar", {
    position: { left: 72, top: 180, width: 690, height: 390 },
    categories: ["Train", "Validation", "Test"],
    series: [
      { name: "Accuracy", values: [metrics.train.accuracy, metrics.validation.accuracy, metrics.test.accuracy].map((value) => Math.round(value * 1000) / 10), fill: C.blue },
      { name: "Macro F1", values: [metrics.train.macro_f1, metrics.validation.macro_f1, metrics.test.macro_f1].map((value) => Math.round(value * 1000) / 10), fill: C.sky },
    ],
    barOptions: { direction: "column", grouping: "clustered" },
    hasLegend: true,
    legend: { position: "bottom" },
    valueAxis: { minimumScale: 0, maximumScale: 100, numberFormatCode: "0" },
    dataLabels: { showValue: true, position: "outEnd", numberFormatCode: "0.0" },
  });
  applyPresentationChartFont(chart, { fontFamily: FONT });
  box(slide, 824, 182, 360, 176, C.paper, 20);
  textBox(slide, "Test set", 858, 204, 290, 34, { size: 16, bold: true, color: C.gray });
  textBox(slide, `${(metrics.test.accuracy * 100).toFixed(1)}%`, 854, 244, 300, 66, { size: 48, bold: true, color: C.blue });
  textBox(slide, `Accuracy\nMacro F1 ${(metrics.test.macro_f1 * 100).toFixed(1)}%`, 858, 306, 300, 48, { size: 17, bold: true });
  addBullets(slide, [
    "Group-aware 70/15/15 approximation",
    "Zero leakage-group overlap",
    "Pipeline fitted on training data only",
    "Shortcut risk remains visible",
  ], 836, 388, 342, 176, { size: 18, spaceAfter: 9 });
  addFooter(slide, 7, "n = 3,000 synthetic examples; test n = 449");
  note(slide, "Source: reports/final_evaluation_v1.json and models/error_classifier_v1_metadata.json. This baseline classifies an already-incorrect sentence into one of three synthetic categories.");
}

// Slide 8
{
  const slide = presentation.slides.add();
  slide.background.fill = C.paper;
  addTitle(slide, "Validated LLM grammar checker", "Contextual detection, correction, explanation, and learning tips", "Production AI");
  await addImage(slide, "docs/presentation/screenshots/grammar_result_recorded.png", { left: 622, top: 160, width: 586, height: 414 }, "Grammar Checker showing a preserved real correction", "cover", { left: 0.20, top: 0.13, right: 0, bottom: 0.02 });
  const stages = ["Grammar Service", "LLM Service", "JSON extraction", "GrammarResult validation"];
  const nodes = [];
  stages.forEach((label, index) => {
    const node = box(slide, 74, 170 + index * 102, 400, 68, index === 3 ? C.mint : C.white, 16, index === 3 ? "#8ED8B4" : C.line);
    node.text = label;
    node.text.style = { typeface: FONT, fontSize: 20, bold: true, color: C.ink, autoFit: "none", textAlign: "center", verticalAlignment: "middle" };
    nodes.push(node);
  });
  for (let i = 0; i < nodes.length - 1; i += 1) {
    slide.shapes.connect(nodes[i], nodes[i + 1], { kind: "straight", fromSide: "bottom", toSide: "top", line: { fill: C.blue, width: 2 }, tail: { type: "arrow", width: "sm", length: "sm" } });
  }
  textBox(slide, "Minä menee kouluun.  →  Minä menen kouluun.", 72, 604, 1100, 38, { size: 24, bold: true, color: C.blue });
  addFooter(slide, 8, "Screenshot: previously recorded real Phase 11 system output");
  note(slide, "Source: app/services/grammar_service.py, app/services/llm_service.py, and the preserved Phase 11 grammar output for single_verb_01. The screenshot is explicitly a previously recorded real output, not a current live call.");
}

// Slide 9
{
  const slide = presentation.slides.add();
  slide.background.fill = C.white;
  addTitle(slide, "Personalization from stored mistakes", "Deterministic aggregation selects the learner's highest supported weakness", "Learner profile");
  await addImage(slide, "docs/presentation/screenshots/weakness_profile.png", { left: 70, top: 162, width: 682, height: 430 }, "My Mistakes page with controlled demo history and weakness profile", "cover", { left: 0.12, top: 0.03, right: 0, bottom: 0.02 });
  const flow = [
    ["1", "Persist once", "One grammar check and its errors use one SQLite transaction."],
    ["2", "Aggregate", "Counts and percentages come from stored error rows."],
    ["3", "Select target", "Highest supported category drives the next exercise."],
  ];
  flow.forEach(([n, title, body], index) => {
    textBox(slide, n, 810, 184 + index * 142, 48, 48, { size: 23, bold: true, color: C.white, fill: C.blue, align: "center" });
    textBox(slide, title, 884, 178 + index * 142, 270, 38, { size: 22, bold: true });
    textBox(slide, body, 884, 218 + index * 142, 294, 66, { size: 17, color: C.gray });
  });
  addFooter(slide, 9, "Controlled demo_user state; no production database is committed");
  note(slide, "Source: app/services/database_service.py and app/services/profile_service.py. The screenshot uses the disposable demo database prepared for the presentation.");
}

// Slide 10
{
  const slide = presentation.slides.add();
  slide.background.fill = C.paper;
  addTitle(slide, "Integrated Streamlit product", "Focused views support the complete learner flow", "Product demo");
  await addImage(slide, "docs/presentation/screenshots/grammar_checker.png", { left: 70, top: 162, width: 360, height: 220 }, "Grammar Checker input and result", "cover", { left: 0.10, top: 0.02, right: 0.02, bottom: 0.18 });
  await addImage(slide, "docs/presentation/screenshots/vocabulary_koulu.png", { left: 460, top: 162, width: 360, height: 220 }, "Vocabulary lookup for koulu", "cover", { left: 0.12, top: 0.03, right: 0, bottom: 0.20 });
  await addImage(slide, "docs/presentation/screenshots/practice_recorded.png", { left: 850, top: 162, width: 360, height: 220 }, "Practice page with correct-answer feedback", "cover", { left: 0.12, top: 0.03, right: 0, bottom: 0.02 });
  textBox(slide, "Grammar", 70, 398, 360, 32, { size: 21, bold: true, align: "center" });
  textBox(slide, "Vocabulary", 460, 398, 360, 32, { size: 21, bold: true, align: "center" });
  textBox(slide, "Targeted practice", 850, 398, 360, 32, { size: 21, bold: true, align: "center" });
  textBox(slide, "Explicit actions make Streamlit reruns safe: rendering does not repeat API calls or database inserts, and answer checking keeps the exercise stable.", 166, 488, 948, 90, { size: 23, color: C.gray, align: "center" });
  addFooter(slide, 10, "Screenshots from the actual application components; fallback outputs are labeled");
  note(slide, "Screenshots were captured from the project Streamlit UI. Grammar and exercise screenshots use preserved real Phase 11 outputs because the Phase 12 live grammar smoke encountered provider unavailability.");
}

// Slide 11
{
  const slide = presentation.slides.add();
  slide.background.fill = C.white;
  addTitle(slide, "Phase 11 evaluation", "Quantitative structure and AI-assisted linguistic review are reported separately", "Evidence");
  const grammar = report.grammar;
  const exercise = report.exercise;
  const qualitative = exercise.manual_review.criterion_summary;
  const chart = slide.charts.add("bar", {
    position: { left: 72, top: 174, width: 660, height: 388 },
    categories: ["Grammar F1", "Correction exact", "Structured output", "Exercise structure", "Answer correct", "Distractor pass"],
    series: [{
      name: "Rate",
      values: [grammar.detection.f1, grammar.correction.exact_match_rate, grammar.structured_output.success_rate, exercise.structural_validity_rate_over_all_requests, qualitative.answer_correctness.pass_rate, qualitative.distractor_plausibility.pass_rate].map((value) => Math.round(value * 1000) / 10),
      fill: C.blue,
    }],
    barOptions: { direction: "bar", grouping: "clustered" },
    hasLegend: false,
    valueAxis: { minimumScale: 0, maximumScale: 100, numberFormatCode: "0" },
    dataLabels: { showValue: true, position: "outEnd", numberFormatCode: "0.0" },
  });
  applyPresentationChartFont(chart, { fontFamily: FONT });
  box(slide, 798, 174, 390, 388, C.paper, 22);
  textBox(slide, "Selected evidence", 830, 196, 326, 40, { size: 23, bold: true });
  textBox(slide, `${(grammar.detection.f1 * 100).toFixed(2)}%`, 830, 254, 200, 52, { size: 42, bold: true, color: C.blue });
  textBox(slide, "Grammar detection F1\n39 predictions from 40 cases", 830, 306, 310, 58, { size: 17, color: C.gray });
  textBox(slide, `${grammar.false_positive_rate.false_positives}/${grammar.false_positive_rate.total_valid_sentences_in_dataset}`, 830, 386, 200, 46, { size: 34, bold: true, color: C.coral });
  textBox(slide, `False positives among valid cases\n${(grammar.false_positive_rate.rate * 100).toFixed(2)}% frozen-set rate`, 830, 434, 310, 58, { size: 17, color: C.gray });
  textBox(slide, "AI-assisted qualitative linguistic review, not Finnish-teacher validation", 830, 510, 316, 42, { size: 15, bold: true, color: C.gold });
  addFooter(slide, 11, "Grammar n = 40; exercise n = 20; ML test n = 449");
  note(slide, "Source: reports/final_evaluation_v1.json. Displayed rates are loaded from the machine-readable report. Grammar output validity was 39/40. Exercise structural validity was 20/20. Exercise distractor PASS rate was 11/20.");
}

// Slide 12
{
  const slide = presentation.slides.add();
  slide.background.fill = C.ink;
  textBox(slide, "LIMITATIONS AND NEXT EVIDENCE", 72, 42, 520, 28, { size: 14, bold: true, color: C.sky });
  textBox(slide, "A complete MVP with honest boundaries", 72, 82, 930, 62, { size: 38, bold: true, color: C.white });
  addBullets(slide, [
    "The ML baseline uses controlled synthetic learner errors.",
    "The grammar set has 40 cases and the exercise sample has 20 items.",
    "Qualitative review was AI-assisted, not a Finnish-teacher evaluation.",
    "LLM output and latency depend on the external provider.",
    "Vocabulary coverage is corpus-bounded and meanings are not context-ranked.",
    "SQLite and demo_user suit a local MVP, not multi-user production.",
  ], 74, 190, 720, 330, { size: 21, color: C.white, spaceAfter: 10 });
  box(slide, 858, 180, 340, 330, C.blue, 24);
  textBox(slide, "Future validation", 892, 210, 270, 44, { size: 25, bold: true, color: C.white });
  textBox(slide, "Authentic learner corpus\n\nFinnish-teacher review\n\nLarger evaluation sample\n\nStronger exercise validation\n\nManaged identity and persistence", 892, 278, 270, 216, { size: 19, color: C.white });
  textBox(slide, "The project demonstrates an evidence-backed learning loop from input to personalized practice.", 72, 582, 1090, 58, { size: 24, bold: true, color: "#D7E4FF" });
  note(slide, "Close by summarizing what the system proves today and what still requires authentic learner data, Finnish-teacher validation, and production infrastructure.");
}

const expectedSlideSizeEmu = "12192000,6858000";
const requirements = {
  explicitTotalSlideCount: 12,
  requiredNativeTableOwnerSlides: [],
  requiredNativeChartOwnerSlides: [7, 11],
  materializeLiteralChartWorkbooks: true,
  nativeChartTargetApplication: "powerpoint",
};
const fontPolicy = { basis: "design", families: [FONT] };
const stagingDir = path.join(workspaceDir, ".codex-finalizer");
await fs.mkdir(stagingDir, { recursive: true });
const candidatePath = path.join(stagingDir, "phase12_final_presentation_candidate.pptx");
await (await PresentationFile.exportPptx(presentation)).save(candidatePath);

await finalizePresentation({
  ...requirements,
  workspaceDir,
  candidatePath,
  finalPath: FINAL_PPTX,
  pythonExecutable: RUNTIME_PYTHON,
  integrityValidatorPath: path.join(SKILL_DIR, "container_tools/inspect_presentation_package_integrity.py"),
  layoutValidatorPath: path.join(SKILL_DIR, "container_tools/inspect_presentation_layout_geometry.py"),
  layoutArgs: [
    "--expected-slide-size-emu", expectedSlideSizeEmu,
    "--validate-bullet-geometry",
    "--validate-heading-fit",
  ],
  requiredNativeTableOwnerSlides: [],
  fontPolicy,
  verifyArtifactToolImport: true,
  receiptPath: path.join(stagingDir, "final_presentation.pptx.validation.json"),
});
