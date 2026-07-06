const driver = require("../neo4j/neo4jDriver")


const UUID_REGEX =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

const CODE = {
  // structural
  INVALID_JSON:             "INVALID_JSON",
  MISSING_FIELD:            "MISSING_FIELD",
  INVALID_TYPE:             "INVALID_TYPE",
  INVALID_FORMAT:           "INVALID_FORMAT",
  DUPLICATE_ID:             "DUPLICATE_ID",
  MISSING_START_NODE:       "MISSING_START_NODE",
  MULTIPLE_START_NODES:     "MULTIPLE_START_NODES",
  INVALID_BRANCH_REFERENCE: "INVALID_BRANCH_REFERENCE",
  // semantic
  INVALID_APP_ID:           "INVALID_APP_ID",
  APP_FIELD_MISMATCH:       "APP_FIELD_MISMATCH",
  INVALID_ACTION_NAME:      "INVALID_ACTION_NAME",
  REVERSE_MAPPING_MISMATCH: "REVERSE_MAPPING_MISMATCH",
  // import
  SHUFFLE_IMPORT_ERROR:     "SHUFFLE_IMPORT_ERROR",
}

function normalizeName(name) {
  return String(name || "").trim().toLowerCase().replace(/[\s-]+/g, "_")
}

function err(level, code, location, message, expected = null, received = null) {
  const e = { level, code, location, message }
  if (expected !== null) e.expected = expected
  if (received !== null) e.received = received
  return e
}

function isUUID(str) {
  return UUID_REGEX.test(str)
}

function isNonEmptyString(val) {
  return typeof val === "string" && val.trim().length > 0
}

// ─────────────────────────────────────────────
// LEVEL A — STRUCTURAL
// ─────────────────────────────────────────────

