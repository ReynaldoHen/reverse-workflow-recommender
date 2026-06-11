const axios = require("axios")
const path  = require("path")

require("dotenv").config({
  path: path.resolve(__dirname, "../../.env"),
})

// ─────────────────────────────────────────────
// CONFIG
// ─────────────────────────────────────────────
const LIMIT    = 200
const MAX_PAGE = 50

// ─────────────────────────────────────────────
// HELPERS
// ─────────────────────────────────────────────

/**
 * Normalize response body into a plain array.
 * Shuffle may return:
 *   []
 *   { apps: [] }
 *   { success, apps: [] }
 *   { success, reason: [] }
 *   { data: [] }
 */
function extractApps(data) {
  if (Array.isArray(data))         return data
  if (Array.isArray(data?.apps))   return data.apps
  if (Array.isArray(data?.reason)) return data.reason
  if (Array.isArray(data?.data))   return data.data
  return []
}

// ─────────────────────────────────────────────
// CLOUD FETCH  (shuffler.io — full catalog)
// ─────────────────────────────────────────────

/**
 * Fetch all apps from shuffler.io cloud catalog.
 * Uses POST /api/v1/apps/search with pagination.
 * App_id yang dikembalikan konsisten dengan lokal
 * karena aktivasi lokal juga download dari sini.
 */
async function fetchFromCloud() {

  console.log("[apps] Fetching catalog from shuffler.io cloud...")

  const headers = {
    Authorization:  `Bearer ${process.env.SHUFFLE_CLOUD_API_KEY}`,
    "Content-Type": "application/json",
  }

  let allApps = []

  for (let page = 0; page < MAX_PAGE; page++) {

    const offset = page * LIMIT

    try {

      const response = await axios.post(
        `${process.env.SHUFFLE_CLOUD_URL}/api/v1/apps/search`,
        {
          search: "",
          limit:  LIMIT,
          offset: offset,
        },
        { headers }
      )

      const apps = extractApps(response.data)

      if (!apps.length) break

      allApps = allApps.concat(apps)

      console.log(
        `[apps][cloud] Page ${page + 1} — ${apps.length} apps` +
        ` (running total: ${allApps.length})`
      )

      if (apps.length < LIMIT) break

    } catch (error) {

      if (error.response) {
        console.error("[apps][cloud] Status:", error.response.status)
        console.error("[apps][cloud]", error.response.data)
      } else {
        console.error("[apps][cloud]", error.message)
      }

      break
    }
  }

  console.log(`[apps][cloud] Done — ${allApps.length} apps fetched`)

  return allApps
}

// ─────────────────────────────────────────────
// LOCAL FETCH  (self-hosted — installed only)
// ─────────────────────────────────────────────

/**
 * Fetch installed apps from self-hosted instance.
 * Digunakan hanya untuk menangkap custom apps lokal
 * yang tidak ada di cloud catalog.
 */
async function fetchFromLocal() {

  console.log("[apps] Fetching installed apps from local instance...")

  const headers = {
    Authorization: `Bearer ${process.env.SHUFFLE_API_KEY}`,
  }

  let allApps = []

  for (let page = 0; page < MAX_PAGE; page++) {

    const offset = page * LIMIT

    try {

      const response = await axios.get(
        `${process.env.SHUFFLE_URL}/api/v1/apps`,
        {
          headers,
          params: { limit: LIMIT, offset: offset },
        }
      )

      const apps = extractApps(response.data)

      if (!apps.length) break

      allApps = allApps.concat(apps)

      if (apps.length < LIMIT) break

    } catch (error) {

      if (error.response) {
        console.error("[apps][local] Status:", error.response.status)
        console.error("[apps][local]", error.response.data)
      } else {
        console.error("[apps][local]", error.message)
      }

      break
    }
  }

  console.log(`[apps][local] Done — ${allApps.length} installed apps fetched`)

  return allApps
}

// ─────────────────────────────────────────────
// MAIN
// ─────────────────────────────────────────────

/**
 * Fetch ALL apps:
 *   1. Cloud catalog (shuffler.io) → full catalog, app_id konsisten
 *   2. Local installed             → hanya ambil custom apps yang
 *                                    tidak ada di cloud
 *
 * Hasil akhir: semua apps cloud + custom local apps (if any)
 */
async function fetchAllApps() {

  // 1. cloud catalog
  const cloudApps = await fetchFromCloud()

  // 2. local installed (untuk custom apps)
  const localApps = await fetchFromLocal()

  // 3. merge — tambahkan local apps yang tidak ada di cloud
  const cloudIds  = new Set(cloudApps.map(a => a.id))
  const customApps = localApps.filter(a => !cloudIds.has(a.id))

  if (customApps.length > 0) {
    console.log(
      `[apps] ${customApps.length} custom local app(s) added` +
      ` (not found in cloud catalog)`
    )
  }

  const total = [...cloudApps, ...customApps]

  console.log(`[apps] Total: ${total.length} apps (${cloudApps.length} cloud + ${customApps.length} custom local)`)

  return total
}

module.exports = {
  fetchAllApps,
}