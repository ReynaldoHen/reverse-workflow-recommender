/**
 * buildShuffleWorkflow.js
 * AI Workflow Compiler: Semantic Workflow Plan → Shuffle Workflow JSON
 *
 * Analogi compiler architecture:
 *   Semantic Workflow Plan (IR dari LLM)  →  buildShuffleWorkflow()  →  Shuffle JSON (executable)
 *
 * Input  : Semantic Workflow Plan (output LLM)
 * Output : Valid Shuffle Workflow JSON → diimport via POST /api/v1/workflows
 */

const { v4: uuidv4 } = require("uuid");
const axios = require("axios");
const path  = require("path");
require("dotenv").config({ path: path.resolve(__dirname, "../../.env") });

// ─────────────────────────────────────────────
// PARAMETER COMPILER
// ─────────────────────────────────────────────
function compileParameter(param) {
  return {
    name:          param.name        || "",
    value:         param.value       || "",
    required:      param.required    ?? false,
    id:            "",
    description:   param.description || "",
    example:       "",
    multiline:     false,
    multiselect:   false,
    options:       null,
    action_field:  "",
    variant:       "STATIC_VALUE",
    configuration: false,
    tags:          null,
    schema:        { type: "string" },
    skip_multicheck: false,
    custom_value:  false,
    value_replace: null,
    unique_toggled: false,
    error:         "",
    hidden:        false,
  };
}

// ─────────────────────────────────────────────
// ACTION COMPILER
// ─────────────────────────────────────────────
function compileAction(step, defaultEnvironment) {
  return {
    id:    step.step_id,
    label: step.label || `${step.app_name}_${step.step_id.slice(0, 4)}`,

    app_name:    step.app_name,
    app_id:      step.app_id      || "",
    app_version: step.app_version || "1.0.0",
    name:        step.action_name,

    isStartNode:  step.is_start_node ?? false,
    environment:  step.environment   || defaultEnvironment,
    is_valid:     true,
    errors:       [],

    parameters: Array.isArray(step.parameters)
      ? step.parameters.map(compileParameter)
      : [],

    position: step.position || { x: 0, y: 0 },

    description:    step.purpose    || "",
    category:       step.category   || "",
    category_label: [],
    generated:      true,
    public:         false,
    large_image:    "",

    authentication_id:  "",
    execution_variable: { description: "", id: "", name: "", value: "" },
    sub_action:         false,
    run_magic_output:   false,
    run_magic_input:    false,
    execution_delay:    0,
    reference_url:      "",
    suggestion:         false,
    parent_controlled:  false,
    source_workflow:    "",
    source_execution:   "",
  };
}

// ─────────────────────────────────────────────
// BRANCH COMPILER
// ─────────────────────────────────────────────
function compileBranch(connection) {
  let conditions = [];
  if (Array.isArray(connection.condition)) {
    conditions = connection.condition;
  } else if (connection.condition && typeof connection.condition === "string") {
    conditions = [{ value: connection.condition, condition: {} }];
  }

  return {
    id:             uuidv4(),
    source_id:      connection.source,
    destination_id: connection.target,
    label:          connection.label || "",
    has_errors:     false,
    conditions,
    decorator:         false,
    parent_controlled: false,
    source_parent:     "",
  };
}

// ─────────────────────────────────────────────
// SAFETY NETS
// ─────────────────────────────────────────────
function ensureStepIds(steps) {
  steps.forEach((step) => {
    if (!step.step_id) step.step_id = uuidv4();
  });
}

function resolveStartNode(steps) {
  const declared = steps.find((s) => s.is_start_node === true);
  if (declared) return declared.step_id;
  steps[0].is_start_node = true;
  return steps[0].step_id;
}

function buildLinearConnections(steps) {
  return steps.slice(0, -1).map((step, i) => ({
    source:       step.step_id,
    target:       steps[i + 1].step_id,
    relationship: "CONNECTS_TO",
    condition:    "",
    label:        "",
  }));
}

