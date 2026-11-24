# electricity-planner

Веб-приложение для проектирования электрощитов квартиры/дома (в т.ч. резервное питание и солнечные панели) с визуальным редактором и ориентировочной спецификацией материалов.

- Требования: [PROMPT.md](PROMPT.md)
- План, ER, API, формулы, допущения: [docs/PLAN.md](docs/PLAN.md)
- Стек: Django 5 + DRF + PostgreSQL 16, React 18 + TypeScript + Vite, Docker.

## Локальный запуск backend

```bash
cd backend
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env            # DATABASE_URL -> PostgreSQL 16
python manage.py migrate
python manage.py seed_catalog   # ~180 ориентировочных позиций каталога
python manage.py createsuperuser
python manage.py runserver
pytest && ruff check . && mypy
```

- Swagger UI: http://localhost:8000/api/v1/docs/ · OpenAPI: `/api/v1/schema/`
- Админка каталога (импорт/экспорт CSV): http://localhost:8000/admin/
- Healthcheck: `/healthz`, `/readyz`

Статус: этапы 0–3 (план, модели и каталог, расчёты, REST API). Docker и фронтенд — в следующих этапах.

> Расчёты ориентировочные и не заменяют проект сертифицированного специалиста.