function validateStructure(workflow) {
  const errors = []

  if (!workflow || typeof workflow !== "object" || Array.isArray(workflow)) {
    return [err("structural", CODE.INVALID_JSON, "root",
      "Output must be a valid JSON object",
      '{ "actions": [...], "branches": [...], "name": "...", "description": "..." }',
      typeof workflow
    )]
  }

  if (!isNonEmptyString(workflow.name)) {
    errors.push(err("structural", CODE.MISSING_FIELD, "name",
      "Field 'name' is required and must not be empty",
      "non-empty string, e.g. 'Security Threat Investigation'",
      workflow.name ?? null
    ))
  }

  if (workflow.description === undefined) {
    errors.push(err("structural", CODE.MISSING_FIELD, "description",
      "Field 'description' must be present (empty string is allowed)",
      "string",
      null
    ))
  }

  if (!Array.isArray(workflow.actions) || workflow.actions.length === 0) {
    errors.push(err("structural", CODE.MISSING_FIELD, "actions",
      "'actions' must be a non-empty array",
      "array with at least 1 element",
      workflow.actions ?? null
    ))
    return errors
  }

  const actionIds  = new Set()
  let   startCount = 0

  for (let i = 0; i < workflow.actions.length; i++) {
    const a   = workflow.actions[i]
    const loc = `actions[${i}]`

    const stringFields = {
      app_name:    "Application name from Neo4j, e.g. 'Virustotal_v3'",
      app_version: "Application version from Neo4j, e.g. '1.1.0'",
      app_id:      "Application ID from Neo4j, e.g. 'a86a53b9a463ceace67bb62eb2a9dab4'",
      id:          "Unique UUID v4 for this action, e.g. '4a183af7-7cf2-4ce9-a008-a931c7cf4ff6'",
      label:       "Display name on the Shuffle canvas, e.g. 'Check_Domain_Reputation'",
      name:        "Valid action name from Neo4j, e.g. 'get_comments_on_a_domain'",
    }

    for (const [field, hint] of Object.entries(stringFields)) {
      if (!isNonEmptyString(a[field])) {
        errors.push(err("structural", CODE.MISSING_FIELD, `${loc}.${field}`,
          `Field '${field}' in action ${i + 1} is required and must be a non-empty string`,
          hint,
          a[field] ?? null
        ))
      }
    }

    if (isNonEmptyString(a.id) && !isUUID(a.id)) {
      errors.push(err("structural", CODE.INVALID_FORMAT, `${loc}.id`,
        `'id' in action ${i + 1} must be a valid UUID v4`,
        "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx",
        a.id
      ))
    }

    if (a.id) {
      if (actionIds.has(a.id)) {
        errors.push(err("structural", CODE.DUPLICATE_ID, `${loc}.id`,
          `ID '${a.id}' is duplicated — each action must have a unique ID`,
          "A UUID v4 different from all other actions",
          a.id
        ))
      }
      actionIds.add(a.id)
    }

    if (typeof a.is_start_node !== "boolean") {
      errors.push(err("structural", CODE.INVALID_TYPE, `${loc}.is_start_node`,
        "'is_start_node' must be a boolean",
        "true or false",
        a.is_start_node ?? null
      ))
    } else if (a.is_start_node) {
      startCount++
    }

    if (typeof a.execution_delay !== "number" || a.execution_delay < 0) {
      errors.push(err("structural", CODE.INVALID_TYPE, `${loc}.execution_delay`,
        "'execution_delay' must be a number >= 0",
        "0",
        a.execution_delay ?? null
      ))
    }

    if (
      !a.position ||
      typeof a.position !== "object"   ||
      typeof a.position.x !== "number" ||
      typeof a.position.y !== "number"
    ) {
      errors.push(err("structural", CODE.INVALID_TYPE, `${loc}.position`,
        "'position' must be an object with numeric x and y properties",
        '{"x": 200, "y": 300}',
        JSON.stringify(a.position ?? null)
      ))
    }
  }

  if (startCount === 0) {
    errors.push(err("structural", CODE.MISSING_START_NODE, "actions",
      "No action has is_start_node: true",
      "Exactly 1 action must have is_start_node: true (the first/trigger node)",
      0
    ))
  } else if (startCount > 1) {
    errors.push(err("structural", CODE.MULTIPLE_START_NODES, "actions",
      `${startCount} actions have is_start_node: true`,
      "Only exactly 1 action may have is_start_node: true",
      startCount
    ))
  }

  if (!Array.isArray(workflow.branches)) {
    errors.push(err("structural", CODE.INVALID_TYPE, "branches",
      "'branches' must be an array",
      "array (can be empty if there is only 1 action)",
      typeof workflow.branches
    ))
    return errors
  }

  const branchIds = new Set()

  for (let i = 0; i < workflow.branches.length; i++) {
    const b   = workflow.branches[i]
    const loc = `branches[${i}]`

    for (const field of ["id", "source_id", "destination_id"]) {
      if (!isNonEmptyString(b[field])) {
        errors.push(err("structural", CODE.MISSING_FIELD, `${loc}.${field}`,
          `Field '${field}' in branch ${i + 1} is required`,
          "UUID v4",
          b[field] ?? null
        ))
      } else if (!isUUID(b[field])) {
        errors.push(err("structural", CODE.INVALID_FORMAT, `${loc}.${field}`,
          `'${field}' in branch ${i + 1} must be a valid UUID v4`,
          "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx",
          b[field]
        ))
      }
    }

    if (b.id) {
      if (branchIds.has(b.id)) {
        errors.push(err("structural", CODE.DUPLICATE_ID, `${loc}.id`,
          `Branch ID '${b.id}' is duplicated`,
          "A UUID v4 different from all other branches",
          b.id
        ))
      }
      branchIds.add(b.id)
    }

    const validIds = [...actionIds].join(", ")

    if (b.source_id && isUUID(b.source_id) && !actionIds.has(b.source_id)) {
      errors.push(err("structural", CODE.INVALID_BRANCH_REFERENCE, `${loc}.source_id`,
        `source_id '${b.source_id}' does not reference an existing action`,
        `One of: ${validIds}`,
        b.source_id
      ))
    }

    if (b.destination_id && isUUID(b.destination_id) && !actionIds.has(b.destination_id)) {
      errors.push(err("structural", CODE.INVALID_BRANCH_REFERENCE, `${loc}.destination_id`,
        `destination_id '${b.destination_id}' does not reference an existing action`,
        `One of: ${validIds}`,
        b.destination_id
      ))
    }
  }

  return errors
}

