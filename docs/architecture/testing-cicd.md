# План тестирования и CI/CD (актуализация)

См. также подробный план: [ci-cd-plan.md](./ci-cd-plan.md)

Кратко после запуска очередей:

1. **CI на PR:** lint + unit (health/dispatcher) на fakeredis.
2. **Integration:** Redis service + 4 workers smoke.
3. **CD staging:** Redis + OmniRoute docker + Flask + workers systemd.
4. **Health:** каждые **30с**, порог **2** фейла → канал down → модели канала исчезают из `/api/integrations`.
