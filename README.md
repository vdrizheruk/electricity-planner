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
python manage.py seed_catalog   # 284 ориентировочные позиции каталога
python manage.py createsuperuser
python manage.py runserver
pytest && ruff check . && mypy
```

- Swagger UI: http://localhost:8000/api/v1/docs/ · OpenAPI: `/api/v1/schema/`
- Админка каталога (импорт/экспорт CSV): http://localhost:8000/admin/
- Healthcheck: `/healthz`, `/readyz`

## Локальный запуск frontend

```bash
cd frontend
npm install
npm run dev            # http://localhost:5173, /api проксируется на :8000
npm run gen:api        # типы из ../backend/openapi.yaml
npm test && npm run lint && npm run typecheck
npm run test:e2e       # Playwright (dnd); поднимает Django и Vite сам
```

Редактор щита: `/projects/<id>/board`. Палитра каталога и неразмещённые группы слева, drag&drop на DIN-рейку / монтажную панель / корзину, снап к модулю, подсветка допустимой позиции, мульти-выделение (Shift/Ctrl, рамка), Ctrl+C/V, Ctrl+Z / Ctrl+Shift+Z, zoom (Ctrl+колесо), pan (колесо, Alt+drag), автокомпоновка, версии, автосохранение, экспорт SVG/PNG. На экране уже 768 px — только просмотр.

Вкладка «Схема» — однолинейная схема (React Flow), строится из раскладки щита: вводная цепь → шина → УЗО с автоматами. Выбор и удаление синхронны с видом «Щит»; экспорт SVG/PNG и лист наклеек маркировки (обозначения QS/QF/QD/QFD/FV/KV по порядку на рейках).

Провода внутри щита: фаза (1ф — красный; 3ф — L1 коричневый, L2 чёрный, L3 серый по IEC 60445), N синий, PE жёлто-зелёный. Узлы схемы перетаскиваются, позиции сохраняются для щита.

Резервное питание: `/projects/<id>/power`. Сценарии: сеть+генератор через АВР, сеть+инвертор, инвертор+генератор, ручной I-0-II, 3ф сеть + 1ф генератор (одна фаза / объединение). Проверки нагрузки, пусковых токов, перекоса, АКБ, блокировок АВР; подбор аппаратов с ценами и кнопка «Применить к щиту резерва». API: `/api/v1/projects/<id>/power/`, `power/check/`, `power/apply/`. Лимиты троттлинга настраиваются `THROTTLE_ANON/USER/AUTH`.

Солнечные панели: `/projects/<id>/pv`. Панель и инвертор с MPPT, строки по входам (модулей в строке, число строк, азимут, наклон, длина кабеля). Проверки: Voc при Tmin ≤ Vmax входа, Vmp в окне MPPT, Isc ≤ Imax входа, DC/AC > 1,3. DC-бокс: gPV-предохранители (строк > 2), DC-разъединитель и DC-УЗИП (Ucpv ≥ Voc max) на каждый вход, MC4, кабель PV 4/6/10 мм² по току и ΔU ≤ 1–2 %, AC-автомат и УЗИП, двунаправленный счётчик при «зелёном» тарифе. Выработка кВт·ч/год — упрощённая модель. API: `/api/v1/projects/<id>/pv/`, `pv/check/`, `pv/apply/` («Собрать DC-бокс»).

Статус: этапы 0–7. Спецификация/экспорт и Docker — в следующих этапах.

> Расчёты ориентировочные и не заменяют проект сертифицированного специалиста.
