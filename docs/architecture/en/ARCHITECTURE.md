# Generate: dispatcher, three queues, three channels

Last updated: 2026-09-09  
Status: **target architecture** (code still uses a synchronous wait; see the table in README).

--------------------------------------------------------------------------------
1. Big picture
--------------------------------------------------------------------------------

                    ┌─────────────┐
                    │  Browser    │
                    │  Generate   │
                    └──────┬──────┘
                           │ POST /api/generate  (accept)
                           │ GET  /api/jobs/:id  (status)
                           ▼
                    ┌─────────────┐
                    │  Flask API  │
                    │  (fast)     │
                    └──────┬──────┘
                           │ create Job + LogicalModel
                           ▼
              ┌────────────────────────────┐
              │     ROUTING DISPATCHER     │
              │  health + duplicate map +   │
              │  channel selection         │
              └─────────────┬──────────────┘
            ┌───────────────┼───────────────┐
            ▼               ▼               ▼
     queue:replicate  queue:fal     queue:omniroute
            │               │               │
            ▼               ▼               ▼
      worker-repl     worker-fal      worker-omni
            │               │               │
            ▼               ▼               ▼
       Replicate API    fal queue      OmniRoute
                                            │
                                            ▼
                                      providers
                                      behind the gateway

One routing dispatcher. Three queues. Three channel workers.
A separate “4th dispatcher worker” is optional: channel selection runs
at job create time (and optionally on retry/failover for in-flight jobs).

--------------------------------------------------------------------------------
2. Dispatcher logic (failover)
--------------------------------------------------------------------------------

**Today (no LogicalModel in DB):** Replicate → fal pairs live in `FAILOVER_MAP`
and `INTEGRATED_MODELS` (`listed: false`, `backup_for`). Backup selection:
`_failover_target(primary_id, has_image)` → fal-copy id. Full list and
exceptions (p-video, gen4-turbo) — `docs/fal_backups_report.md`. Automatic
switch on channel failure is task B2 (dispatcher + worker).

Input (target model): LogicalModel (what the user sees) + payload (prompt, media).

Steps:

  1) Resolve RouteMap: LogicalModel → list of ChannelBinding
       example: wan-3-0 → [ replicate:… , fal:…-fal , omniroute:… ]

  2) Read ChannelHealth:
       replicate / fal / omniroute ∈ { healthy, degraded, down }

  3) Pick channel by policy:
       - preferred = first healthy entry in RouteMap (priority order)
       - if preferred is down → next healthy in the map
       - if Replicate is down and fal is healthy → share/all new jobs to fal
       - if no channel is healthy → job = failed (no_channel)

  4) Enqueue the job on the chosen channel
       queue:replicate | queue:fal | queue:omniroute

  5) On worker error (5xx / timeout / auth):
       bump the channel error counter
       threshold → channel = degraded/down for a cooldown
       optionally: requeue the job on a backup channel (if a binding exists)

Why not three independent dispatchers:
  Failover “Replicate is dead → more to fal” needs ONE place that sees
  health of all channels and the duplicate map.
  Three isolated dispatchers cannot shift load across channels.

--------------------------------------------------------------------------------
3. Three queues and three workers
--------------------------------------------------------------------------------

Queue                Worker              Upstream
-------------------  ------------------  -------------------------
queue:replicate      worker-replicate    api.replicate.com
queue:fal            worker-fal          queue.fal.run
queue:omniroute      worker-omniroute    OmniRoute :20128 /v1/...

Rules:
  - a worker reads ONLY its own queue;
  - channels do not block each other;
  - scale: +N processes on a hot channel;
  - result → Job.status = succeeded|failed + urls/text in Postgres
    (media bytes optionally → Object Storage; see yandex-object-storage.md).

--------------------------------------------------------------------------------
4. OmniRoute channel
--------------------------------------------------------------------------------

Role: a third channel beside Replicate and fal, not a replacement.

Placement: separate service (in-repo: OmniRoute-release-v3.8.51/),
default port 20128, its own .env / API key.

Flask → worker-omniroute → HTTP OpenAI-compatible (etc.) → OmniRoute
→ further routing inside OmniRoute to connected providers.

Duplicates with Replicate/fal are ALLOWED (separate bindings / ids),
same as the existing replicate ↔ …-fal pairs.

OmniRoute catalog sync (GET /v1/models): periodic snapshot (target — weekly),
merge into the integrations snapshot without deleting existing
replicate/fal entries.

UI source labels are optional for now (added separately).

--------------------------------------------------------------------------------
5. Current integrations (runtime as of 2026-09-09)
--------------------------------------------------------------------------------

