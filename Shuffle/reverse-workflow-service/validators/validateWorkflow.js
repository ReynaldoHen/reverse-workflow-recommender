/**
 * validateWorkflow.js
 * Validator: Semantic Workflow Plan → { valid, errors, warnings }
 *
 * Dijalankan SEBELUM buildShuffleWorkflow() untuk memastikan
 * plan yang diterima dari LLM bisa di-compile menjadi valid Shuffle JSON.
 *
 * Prinsip validasi:
 * - errors   → plan tidak bisa di-compile, harus ditolak
 * - warnings → plan bisa di-compile tapi ada potensi masalah / hasil suboptimal
 */

const validateWorkflow = (plan) => {
  const errors   = [];
  const warnings = [];

  // ── WORKFLOW LEVEL ───────────────────────────────────────────────────

  if (!plan.workflow_name) {
    errors.push("workflow_name is required");
  }

  if (!plan.workflow_description) {
    warnings.push("workflow_description is empty");
  }

  // workflow_metadata opsional, tapi beri warning jika tidak ada
  // karena environment default akan fallback ke "Cloud"
  if (!plan.workflow_metadata) {
    warnings.push("workflow_metadata is missing — environment will default to 'Cloud'");
  }

  // ── STEPS ────────────────────────────────────────────────────────────

  if (!plan.steps) {
    errors.push("steps is required");
    // Tidak bisa lanjut validasi steps jika steps tidak ada
    return { valid: false, errors, warnings };
  }

  if (plan.steps.length === 0) {
    errors.push("steps cannot be empty");
    return { valid: false, errors, warnings };
  }

  // Cek duplikat step_id sebelum iterasi per-step
  const stepIds    = plan.steps.map((s) => s.step_id).filter(Boolean);
  const duplicates = stepIds.filter((id, i) => stepIds.indexOf(id) !== i);
  if (duplicates.length > 0) {
    errors.push(`duplicate step_id found: ${[...new Set(duplicates)].join(", ")}`);
  }

  // Validasi per step
  let startNodeCount = 0;

  plan.steps.forEach((step, index) => {
    const label = step.label || `step ${index + 1}`;

    // Field wajib — compiler tidak bisa jalan tanpa ini
    if (!step.step_id) {
      errors.push(`[${label}] missing step_id`);
    }

    if (!step.app_name) {
      errors.push(`[${label}] missing app_name`);
    }

    if (!step.action_name) {
      errors.push(`[${label}] missing action_name`);
    }

    // app_id kosong → workflow tetap bisa diimport tapi action tidak executable
    if (!step.app_id) {
      warnings.push(`[${label}] app_id is empty — action may not be executable in Shuffle`);
    }

    // app_version kosong → compiler fallback ke "1.0.0"
    if (!step.app_version) {
      warnings.push(`[${label}] app_version is missing — will default to '1.0.0'`);
    }

    // is_start_node harus tepat satu step yang true
    if (step.is_start_node === true) {
      startNodeCount++;
    }

    // position harus ada dan valid
    if (!step.position) {
      warnings.push(`[${label}] position is missing — will default to { x: 0, y: 0 }`);
    } else {
      if (typeof step.position.x !== "number" || typeof step.position.y !== "number") {
        warnings.push(`[${label}] position.x / position.y must be numbers`);
      }
    }

    // Validasi parameters jika ada
    if (step.parameters && Array.isArray(step.parameters)) {
      step.parameters.forEach((param, pi) => {
        if (!param.name) {
          errors.push(`[${label}] parameter ${pi + 1}: missing name`);
        }
        // value boleh kosong tapi beri warning jika required
        if (param.required && (param.value === undefined || param.value === "")) {
          warnings.push(`[${label}] parameter '${param.name}' is required but has no value`);
        }
      });
    }
  });

  // Tepat 1 start node
  if (startNodeCount === 0) {
    warnings.push("no step has is_start_node: true — compiler will use first step as start node");
  } else if (startNodeCount > 1) {
    errors.push(`multiple start nodes found (${startNodeCount}) — exactly one step must have is_start_node: true`);
  }

  // ── CONNECTIONS ──────────────────────────────────────────────────────

  if (!plan.connections || plan.connections.length === 0) {
    warnings.push("connections is empty — compiler will auto-generate linear connections");
  } else {
    const validStepIds = new Set(stepIds);

    plan.connections.forEach((conn, index) => {
      const label = `connection ${index + 1}`;

      if (!conn.source) {
        errors.push(`[${label}] missing source`);
      } else if (!validStepIds.has(conn.source)) {
        errors.push(`[${label}] source '${conn.source}' does not match any step_id`);
      }

      if (!conn.target) {
        errors.push(`[${label}] missing target`);
      } else if (!validStepIds.has(conn.target)) {
        errors.push(`[${label}] target '${conn.target}' does not match any step_id`);
      }

      // Self-loop tidak valid di Shuffle
      if (conn.source && conn.target && conn.source === conn.target) {
        errors.push(`[${label}] source and target are the same step — self-loop is not allowed`);
      }

      // relationship harus CONNECTS_TO jika di-set
      if (conn.relationship && conn.relationship !== "CONNECTS_TO") {
        warnings.push(`[${label}] unknown relationship '${conn.relationship}' — expected 'CONNECTS_TO'`);
      }
    });

    // Cek apakah start node punya outgoing connection
    // (hanya jika steps > 1, karena single-step workflow tidak butuh connection)
    if (plan.steps.length > 1) {
      const startStep = plan.steps.find((s) => s.is_start_node === true) || plan.steps[0];
      const hasOutgoing = plan.connections.some((c) => c.source === startStep.step_id);
      if (!hasOutgoing) {
        warnings.push(
          `start node '${startStep.label || startStep.step_id}' has no outgoing connection — workflow may stop immediately`
        );
      }
    }
  }

  return {
    valid: errors.length === 0,
    errors,
    warnings,
  };
};

module.exports = { validateWorkflow };