// ─────────────────────────────────────────────
// LEVEL B — SEMANTIC (Neo4j)
// ─────────────────────────────────────────────

async function validateSemantic(workflow) {
  const errors  = []
  const session = driver.session()

  try {
    for (let i = 0; i < workflow.actions.length; i++) {
      const a   = workflow.actions[i]
      const loc = `actions[${i}]`

      if (!a.app_id) continue

      const appRes = await session.run(
        `MATCH (a:APP {app_id: $app_id})
         RETURN a.app_name    AS app_name,
                a.app_version AS app_version,
                a.large_image AS large_image`,
        { app_id: a.app_id }
      )

      if (appRes.records.length === 0) {
        errors.push(err("semantic", CODE.INVALID_APP_ID, `${loc}.app_id`,
          `app_id '${a.app_id}' was not found in the Neo4j catalog`,
          "A valid app_id from the Application Knowledge Graph",
          a.app_id
        ))
        continue
      }

      const neo4j = {
        app_name:    appRes.records[0].get("app_name"),
        app_version: appRes.records[0].get("app_version"),
        large_image: appRes.records[0].get("large_image"),
      }

      if (a.app_name !== neo4j.app_name) {
        errors.push(err("semantic", CODE.APP_FIELD_MISMATCH, `${loc}.app_name`,
          `app_name does not match app_id '${a.app_id}'`,
          neo4j.app_name,
          a.app_name
        ))
      }

      if (a.app_version !== neo4j.app_version) {
        errors.push(err("semantic", CODE.APP_FIELD_MISMATCH, `${loc}.app_version`,
          `app_version does not match app_id '${a.app_id}'`,
          neo4j.app_version,
          a.app_version
        ))
      }

      if (a.large_image !== neo4j.large_image) {
        errors.push(err("semantic", CODE.APP_FIELD_MISMATCH, `${loc}.large_image`,
          `large_image does not match app_id '${a.app_id}'`,
          `Retrieve the large_image value from the Application Knowledge Graph for app_id '${a.app_id}'. Do not generate this value yourself.`,
          "(mismatched value — base64 not shown)"
        ))
      }

      if (!a.name) continue

      const actRes = await session.run(
        `MATCH (APP:APP {app_id: $app_id})-[:HAS_ACTION]->(act:ACTION_TEMPLATE {name: $action_name})
         RETURN act.name AS action_name`,
        { app_id: a.app_id, action_name: a.name }
      )

      if (actRes.records.length === 0) {

        const exRes = await session.run(
          `MATCH (APP:APP {app_id: $app_id})-[:HAS_ACTION]->(act:ACTION_TEMPLATE)
           RETURN act.name AS action_name
           LIMIT 5`,
          { app_id: a.app_id }
        )

        const examples = exRes.records
          .map(r => r.get("action_name"))
          .join(", ")

        errors.push(err("semantic", CODE.INVALID_ACTION_NAME, `${loc}.name`,
          `Action '${a.name}' is not available for app '${neo4j.app_name}'`,
          examples
            ? `Use a valid action from Neo4j. Examples: ${examples}`
            : `Use a valid action from the Action Knowledge Graph for app_id '${a.app_id}'`,
          a.name
        ))
      }
    }
  } finally {
    await session.close()
  }

  return errors
}

// ─────────────────────────────────────────────
// LEVEL C — RULE-BASED REVERSE MAPPING CHECK
// ─────────────────────────────────────────────

