# electricity-planner

Веб-приложение для проектирования электрощитов квартиры/дома, включая резервное питание (АВР, генератор, инвертор, АКБ) и солнечные панели, с визуальным редактором и ориентировочной спецификацией материалов (только материалы, UAH с НДС).

> **Дисклеймер.** Расчёты ориентировочные и не заменяют проект сертифицированного специалиста. Цены каталога — ориентировочные, строки с неподтверждённой ценой помечены `*`.

- Требования: [PROMPT.md](PROMPT.md)
- План, ER-модель, API, формулы и допущения по этапам: [docs/PLAN.md](docs/PLAN.md)
- Стек: Django 5.2 + DRF + PostgreSQL 16 · React 18 + TypeScript + Vite · dnd-kit, Zustand, React Flow, Tailwind · WeasyPrint, openpyxl · Docker, Helm, GitHub Actions.

## Быстрый старт (Docker)

```bash
cp .env.example .env     # задайте DJANGO_SECRET_KEY и POSTGRES_PASSWORD
docker compose up --build
```

Приложение: http://localhost:8080 (порт — `HTTP_PORT`). При первом запуске backend сам применит миграции и загрузит каталог. Администратор каталога:

```bash
docker compose exec backend python manage.py createsuperuser   # затем /admin/
deploy/smoke.sh http://localhost:8080                          # проверка: пробы, SPA, регистрация, PDF/XLSX
```

Сервисы: `db` (PostgreSQL 16), `backend` (gunicorn, статика через WhiteNoise), `frontend` (SPA на nginx), `nginx` (входная точка: `/api`, `/admin`, `/static`, `/healthz`, `/readyz` → backend, остальное → frontend). Процессы в контейнерах работают не от root, `cap_drop: ALL`.

### Переменные окружения

| Переменная | Назначение |
|---|---|
| `DJANGO_SECRET_KEY` | обязательна, приложение без неё не стартует |
| `DJANGO_DEBUG` | `false` по умолчанию |
| `DJANGO_ALLOWED_HOSTS` | допустимые значения заголовка Host (через запятую) |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | публичный адрес с схемой, например `https://planner.example.com` |
| `DJANGO_COOKIE_SECURE` | `true` за HTTPS (по умолчанию `true` при `DEBUG=false`) |
| `DJANGO_SSL_REDIRECT`, `DJANGO_HSTS_SECONDS` | редирект на HTTPS и HSTS (по умолчанию выключены: их включает TLS-терминатор) |
| `DATABASE_URL` | `postgres://user:password@host:5432/db` |
| `THROTTLE_ANON`, `THROTTLE_USER`, `THROTTLE_AUTH` | лимиты запросов DRF (`60/min`, `600/min`, `10/min`) |
| `DJANGO_DATA_UPLOAD_MAX_BYTES` | максимальный размер JSON-запроса (32 МБ: PDF со схемами) |
| `WEB_CONCURRENCY` | число воркеров gunicorn |
| `RUN_MIGRATIONS`, `SEED_CATALOG` | `1` — применить миграции / загрузить каталог при старте контейнера |

Без Docker настройки читаются из `backend/.env` (см. `backend/.env.example`).

### Kubernetes (Helm)

Chart: [`charts/electricity-planner`](charts/electricity-planner). Образы stateless (12-factor, пользователь `10001`, `runAsNonRoot`, `readOnlyRootFilesystem` у backend). Образы публикуются в GHCR (`ghcr.io/vdrizheruk/electricity-planner-{backend,frontend}`) workflow `release.yml` при пуше тега `v*`; свой реестр — `backend.image.repository` / `frontend.image.repository`.

```bash
kubectl create secret generic planner-secrets \
  --from-literal=DJANGO_SECRET_KEY="$(python3 -c 'import secrets;print(secrets.token_urlsafe(50))')" \
  --from-literal=DATABASE_URL='postgres://planner:PASSWORD@db-host:5432/planner'
helm upgrade --install planner charts/electricity-planner \
  --set secret.existingSecret=planner-secrets \
  --set ingress.enabled=true --set ingress.className=nginx --set 'ingress.hosts={planner.example.com}' \
  --set 'ingress.tls[0].secretName=planner-tls' --set 'ingress.tls[0].hosts={planner.example.com}'
```