Generate source of truth: INTEGRATED_MODELS in server.py
(Postgres `neural_networks` catalog — showcase / metadata).
Live model prices: models_catalog/CATALOG.md (script build_priced_catalog.py).

Channel      Models in registry   Notes
----------   ------------------   --------------------------------
replicate    ~39                  LLM, image, video, audio, music
fal          ~19                  ids with -fal suffix, FAL_KEY
omniroute    3                    assistant + auto/chat + auto/coding:free
TOTAL live   ~61                  chat + generate

Duplicate pattern already exists: one capability — two registry rows
(e.g. wan-3-0 on replicate and wan-3-0-*-fal on fal).
For the dispatcher this collapses into LogicalModel + RouteMap.

As-is today:

  Generate (media/LLM):
    Browser ──POST /api/generate──► Flask ──(opt. Redis queue)──► Replicate | fal | Omni
  Chat (navigator):
    Browser ──POST /api/chat──► Flask ──► OmniRoute ──(fail)──► Replicate DeepSeek
    See §9 and assistant-prompt.md.

--------------------------------------------------------------------------------
6. Job states
--------------------------------------------------------------------------------

  queued → dispatched → running → succeeded
                              └→ failed
                              └→ requeued (failover to another channel)

Minimum fields: id, logical_model, chosen_channel, upstream_ref,
status, error, result_urls|reply, created_at, updated_at.

--------------------------------------------------------------------------------
7. Architectural bottlenecks
--------------------------------------------------------------------------------

A. Synchronous Flask (as-is)
   Long HTTP holds a gunicorn worker. Under a Generate spike (tens of jobs)
   the site/API queue in the OS or return 504. Fix: job + poll.

B. Dispatcher without a duplicate map
   Failover “to fal” is impossible without a second binding.
   Product bottleneck: coverage of replicate↔fal↔omni pairs.

C. False health
   One timeout ≠ down. Need an error threshold + cooldown, otherwise
   channel flapping and chaotic failover.

D. Single VM for everything
   Flask + 3 workers + OmniRoute (Node) share CPU/disk/network.
   Media peaks + OmniRoute sync can cause iowait.
   Mitigation: systemd/cgroup limits, night sync, later — move Omni out.

E. Queue depth inside a channel
   One worker-replicate with 33 jobs = sequential processing.
   The dispatcher balances ACROSS channels; inside a channel —
   worker concurrency (1..N).

F. No idempotency / dedupe
   Double-click = second job. Need client request_id or UI lock.

G. Secrets and boundaries
   REPLICATE_API_TOKEN, FAL_KEY, OMNIROUTE_API_KEY — separate contours.
   Leaking OmniRoute .env / committing secrets — operational risk.

H. Media in JSON body (data URL)
   Large image/audio/video in POST bloats API memory.
   Bottleneck until S3/presign upload.

I. Weekly OmniRoute sync
   A large /v1/models can slow import; run offline/job,
   not on the Generate request path.

J. Observability
   Without metrics for the three queue depths and channel health,
   failover is blind.

--------------------------------------------------------------------------------
8. Out of scope for this document
--------------------------------------------------------------------------------

- RBAC / email confirm details (separate product decision).
- Full B2b webhook→S3 as the only path — obsolete as
  “Replicate-only”; S3 remains an optional media sink
  (yandex-object-storage.md).
- Internal OmniRoute architecture (see their README in the release).
- Full assistant system-prompt text — in assistant-prompt.md
  and the CHAT_SYSTEM_PROMPT constant (server.py).

--------------------------------------------------------------------------------
9. Navigator assistant (chat + persona)
--------------------------------------------------------------------------------

Product role: “Caring Navigator + Economic Advocate”.
Doc: assistant-prompt.md. Code: CHAT_SYSTEM_PROMPT, _with_assistant_persona.

Agent goals:
  - hear the task / format / budget / tone;
  - propose 2–3 models with honest price/quality;
  - return an improved prompt and run parameters;
  - ethical refusal of dangerous topics + crisis help line.

Chat routing (separate from media-generate):

                    ┌─────────────┐
                    │  Generate   │
                    │  UI chat    │
                    └──────┬──────┘
                           │ POST /api/chat
                           ▼
                    ┌─────────────┐
                    │ Flask       │
                    │ + system    │
                    │   prompt    │
                    └──────┬──────┘
              ┌────────────┴────────────┐
              ▼                         ▼
        OmniRoute                  Replicate
        auto/coding:free           DeepSeek
        (primary)                  (fallback)

The same persona is applied to any LLM with group=assistants
via /api/generate (not only the “Assistant” button).
Media models (image/video/audio) do not get the persona.