async function validateReverseMapping(workflow, workflowId) {
  const errors  = []
  if (!workflowId) return errors

  const session = driver.session()
  try {
    const res = await session.run(
      `MATCH (a:ACTION {workflow_id: $workflowId})-[:HAS_REVERSE]->(r:REVERSE_ACTION)
       WHERE r.status = 'auto_mapped' AND r.reverse_action_name <> ''
       RETURN DISTINCT r.reverse_action_name AS expected, a.action_name AS source`,
      { workflowId }
    )
    if (res.records.length === 0) return errors

    const present = new Set(
      (workflow.actions || []).map(a => normalizeName(a.name))
    )

    for (const rec of res.records) {
      const exp = normalizeName(rec.get("expected"))
      const src = normalizeName(rec.get("source"))
      if (!present.has(exp) && !present.has(src)) {
        errors.push(err("semantic", CODE.REVERSE_MAPPING_MISMATCH, "actions",
          `Reverse untuk '${src}' tidak ditemukan: tidak ada '${exp}' maupun '${src}' pada hasil`,
          `Sertakan action '${exp}' (reverse mekanis) atau pertahankan '${src}' (audit/notifikasi)`,
          [...present].join(", ")
        ))
      }
    }
  } finally {
    await session.close()
  }

  return errors
}

function collectReviewRequired(workflow) {
  return (workflow.actions || [])
    .filter(a => a && a.requires_manual_review === true)
    .map(a => ({ id: a.id || null, name: a.name || null }))
}

async function getAppImages(appIds) {
  const ids = [...new Set((appIds || []).filter(Boolean))]
  if (!ids.length) return {}
  const session = driver.session()
  try {
    const res = await session.run(
      `MATCH (app:APP) WHERE app.app_id IN $ids
       RETURN app.app_id AS app_id, COALESCE(app.large_image, '') AS large_image`,
      { ids }
    )
    const map = {}
    res.records.forEach(r => { map[r.get("app_id")] = r.get("large_image") })
    return map
  } catch (e) {
    console.warn("[validate] getAppImages gagal:", e.message)
    return {}
  } finally {
    await session.close()
  }
}

async function getAutoMappedFromGraph(workflowId) {
  if (!workflowId) return []
  const session = driver.session()
  try {
    const res = await session.run(
      `MATCH (a:ACTION {workflow_id: $workflowId})-[:HAS_REVERSE]->(r:REVERSE_ACTION)
       WHERE r.status = 'auto_mapped'
       OPTIONAL MATCH (a)-[:USES_APP]->(app:APP)
       RETURN a.action_id      AS source_action_id,
              a.action_name     AS source_action_name,
              a.app_name        AS app_name,
              a.app_id          AS app_id,
              a.app_version     AS app_version,
              a.parameters      AS parameters,
              COALESCE(app.large_image, '') AS large_image,
              r.reverse_action_name AS reverse_action_name`,
      { workflowId }
    )
    return res.records.map(x => {
      let params = []
      try { params = JSON.parse(x.get("parameters") || "[]") } catch (_) { params = [] }
      return {
        source_action_name: x.get("source_action_name"),
        app_name:           x.get("app_name") || "",
        app_id:             x.get("app_id") || "",
        app_version:        x.get("app_version") || "",
        large_image:        x.get("large_image") || "",
        reverse_action_name: x.get("reverse_action_name") || "",
        parameters:         Array.isArray(params) ? params : [],
      }
    }).filter(m => m.reverse_action_name)
  } catch (err) {
    console.warn("[validate] getAutoMappedFromGraph gagal:", err.message)
    return []
  } finally {
    await session.close()
  }
}

async function getReviewRequiredFromGraph(workflowId) {
  if (!workflowId) return []
  const session = driver.session()
  try {
    const res = await session.run(
      `MATCH (a:ACTION {workflow_id: $workflowId})-[:HAS_REVERSE]->(r:REVERSE_ACTION)
       WHERE r.status IN ['requires_manual_review', 'needs_llm']
       RETURN a.action_id     AS source_action_id,
              a.action_name    AS source_action_name,
              a.app_name       AS app_name,
              r.status         AS status,
              r.reason         AS reason`,
      { workflowId }
    )
    return res.records.map(x => ({
      source_action_id:   x.get("source_action_id"),
      source_action_name: x.get("source_action_name"),
      app_name:           x.get("app_name"),
      status:             x.get("status"),
      reason:             x.get("reason") || ""
    }))
  } catch (err) {
    console.warn("[validate] getReviewRequiredFromGraph gagal:", err.message)
    return []
  } finally {
    await session.close()
  }
}

