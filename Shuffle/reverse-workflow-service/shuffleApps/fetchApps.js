const axios = require("axios")
const path = require("path")

require("dotenv").config({
  path: path.resolve(__dirname, "../../.env"),
})

async function fetchApps() {
  try {

    console.log("[apps] Fetching installed apps from Shuffle...")

    const response = await axios.get(
      `${process.env.SHUFFLE_URL}/api/v1/apps`,
      {
        headers: {
          Authorization: `Bearer ${process.env.SHUFFLE_API_KEY}`,
        },
      }
    )

    console.log(
      `[apps] ${response.data.length} apps fetched`
    )

    return response.data

  } catch (error) {

    if (error.response) {
      console.error(
        "[apps] Status:",
        error.response.status
      )
      console.error(error.response.data)
      return []
    }

    console.error(
      "[apps]",
      error.message
    )

    return []
  }
}

module.exports = {
  fetchApps,
}