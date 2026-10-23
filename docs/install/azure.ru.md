# OpenConstructionERP в Microsoft Azure

[English](azure.md) | [Deutsch](azure.de.md) | Русский

Как запустить OpenConstructionERP в Azure так, чтобы данные оставались в выбранном регионе, и что сегодня работает для входа через Microsoft Entra ID. Кода под Azure нет: платформа работает как один Docker-контейнер поверх PostgreSQL, всё ниже является настройкой.

**Что проверено.** Все названия настроек сверены с исходным кодом версии 18.8.2 (`backend/app/config.py`, `backend/app/modules/users/`, `deploy/docker/`). Шаги в портале Azure и в CLI взяты из документации Azure и **не** выполнялись на живой подписке. Считайте первую установку проверкой и прочитайте раздел «Вход через Entra ID», прежде чем обещать кому-то единый вход.

## Выбор схемы

| | ВМ Azure с Docker (рекомендуется) | Azure Container Apps |
|---|---|---|
| Трудоёмкость | Одна ВМ, один compose-файл | Не нужно обновлять ВМ, но больше частей |
| Файлы в `/data` | Управляемый диск, bind mount | Общий ресурс Azure Files (сетевая файловая система) |
| TLS | Обратный прокси на ВМ (ниже) | Встроен в ingress |
| Подходит | Большинству компаний | Если политика запрещает ВМ |

В обоих случаях используются **Azure Database for PostgreSQL Flexible Server** (PostgreSQL 16) и **ровно одна реплика** приложения. При старте создаётся около 600 таблиц и выполняются миграции, поэтому два одновременно стартующих экземпляра могут столкнуться. Не масштабируйте горизонтально.

Опубликованный образ собран для `linux/amd64`. Берите размеры x64, не Arm.

## Размеры