// ─────────────────────────────────────────────
// MAIN COMPILER
// ─────────────────────────────────────────────
function buildShuffleWorkflow(plan) {
  if (!plan.steps || plan.steps.length === 0) {
    throw new Error("[compiler] Plan harus memiliki minimal 1 step.");
  }

  ensureStepIds(plan.steps);

  if (!plan.connections || plan.connections.length === 0) {
    plan.connections = buildLinearConnections(plan.steps);
  }

  const startStepId        = resolveStartNode(plan.steps);
  const defaultEnvironment = plan.workflow_metadata?.environment || "Cloud";
  const actions            = plan.steps.map((step) => compileAction(step, defaultEnvironment));
  const branches           = plan.connections.map(compileBranch);

  return {
    id:          uuidv4(),
    name:        plan.workflow_name        || "Generated Workflow",
    description: plan.workflow_description || "",
    start:       startStepId,

    actions,
    branches,

    execution_environment: defaultEnvironment.toLowerCase(),
    org_id:  "",
    owner:   "",

    triggers:           [],
    comments:           [],
    visual_branches:    [],
    workflow_variables: [],
    is_valid:           true,
    errors:             [],
    categories:         [],
    tags:               [],
    status:             "test",
    generated:          true,
    public:             false,
    sharing:            false,
    previously_saved:   false,
    hidden:             false,
    background_processing: false,
    workflow_as_code:   "",
    configuration:      null,
    created:            Math.floor(Date.now() / 1000),
    edited:             0,
    last_runtime:       0,
    due_date:           0,
    image:              "",
    org:                "",
    execution_org:      {},
    example_argument:   null,
    default_return_value: null,
    contact_info:       { name: "", url: "" },
    published_id:       "",
    revision_id:        "",
    usecase_ids:        null,
    input_questions:    null,
    form_control:       {},
    blogpost:           "",
    video:              "",
    workflow_type:      "",
    updated_by:         "",
    validated:          false,
    validation:         null,
    parentorg_workflow:    false,
    childorg_workflow_ids: null,
    suborg_distribution:   null,
    backup_config:      null,
    auth_groups:        null,
    first_save:         false,
  };
}

// ─────────────────────────────────────────────
// SHUFFLE IMPORTER
// API key dibaca di dalam fungsi (bukan module level)
// agar selalu dapat nilai terbaru dari process.env
// ─────────────────────────────────────────────
async function importWorkflowToShuffle(workflowJson) {
  const SHUFFLE_URL     = process.env.SHUFFLE_URL     || "http://localhost:3000";
  const SHUFFLE_API_KEY = process.env.SHUFFLE_API_KEY || "";

  if (!SHUFFLE_API_KEY) {
    throw new Error("[importer] SHUFFLE_API_KEY tidak di-set di .env");
  }

  const url = `${SHUFFLE_URL}/api/v1/workflows`;

  console.log("[importer] Connecting to:", url);
  console.log("[importer] API_KEY:", `'${SHUFFLE_API_KEY}'`);
  console.log("[importer] API_KEY length:", SHUFFLE_API_KEY.length);
  console.log("[importer] Payload size:", JSON.stringify(workflowJson).length, "bytes");
  console.log("[importer] Workflow id:", workflowJson.id);
  console.log("[importer] Actions count:", workflowJson.actions.length);

  try {
    const response = await axios.post(url, workflowJson, {
      headers: {
        "Content-Type":  "application/json",
        "Accept":        "application/json",
        "Authorization": `Bearer ${SHUFFLE_API_KEY}`,
      },
    });

    console.log("[importer] Response status:", response.status);
    return response.data;

  } catch (err) {
    if (err.response) {
      console.log("[importer] Response status:", err.response.status);
      console.log("[importer] Response body:", JSON.stringify(err.response.data).slice(0, 300));
      throw new Error(`[importer] Gagal [${err.response.status}]: ${JSON.stringify(err.response.data)}`);
    }
    throw new Error(`[importer] Tidak bisa reach Shuffle — ${err.message}`);
  }
}

// ─────────────────────────────────────────────
// EXPORTS
// ─────────────────────────────────────────────
module.exports = {
  buildShuffleWorkflow,
  importWorkflowToShuffle,
  buildLinearConnections,
};