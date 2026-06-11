const { fetchAllApps }   = require("./fetchApps")
const { saveAppsToNeo4j } = require("./saveAppsToNeo4j")
const driver              = require("../neo4j/neo4jDriver")

// ─────────────────────────────────────────────
// CONFIG
// ─────────────────────────────────────────────

// How many hours before the catalog is considered stale.
// Override via APP_SYNC_TTL_HOURS in .env
const TTL_HOURS = parseInt(process.env.APP_SYNC_TTL_HOURS || "24", 10)

// ─────────────────────────────────────────────
// TTL CHECK
// ─────────────────────────────────────────────

/**
 * Query APP_SYNC_META to decide whether a sync is needed.
 *
 * Returns { needed: true }  when:
 *   - No APP_SYNC_META node exists yet (first run)
 *   - APP count is 0
 *   - Last sync is older than TTL_HOURS
 *
 * Returns { needed: false, lastSyncedAt, totalApps } when fresh.
 */
async function checkSyncNeeded() {

  const session = driver.session()

  try {

    const result = await session.run(
      `
      OPTIONAL MATCH (m:APP_SYNC_META {id: "singleton"})

      RETURN
        m.last_synced_at  AS lastSyncedAt,
        m.total_apps      AS totalApps,
        count { (n:APP) } AS appCount
      `
    )

    const row        = result.records[0]
    const appCount   = row.get("appCount").toNumber()
    const totalApps  = row.get("totalApps")
    const rawTs      = row.get("lastSyncedAt")   // Neo4j DateTime or null

    // ── never synced / empty ──────────────────
    if (!rawTs || appCount === 0) {
      console.log(
        appCount === 0
          ? "[apps] Neo4j has no APP nodes — sync required"
          : "[apps] No sync metadata found — sync required"
      )
      return { needed: true }
    }

    // ── check TTL ────────────────────────────
    const lastSyncedAt = new Date(rawTs.toString())  // Neo4j DateTime → JS Date
    const ageHours     = (Date.now() - lastSyncedAt.getTime()) / (1000 * 60 * 60)

    if (ageHours > TTL_HOURS) {
      console.log(
        `[apps] Catalog is stale ` +
        `(last synced ${ageHours.toFixed(1)}h ago, TTL = ${TTL_HOURS}h) ` +
        `— sync required`
      )
      return { needed: true }
    }

    // ── still fresh ───────────────────────────
    console.log(
      `[apps] Catalog is fresh ` +
      `(last synced ${ageHours.toFixed(1)}h ago, ` +
      `${appCount} apps in Neo4j) — skipping sync`
    )

    return { needed: false, lastSyncedAt, totalApps }

  } catch (error) {

    // If the check itself fails (e.g. Neo4j just started),
    // default to syncing to be safe.
    console.warn(
      "[apps] TTL check failed — defaulting to sync:",
      error.message
    )
    return { needed: true }

  } finally {

    await session.close()
  }
}

// ─────────────────────────────────────────────
// MAIN
// ─────────────────────────────────────────────

/**
 * Entry point — called once when the service starts.
 *
 * Flow:
 *   1. Check Neo4j for existing data + last sync timestamp.
 *   2. If data is missing or stale (> TTL_HOURS), run a full sync.
 *   3. Otherwise skip — the catalog is still fresh.
 */
async function syncAppCatalog() {

  console.log("[apps] ── App Catalog Sync ──────────────────")
  console.log(`[apps] TTL = ${TTL_HOURS}h  (APP_SYNC_TTL_HOURS)`)

  // ── Step 1: TTL check ────────────────────────
  const { needed } = await checkSyncNeeded()

  if (!needed) {
    console.log("[apps] ── Sync skipped ──────────────────────")
    return
  }

  // ── Step 2: fetch ─────────────────────────────
  const apps = await fetchAllApps()

  if (!apps || apps.length === 0) {
    console.warn("[apps] No apps returned from Shuffle — sync aborted")
    return
  }

  // ── Step 3: save (replace) ────────────────────
  try {
    await saveAppsToNeo4j(apps)
    console.log("[apps] ── Sync complete ─────────────────────")
  } catch (error) {
    console.error("[apps] Sync failed:", error.message)
    // Do NOT crash the whole service — log and continue
  }
}

module.exports = {
  syncAppCatalog,
  checkSyncNeeded, // exported for manual triggers / health checks
}