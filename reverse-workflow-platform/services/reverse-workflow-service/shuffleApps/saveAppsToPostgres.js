const pool = require("./postgresClient")

// ─────────────────────────────────────────────
// TABLE CREATION (AUTO INIT)
// ─────────────────────────────────────────────
async function ensureTables(client) {

  console.log("[postgres] creating tables...")

  await client.query(`
    CREATE TABLE IF NOT EXISTS app_catalog (
      app_id TEXT PRIMARY KEY,
      app_name TEXT,
      app_version TEXT,
      large_image TEXT,
      sync_batch TEXT
    );
  `)

  await client.query(`
    CREATE TABLE IF NOT EXISTS action_templates (
      action_key TEXT PRIMARY KEY,
      app_id TEXT,
      action_name TEXT,
      action_label TEXT,
      description TEXT,
      parameters JSONB,
      sync_batch TEXT
    );
  `)

  await client.query(`
    CREATE TABLE IF NOT EXISTS parameter_templates (
      parameter_key TEXT PRIMARY KEY,
      action_key TEXT,
      parameter_name TEXT,
      required BOOLEAN,
      parameter_type TEXT,
      description TEXT,
      sync_batch TEXT
    );
  `)
}

// ─────────────────────────────────────────────
// MAIN SYNC
// ─────────────────────────────────────────────
async function saveAppsToPostgres(apps) {

  console.log("[postgres] saveAppsToPostgres called")

  const client = await pool.connect()
  const batchId = Date.now().toString()

  try {

    await ensureTables(client)

    await client.query("BEGIN")

    for (const app of apps) {

      // APP
      await client.query(
        `
        INSERT INTO app_catalog (
          app_id, app_name, app_version, large_image, sync_batch
        )
        VALUES ($1,$2,$3,$4,$5)
        ON CONFLICT (app_id)
        DO UPDATE SET
          app_name = EXCLUDED.app_name,
          app_version = EXCLUDED.app_version,
          large_image = EXCLUDED.large_image,
          sync_batch = EXCLUDED.sync_batch
        `,
        [
          app.id,
          app.name || "",
          app.app_version || "",
          app.large_image || "",
          batchId
        ]
      )

      for (const action of (app.actions || [])) {

        const actionKey = `${app.id}_${action.name}`

        // ACTION
        await client.query(
          `
          INSERT INTO action_templates (
            action_key, app_id, action_name, action_label, description, parameters, sync_batch
          )
          VALUES ($1,$2,$3,$4,$5,$6,$7)
          ON CONFLICT (action_key)
          DO UPDATE SET
            action_name = EXCLUDED.action_name,
            action_label = EXCLUDED.action_label,
            description = EXCLUDED.description,
            parameters = EXCLUDED.parameters,
            sync_batch = EXCLUDED.sync_batch
          `,
          [
            actionKey,
            app.id,
            action.name || "",
            action.label || "",
            action.description || "",
            JSON.stringify(action.parameters || []),
            batchId
          ]
        )

        for (const param of (action.parameters || [])) {

          const paramKey = `${actionKey}_${param.name}`

          // PARAMETER
          await client.query(
            `
            INSERT INTO parameter_templates (
              parameter_key, action_key, parameter_name,
              required, parameter_type, description, sync_batch
            )
            VALUES ($1,$2,$3,$4,$5,$6,$7)
            ON CONFLICT (parameter_key)
            DO UPDATE SET
              parameter_name = EXCLUDED.parameter_name,
              required = EXCLUDED.required,
              parameter_type = EXCLUDED.parameter_type,
              description = EXCLUDED.description,
              sync_batch = EXCLUDED.sync_batch
            `,
            [
              paramKey,
              actionKey,
              param.name || "",
              !!param.required,
              param.schema?.type || "string",
              param.description || "",
              batchId
            ]
          )
        }
      }
    }

    await client.query("COMMIT")

    console.log(`[postgres] synced ${apps.length} apps`)

  } catch (err) {

    await client.query("ROLLBACK")
    console.error("[postgres] error:", err.message)
    throw err

  } finally {
    client.release()
  }
}

module.exports = {
  saveAppsToPostgres
}