- **База данных**: по умолчанию внешняя, `DATABASE_URL` берётся из Secret (`database.existingSecret`, ключ `database.urlKey`). `--set postgresql.enabled=true` поднимает встроенную одиночную PostgreSQL 16 (StatefulSet + PVC): для тестов и небольших установок, в продакшене лучше управляемая БД (Cloud SQL и т. п.).
- **Секреты**: `secret.existingSecret` (ключ `DJANGO_SECRET_KEY`). Если не задан, chart создаёт Secret сам (генерирует ключ и сохраняет его между обновлениями).
- **Миграции**: Helm-hook Job (`manage.py migrate` + идемпотентный `seed_catalog`) выполняется до выкатки новой версии (`pre-upgrade`; при установке со встроенной БД или созданным chart-ом Secret — `post-install`). В Deployment `RUN_MIGRATIONS=0`, реплики не конкурируют. Отключить: `migrations.enabled=false`.
- **Ingress** опционален: `/api`, `/admin`, `/static`, `/healthz`, `/readyz` → backend, остальное → frontend. TLS терминируется на ingress; `config.cookieSecure=true` по умолчанию. Без ingress: `kubectl port-forward svc/<release>-electricity-planner-frontend 8080:80`.
- **Пробы**: liveness `/healthz`, readiness `/readyz` (проверяет БД), startupProbe. Host-заголовок проб — IP пода; он автоматически добавляется в `DJANGO_ALLOWED_HOSTS` вместе с `localhost` и хостами ingress, поэтому проверки kubelet и GCE-балансировщика (NEG) проходят.
- **GKE**: пример [`values-gke.yaml`](charts/electricity-planner/values-gke.yaml): класс `gce`, container-native LB (NEG), Google-managed certificate, статический IP, Secret с внешней БД, HPA и PDB.
- Дополнительно: `backend.autoscaling`, `*.podDisruptionBudget`, `config.extraEnv`, `imagePullSecrets`, resources, nodeSelector/tolerations/affinity.

Проверка chart локально: `deploy/helm-check.sh` (helm lint, `helm template` для внешней/встроенной БД, существующего Secret и GKE, схема манифестов через kubeconform). Та же проверка запускается в CI.

## Локальная разработка

**Backend** (Python 3.12, PostgreSQL 16):

```bash
cd backend
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env            # DATABASE_URL -> PostgreSQL 16
python manage.py migrate
python manage.py seed_catalog   # 346 ориентировочных позиций каталога
python manage.py createsuperuser
python manage.py runserver
pytest && ruff check . && ruff format --check . && mypy
```

Для PDF нужны системные библиотеки WeasyPrint: pango, `libharfbuzz-subset0` и шрифт DejaVu (`apt install libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-dejavu-core`).

Swagger UI: http://localhost:8000/api/v1/docs/ · OpenAPI: `/api/v1/schema/` · админка каталога (импорт/экспорт CSV): `/admin/` · пробы: `/healthz`, `/readyz`.

**Frontend** (Node 22):

```bash
cd frontend
npm install
npm run dev            # http://localhost:5173, /api проксируется на :8000
npm run gen:api        # типы из ../backend/openapi.yaml
npm test && npm run lint && npm run typecheck && npm run format:check
npm run test:e2e       # Playwright; поднимает Django и Vite сам
```

**Контроль качества.** `pre-commit install` включает ruff, mypy, eslint, prettier и tsc. CI (GitHub Actions, `.github/workflows/ci.yml`): ruff, mypy (strict для сервисного слоя), проверка миграций и актуальности `openapi.yaml`, pytest на PostgreSQL; eslint, prettier, tsc, vitest, сборка и совпадение типов API; Playwright; helm lint/template/kubeconform, сборка Docker-образов (без публикации) и smoke-тест всего compose-стека.

## Возможности

