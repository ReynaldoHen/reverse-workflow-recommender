Skripsi

Main Feature (2):
1. Rollback Feature
2. AI Improvement

About the Features:
Building a custom rollback system gives your automation a memory and an "undo button."
- Fixes Mistakes: If an automated task fails halfway or accidentally blocks a critical server, the system automatically reverses the damage.
- Temporary Actions: It allows you to make temporary changes, like blocking an IP for exactly 24 hours before automatically unblocking it.

You can skip building one if your automation doesn't actually change anything.
- Read-Only: If your playbooks just look up information (like scanning a file) and send Slack alerts, there is nothing to undo.
- Built-in Timers: If your security tools already do this automatically (like a firewall that inherently drops a block rule after an hour), you don't need to rebuild that feature in your SOAR.

Work Flow:
→ Phase 1: Install Ollama, pull models, install Docker
→ Phase 2: Configure .env, docker compose up, health check
→ Phase 3: Import playbooks, index playbooks/knowledge/incidents, smoke test
→ Phase 4: Install app in Shuffle, add recommend_playbook node, add feedback node
→ Phase 5: Alerts trigger recommendations, analysts accept/reject, feedback loop trains rankings
