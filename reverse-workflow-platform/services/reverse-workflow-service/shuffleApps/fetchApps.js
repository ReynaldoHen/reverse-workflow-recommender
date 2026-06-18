const axios = require("axios")
const path = require("path")

require("dotenv").config({
  path: path.resolve(__dirname, "../../.env"),
})

const LIMIT = 200
const MAX_PAGE = 50

function extractApps(data) {
  if (Array.isArray(data)) return data
  if (Array.isArray(data?.apps)) return data.apps
  if (Array.isArray(data?.data)) return data.data
  return []
}

// ─────────────────────────────────────────────
// CLOUD
// ─────────────────────────────────────────────
async function fetchFromCloud() {
  if (!process.env.SHUFFLE_CLOUD_URL) {
    console.warn("[apps][cloud] SHUFFLE_CLOUD_URL not set")
    return []
  }

  console.log("[apps] Fetching cloud apps...")

  const headers = {
    Authorization: `Bearer ${process.env.SHUFFLE_CLOUD_API_KEY || ""}`,
    "Content-Type": "application/json",
  }

  let all = []

  for (let page = 0; page < MAX_PAGE; page++) {
    try {
      const res = await axios.post(
        `${process.env.SHUFFLE_CLOUD_URL}/api/v1/apps/search`,
        { search: "", limit: LIMIT, offset: page * LIMIT },
        { headers }
      )

      const apps = extractApps(res.data)
      if (!apps.length) break

      all = all.concat(apps)

      if (apps.length < LIMIT) break

    } catch (err) {
      console.warn("[apps][cloud] failed:", err.message)
      break
    }
  }

  console.log(`[apps][cloud] ${all.length} apps`)
  return all
}

// ─────────────────────────────────────────────
// LOCAL
// ─────────────────────────────────────────────
async function fetchFromLocal() {
  if (!process.env.SHUFFLE_API_URL) {
    console.warn("[apps][local] SHUFFLE_API_URL missing")
    return []
  }

  console.log("[apps] Fetching local apps...")

  const headers = {
    Authorization: `Bearer ${process.env.SHUFFLE_API_KEY || ""}`,
  }

  let all = []

  for (let page = 0; page < MAX_PAGE; page++) {
    try {
      const res = await axios.get(
        `${process.env.SHUFFLE_API_URL}/api/v1/apps`,
        {
          headers,
          params: { limit: LIMIT, offset: page * LIMIT },
        }
      )

      const apps = extractApps(res.data)
      if (!apps.length) break

      all = all.concat(apps)

      if (apps.length < LIMIT) break

    } catch (err) {
      if (err.response?.status === 401) {
        console.warn("[apps][local] Unauthorized (check API key)")
        break
      }

      console.warn("[apps][local] failed:", err.message)
      break
    }
  }

  console.log(`[apps][local] ${all.length} apps`)
  return all
}

// ─────────────────────────────────────────────
// MERGE
// ─────────────────────────────────────────────
async function fetchAllApps() {
  const cloud = await fetchFromCloud()
  const local = await fetchFromLocal()

  const cloudIds = new Set(cloud.map(a => a.id))
  const custom = local.filter(a => !cloudIds.has(a.id))

  const total = [...cloud, ...custom]

  console.log(`[apps] TOTAL = ${total.length}`)
  return total
}

module.exports = {
  fetchAllApps,
}