- **Проект и группы**: ввод 1ф/3ф, вводной автомат, система заземления (TN-C-S / TN-S / TT), группы потребителей; автоподбор автомата и характеристики, сечения кабеля по току и падению напряжения, УЗО/дифавтомата; балансировка фаз (перекос > 15 % подсвечивается), расчётная мощность с коэффициентами спроса, селективность.
- **Редактор щита** `/projects/<id>/board`: корпус в масштабе, DIN-рейки (1 модуль = 17,5 мм) и монтажная панель; палитра каталога с фильтрами; drag&drop с привязкой к модулям, подсветкой допустимой позиции и запретом коллизий; мульти-выделение, копирование, undo/redo, zoom/pan; автокомпоновка; версии и автосохранение; подбор корпуса с запасом 20 %. На экране уже 768 px — только просмотр.
- **Однолинейная схема** (React Flow) синхронизирована с видом щита в обе стороны; узлы перетаскиваются, позиции сохраняются. Провода внутри щита: фаза красная (3ф: L1 коричневый, L2 чёрный, L3 серый по IEC 60445), N синий, PE жёлто-зелёный. Экспорт SVG/PNG и лист маркировки.
- **Симуляция питания** (переключатель «Симуляция» в редакторе): тумблеры сеть / генератор / инвертор / PV, положение АВР (авто, I, II, 0), уровень солнца. Запитанные цепи подсвечиваются на схеме и на виде щита, обесточенные — серые; показаны источник, нагрузка и ток по источникам, перерыв питания, автономия АКБ и предупреждения (перегрузка источника, срабатывание вводного автомата, обратная подача без блокировки, перекос фаз, остров PV). Логика — чистый сервис `power/services/simulate.py`, статическая модель без динамики.
- **Резервное питание** `/projects/<id>/power`: сценарии «сеть + генератор через АВР», «сеть + инвертор», «инвертор + генератор», ручной I-0-II, «3ф сеть + 1ф генератор» (одна фаза / объединение), «1ф + 1ф». Проверки нагрузки, пусковых токов, перекоса, АКБ, автономности и безопасности (запрет параллели генератора с сетью без блокировки, коммутация N, RCD после инвертора); подбор аппаратов и «Применить к щиту резерва».
- **Солнечные панели** `/projects/<id>/pv`: строки на MPPT; проверки Voc при Tmin ≤ Vmax, Vmp в окне MPPT, Isc ≤ Imax, DC/AC > 1,3; DC-бокс (gPV при строк > 2, разъединитель, DC-УЗИП с Ucpv ≥ Voc max, MC4), кабель PV 4/6/10 мм² по току и ΔU ≤ 1–2 %, AC-часть, двунаправленный счётчик при «зелёном» тарифе; выработка кВт·ч/год — упрощённая модель.
- **Спецификация и экспорт** `/projects/<id>/bom`: разделы «Щиты», «Солнечная система», «Резервное питание» и общий итог; экспорт XLSX и PDF; PDF из редактора («PDF со схемами») содержит вид щита и однолинейную схему каждого щита.

API: `/api/v1/` (сессионная авторизация + CSRF), документация на `/api/v1/docs/`.

## Допущения расчётов

Полный список с формулами — в [docs/PLAN.md](docs/PLAN.md). Главное:

- Нормы: ДБН В.2.5-23, ПУЭ, IEC 60898/61008/61009/61439, IEC 60364-7-712. Сечения — Cu, ПВХ, способ прокладки «в стене/трубе», t = 30 °C.
- Напряжения 230 В (1ф) и 400 В (3ф), 50 Гц. Перекос фаз: `(Pmax − Pср) / Pср > 15 %`.
- Цены — ориентировочные UAH с НДС (`needs_verification`), правятся в админке или импортом CSV. Каталог — демонстрационный: артикулы реальные там, где это известно, остальные помечены.
- Резерв: пуск крупнейшего двигателя с полным коэффициентом, перегрузка генератора ≤ 1,5·kVA, КПД инвертора 0,9, глубина разряда LiFePO4 0,9 / AGM 0,5.
- PV: Tmin −20 °C, температура ячейки 70 °C, выработка по региону (север 950 / центр 1050 / юг 1200 кВт·ч/кВт), поправки ориентации и наклона упрощённые; PVGIS не используется.
- Один редактор на проект (без совместного редактирования).