// ─────────────────────────────────────────────
// CORRECTION INSTRUCTIONS
// ─────────────────────────────────────────────

function buildCorrectionInstructions(errors) {
  const levels = [...new Set(errors.map(e => e.level))]
  const codes  = [...new Set(errors.map(e => e.code))]

  const lines = [
    `Found ${errors.length} error(s) at level(s): ${levels.join(", ")}.`,
    "Fix all errors listed above and regenerate the Shuffle Workflow JSON.",
  ]

  if (codes.includes(CODE.MISSING_FIELD))
    lines.push("- Ensure all required fields are present and filled in.")

  if (codes.includes(CODE.INVALID_APP_ID) ||
      codes.includes(CODE.APP_FIELD_MISMATCH))
    lines.push("- app_id, app_name, app_version, and large_image MUST be taken from the Application Knowledge Graph — do not invent or modify these values.")

  if (codes.includes(CODE.INVALID_ACTION_NAME))
    lines.push("- The 'name' field in each action MUST use a valid action name from the Action Knowledge Graph that corresponds to the action's app_id.")

  if (codes.includes(CODE.REVERSE_MAPPING_MISMATCH))
    lines.push("- Setiap source action yang punya pemetaan reverse otomatis (HAS_REVERSE, status auto_mapped) WAJIB menghasilkan action dengan 'name' sama persis dengan reverse_action_name pada pemetaan. Jangan menyalin action sumber apa adanya.")

  if (codes.includes(CODE.MISSING_START_NODE) ||
      codes.includes(CODE.MULTIPLE_START_NODES))
    lines.push("- Exactly 1 action must have is_start_node: true (the first/trigger node in the workflow).")

  if (codes.includes(CODE.DUPLICATE_ID))
    lines.push("- Every 'id' in actions and branches must be unique (different UUID v4 values).")

  if (codes.includes(CODE.INVALID_BRANCH_REFERENCE))
    lines.push("- source_id and destination_id in every branch must reference an existing action id.")

  if (codes.includes(CODE.SHUFFLE_IMPORT_ERROR))
    lines.push("- The workflow was rejected by Shuffle on import. Review all field values and structure.")

  return lines.join(" ")
}

async function validateWorkflow(workflow, workflowId = null) {

  // ── Level A ───────────────────────────────
  const structuralErrors = validateStructure(workflow)

  if (structuralErrors.length > 0) {
    return {
      valid:                   false,
      errors:                  structuralErrors,
      correction_instructions: buildCorrectionInstructions(structuralErrors),
    }
  }

  // ── Level B ───────────────────────────────
  const semanticErrors = await validateSemantic(workflow)

  if (semanticErrors.length > 0) {
    return {
      valid:                   false,
      errors:                  semanticErrors,
      correction_instructions: buildCorrectionInstructions(semanticErrors),
    }
  }

  // ── Level C — rule-based reverse mapping check ──
  const mappingErrors = await validateReverseMapping(workflow, workflowId)

  if (mappingErrors.length > 0) {
    return {
      valid:                   false,
      errors:                  mappingErrors,
      correction_instructions: buildCorrectionInstructions(mappingErrors),
    }
  }

  return { valid: true, errors: [], review_required: await getReviewRequiredFromGraph(workflowId) }
}

function buildImportError(shuffleErrorMessage) {
  const errors = [
    err("import", CODE.SHUFFLE_IMPORT_ERROR, "workflow",
      `Shuffle rejected the workflow on import: ${shuffleErrorMessage}`,
      "A workflow that can be successfully imported into Shuffle without errors",
      null
    ),
  ]

  return {
    valid:                   false,
    errors,
    correction_instructions: buildCorrectionInstructions(errors),
  }
}

module.exports = {
  validateWorkflow,
  buildImportError,
  getReviewRequiredFromGraph,
  getAutoMappedFromGraph,
  getAppImages,
}