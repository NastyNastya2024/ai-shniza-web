# Testing and CI/CD plan (update)

See also the detailed plan: [ci-cd-plan.md](./ci-cd-plan.md)

After queues are up, in short:

1. **CI on PR:** lint + unit (health/dispatcher) on fakeredis.
2. **Integration:** Redis service + 4 workers smoke.
3. **CD staging:** Redis + OmniRoute docker + Flask + workers systemd.
4. **Health:** every **30s**, threshold **2** fails → channel down → that channel’s models disappear from `/api/integrations`.