Ядру нужно **3 ГБ памяти на выделенной машине**: около 800 МБ приложению, 200-400 МБ PostgreSQL, если он работает рядом, и разовый пик около 1,2 ГБ при импорте национального пакета расценок (версия 17.7.0 и новее). Расчёт приведён в [INSTALL_LINUX.md](../INSTALL_LINUX.md#what-the-machine-needs). Когда база на Flexible Server, ВМ PostgreSQL не несёт, но запас под импорт нужен всё равно.

| Часть | Исходный вариант | Примечания |
|---|---|---|
| ВМ | 2 vCPU, 8 ГиБ (например `Standard_D2s_v5`) | Не burstable: при импорте память лишь номинально ваша. Добавьте 2 ГБ swap, если в образе его нет |
| Container Apps | 2 vCPU, 4 ГиБ, мин. и макс. реплик 1 | Не менее 3 ГиБ |
| PostgreSQL Flexible Server | Burstable `Standard_B2s` для начала, General Purpose `Standard_D2ds_v5` для загруженной команды, 64 ГиБ | Размер можно менять позже; хранилище только растёт |
| Диск данных (`/data`) | 64 ГиБ Premium SSD | Векторное хранилище и загруженные файлы; сюда пишут около 20 модулей |

## Регион и резидентность данных

Создайте группу ресурсов, ВМ, базу и диск в **одном** регионе (например `germanywestcentral`, `uaenorth`, `qatarcentral`, `centralindia`). Резидентность определяют такие решения:

- Не включайте геоизбыточное резервное копирование, если парный регион вам не подходит: копии будут храниться там.
- По той же причине не включайте межрегиональное восстановление в Azure Backup для ВМ.
- Приложение выходит в интернет только ради включённых вами функций (поставщики ИИ, карты, загрузка конвертеров). См. [maps.md](../maps.md) и настройки ИИ, если исходящий трафик нужно ограничить.

## 1. Сеть и база данных

```bash
az group create -n rg-oce -l germanywestcentral
az network vnet create -g rg-oce -n vnet-oce --address-prefixes 10.20.0.0/16 \
  --subnet-name snet-vm --subnet-prefixes 10.20.1.0/24
```

Создайте сервер PostgreSQL с закрытым доступом в отдельной делегированной подсети, чтобы у него не было публичного адреса (актуальные ключи смотрите в `az postgres flexible-server create --help`):

```bash
az postgres flexible-server create -g rg-oce -n oce-pg-<уникальное> -l germanywestcentral \
  --version 16 --tier Burstable --sku-name Standard_B2s --storage-size 64 \
  --admin-user oceadmin --admin-password '<длинный случайный пароль>' \
  --vnet vnet-oce --subnet snet-pg --address-prefixes 10.20.2.0/24 \
  --backup-retention 14 --geo-redundant-backup Disabled
```

Затем с ВМ (или из Cloud Shell в той же сети) создайте роль и базу. Приложение создаёт таблицы само, поэтому роль должна быть владельцем базы:

```sql
CREATE ROLE oe LOGIN PASSWORD '<ещё один длинный случайный пароль>';
GRANT oe TO oceadmin;
CREATE DATABASE openestimate OWNER oe;
```

Flexible Server по умолчанию требует TLS, поэтому в адресах подключения ниже есть `ssl=require`. Если в пароле есть `@`, `/` или `:`, закодируйте его в URL процентным кодированием (`@` станет `%40`). Части `OE_DB_*` из quickstart не умеют добавлять `ssl`, поэтому здесь используются два URL.

## 2. ВМ

Создайте ВМ Ubuntu 24.04 LTS в `snet-vm`, добавьте управляемый диск данных и разрешите во входящих группы безопасности порты 80 и 443 (SSH только с адресов вашего офиса). Установите Docker (https://docs.docker.com/engine/install/ubuntu/), отформатируйте диск данных и смонтируйте его в `/srv/oce-data`.

Контейнер работает от непривилегированного пользователя `oe`. Узнайте его числовой идентификатор и передайте ему папку:

```bash
docker run --rm --entrypoint id ghcr.io/datadrivenconstruction/openconstructionerp:<версия>
sudo chown -R <uid>:<gid> /srv/oce-data
```

Создайте `/srv/oce/.env` (права 600). Секрет сгенерируйте один раз командой `openssl rand -hex 32` и больше не меняйте: все сессии оборвутся.

```bash
APP_ENV=production
JWT_SECRET=<64 hex-символа>
DATABASE_URL=postgresql+asyncpg://oe:<пароль>@oce-pg-<уникальное>.postgres.database.azure.com:5432/openestimate?ssl=require
DATABASE_SYNC_URL=postgresql://oe:<пароль>@oce-pg-<уникальное>.postgres.database.azure.com:5432/openestimate?sslmode=require
ALLOWED_ORIGINS=https://erp.example.com
REGISTRATION_MODE=admin-approve
```

При `APP_ENV=production` сервер отказывается стартовать с коротким или известным `JWT_SECRET` (меньше 32 символов). В `ALLOWED_ORIGINS` должен стоять точный адрес, который вводят пользователи; если он неверен, страница открывается пустой, а журнал сервера чист. `TRUSTED_PROXIES` уже покрывает сеть Docker, прокси ниже менять не нужно. Redis не требуется: без него задачи выполняются внутри процесса приложения.

`/srv/oce/docker-compose.yml`:

```yaml
services:
  app:
    image: ghcr.io/datadrivenconstruction/openconstructionerp:<версия>   # зафиксируйте выпущенную версию
    restart: unless-stopped
    env_file: .env
    volumes:
      - /srv/oce-data:/data
    expose: ["8080"]
  caddy:
    image: caddy:2
    restart: unless-stopped
    ports: ["80:80", "443:443"]
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
volumes:
  caddy_data:
```

`/srv/oce/Caddyfile` (сначала направьте A-запись `erp.example.com` на ВМ; сертификат запрашивается автоматически):

```
erp.example.com {
    reverse_proxy app:8080
}
```

```bash
cd /srv/oce && docker compose up -d
docker compose logs -f app        # первый запуск занимает несколько минут
```

Откройте `https://erp.example.com`. **Первый зарегистрировавшийся становится администратором**, поэтому зарегистрируйтесь сами сразу. Последующие регистрации подчиняются `REGISTRATION_MODE`. Любой другой прокси (Application Gateway, Front Door) должен сохранять WebSocket, большие загрузки и исходное имя хоста; см. [deploy/docker/README.md](../../deploy/docker/README.md).

## Вариант: Container Apps

Создайте среду в том же регионе и той же VNet, общий ресурс Azure Files для `/data` и одно приложение:

- образ `ghcr.io/datadrivenconstruction/openconstructionerp:<версия>`, целевой порт **8080**, внешний ingress;
- CPU 2, память 4 Gi, **мин. и макс. реплик 1**;
- общий ресурс смонтирован в `/data`;
- переменные из `.env` выше, при этом `JWT_SECRET` и два адреса базы хранятся как секреты Container Apps.

Домен добавьте в разделе Custom domains, чтобы получить управляемый сертификат. Если у базы публичный доступ, разрешите на сервере PostgreSQL исходящий адрес приложения. Как приложение ведёт себя на файловом ресурсе SMB, не проверялось; при ошибках блокировок или медленной работе `/data` используйте схему с ВМ.

## Файлы и объектное хранилище

Оставьте `STORAGE_BACKEND` по умолчанию (`local`): файлы лежат в `/data` на управляемом диске. Бэкенд `s3` говорит по протоколу S3 (`S3_ENDPOINT`, `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_REGION`), а Azure Blob Storage его не поддерживает, поэтому напрямую подключить нельзя. S3-совместимый сервис, который вы развернёте сами, подойдёт.

## Вход через Entra ID

Как работает вход в 18.8.2: задайте `OIDC_ENABLED`, `OIDC_ISSUER_URL`, `OIDC_CLIENT_ID` и `OIDC_CLIENT_SECRET` (по желанию `OIDC_SCOPES`, по умолчанию `openid email profile`; `OIDC_AUTO_CREATE_USERS`, по умолчанию true; `OIDC_GROUP_ROLE_MAP`). На странице входа появится «Sign in with SSO». Браузер уходит к поставщику и возвращается на `https://<ваш хост>/auth/oidc/callback`. Сервер обменивает код, читает данные пользователя у поставщика (`sub`, `email`, `name`, `groups`) и выдаёт собственные токены.

**Прямой вход через Entra ID пока не работает.** Мешают две вещи в коде:

1. Страница входа строит адрес авторизации как `<issuer>/protocol/openid-connect/auth`. Это путь Keycloak. У Entra ID он `https://login.microsoftonline.com/<tenant>/oauth2/v2.0/authorize`.
2. Роли читаются из claim `groups` в данных пользователя. Эндпоинт Entra групп не возвращает, поэтому `OIDC_GROUP_ROLE_MAP` напрямую от Entra не питается.

Кроме того, сервер не проверяет ID-токен: он полагается на ответ userinfo, полученный по TLS. Ограничивайте круг входящих в самой Entra (шаг 4).

**Что работает сегодня: Keycloak как посредник.** Разверните Keycloak (отдельный контейнер или ВМ, здесь не описано), подключите в нём Entra ID как поставщика идентификации и направьте платформу на realm Keycloak. Платформа видит обычный Keycloak, Entra берёт на себя пароли и многофакторные запросы, а маппер групп Keycloak отдаёт claim `groups`.

1. **Регистрация приложения в Entra ID** (Microsoft Entra admin center, Регистрация приложений, Новая регистрация): имя `OpenConstructionERP`, тип учётных записей «только этот каталог организации», URI перенаправления типа **Web**: `https://<хост Keycloak>/realms/<realm>/broker/<alias>/endpoint`. Запишите **идентификатор приложения (клиента)** и **идентификатор каталога (клиента-арендатора)**.
2. Сертификаты и секреты, Новый секрет клиента. Скопируйте **значение** сразу (оно показывается один раз) и запишите дату окончания: когда секрет истечёт, вход прекратится.
3. Разрешения API: `openid`, `email`, `profile` (делегированные, Microsoft Graph). В конфигурации токена добавьте необязательный claim `email` и claim групп, если роли нужны из групп.
4. Корпоративные приложения, ваше приложение, Свойства: «Требуется назначение» поставьте в Да и назначьте людей или группы, которым можно входить. Без этого войти может любой пользователь вашего тенанта.
5. **Keycloak:** Identity providers, добавьте «OpenID Connect v1.0» с адресом discovery `https://login.microsoftonline.com/<id тенанта>/v2.0/.well-known/openid-configuration` и идентификатором и секретом из шагов 1 и 2. В realm создайте клиент `openconstructionerp` с допустимым URI перенаправления `https://erp.example.com/auth/oidc/callback` и client scope с маппером членства в группах (имя claim `groups`, добавлять в userinfo).
6. **Платформа:** добавьте в `.env` и перезапустите.

```bash
OIDC_ENABLED=true
OIDC_ISSUER_URL=https://<хост Keycloak>/realms/<realm>
OIDC_CLIENT_ID=openconstructionerp
OIDC_CLIENT_SECRET=<секрет клиента Keycloak>
OIDC_GROUP_ROLE_MAP={"oce-admins":"admin","oce-estimators":"editor","oce-viewers":"viewer"}
```

Назначенная роль применяется при каждом входе; побеждает первая подходящая группа. Человек без сопоставленной группы создаётся как `editor` (а не `viewer`, как при саморегистрации), поэтому оставьте «Требуется назначение» включённым. Существующая локальная учётная запись с тем же адресом почты привязывается к идентификатору при первом входе через SSO.

**Известные проблемы 18.8.2, затрагивающие любого поставщика** (найдены при проверке этого гида, подлежат исправлению в коде): уже привязанный пользователь, входящий повторно с неизменной ролью, получает «403 No matching account found»; а при `OIDC_AUTO_CREATE_USERS=false` неизвестный пользователь получает ошибку сервера вместо чистого отказа. Пока это не исправлено, перед запуском проверьте второй вход одного и того же человека и управляйте доступом через «Требуется назначение», а не через `OIDC_AUTO_CREATE_USERS`.

## Резервные копии

- **База:** Flexible Server делает автоматические копии и поддерживает восстановление на момент времени в пределах срока хранения (7-35 дней, задаётся `--backup-retention`). Один раз проверьте восстановление в новый сервер; оно никогда не перезаписывает исходный.
- **`/data`:** снимки управляемого диска по расписанию (Azure Backup для ВМ или `az snapshot create`). Базу и диск восстанавливайте на один и тот же момент.
- **Копия под вашим контролем:** ночной `pg_dump -Fc` в контейнер хранилища в том же регионе. Что он продолжает выполняться, следит [backup-monitoring.md](../backup-monitoring.md).
- Храните `.env` и `JWT_SECRET` в менеджере паролей; в копиях их нет.

## Обновление

1. Сделайте точку восстановления базы (или `pg_dump`) и снимок диска.
2. Прочитайте заметки к новой версии.
3. Смените `<версия>` в `docker-compose.yml`, затем `docker compose pull app && docker compose up -d app`.
4. Приложение само мигрирует схему при старте; ожидайте короткий простой. Проверьте `https://erp.example.com/api/health`.
5. Откат: копия до обновления вместе со старым образом. Никогда не запускайте более старый образ на уже мигрированной базе.

## Проблемы

| Симптом | Причина |
|---|---|
| Пустая страница, журнал сервера чист | `ALLOWED_ORIGINS` не совпадает с адресом в браузере |
| Загрузка падает с 413 | У прокси впереди есть лимит тела; у Caddy по умолчанию его нет |
| Сервер останавливается при импорте пакета расценок, в журнале пусто | Не хватило памяти, см. раздел о размерах |
| Нет связи с базой | Сервер требует TLS (`ssl=require`), ВМ вне VNet или пароль не закодирован |
| Контейнер не стартует и называет `JWT_SECRET` | Короче 32 символов при `APP_ENV=production` |

Ещё: [INSTALL_LINUX.md](../INSTALL_LINUX.md), [deploy/docker/README.md](../../deploy/docker/README.md), а для Kubernetes с отдельным экземпляром на компанию [deploy/terraform/stackit](../../deploy/terraform/stackit/README.ru.md).
