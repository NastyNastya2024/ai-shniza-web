# Generate Architecture (target)

Routing Generate through three channels — **Replicate**, **fal.ai**, **OmniRoute** — plus a chat assistant with a navigator system role.

Russian originals live one level up: [`../`](../).

| File | Contents |
|------|----------|
| [ARCHITECTURE.md](./ARCHITECTURE.md) | Target design, dispatcher, queues, integrations, bottlenecks, §9 assistant |
| [assistant-prompt.md](./assistant-prompt.md) | “Navigator + Economic Advocate” role, where the prompt is wired, `/api/chat` flow |
| [sequence.txt](./sequence.txt) | Sequence diagram: Generate + chat |
| [data-flow.txt](./data-flow.txt) | UML / data-flow (text) |
| [ci-cd-plan.md](./ci-cd-plan.md) | CI/CD plan (queues, workers, staging) |
| [testing-cicd.md](./testing-cicd.md) | Short testing / CI checklist |
| [../yandex-object-storage.md](../yandex-object-storage.md) | Object Storage (S3) in Yandex Cloud — optional media sink (RU) |

Model catalog + prices: [`../../neural-networks-catalog.md`](../../neural-networks-catalog.md)  
Full price table: [`../../../models_catalog/CATALOG.md`](../../../models_catalog/CATALOG.md)  
Catalog SQL: [`../../sql/neural_networks.sql`](../../sql/neural_networks.sql)

## Status vs code

| Layer | In code today | Target |
|-------|---------------|--------|
| Generate API | `POST /api/generate` → Redis inbound → wait result | + async `job_id` / poll UI |
| Chat API | `POST /api/chat` → OmniRoute → fallback DeepSeek (Replicate) | same + metrics |
| Assistant persona | `CHAT_SYSTEM_PROMPT` on chat + all LLM `assistants` | + inject prices into context |
| Channels | replicate + fal + omniroute | + RouteMap failover |
| Queues | Redis: inbound + 3 channel queues | same + RouteMap failover |
| Health | probe every **30s**, threshold **2** → hide from UI | + metrics |
| OmniRoute | systemd / npm on staging `:20128` | catalog sync weekly |
| Workers | 4 processes: dispatcher + repl/fal/omni | systemd on staging |
