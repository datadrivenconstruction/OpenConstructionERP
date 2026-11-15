# Единый вход: OIDC и SAML

Сотрудники входят через корпоративный провайдер удостоверений (IdP), а не по локальному паролю. Оба протокола поддерживаются наравне. Выберите тот, который есть у вашего IdP; можно настроить оба, тогда на странице входа появятся обе кнопки.

|  | OIDC | SAML 2.0 |
|---|---|---|
| Доп. пакет | не нужен | `pip install "openconstructionerp[saml]"` |
| Включение | `OIDC_ENABLED=true` | `SAML_ENABLED=true` |
| Адрес возврата на вашем хосте | `/auth/oidc/callback` | `/api/v1/users/auth/saml/acs/` (ACS URL) |
| Роли берутся из | `OIDC_ROLE_CLAIMS` (по умолчанию `groups,roles`) | `SAML_ROLE_ATTRIBUTE` (по умолчанию `groups`) |

После изменения настроек перезапустите сервер.

## OIDC

Задайте `OIDC_ISSUER_URL`, `OIDC_CLIENT_ID` и `OIDC_CLIENT_SECRET`. По желанию: `OIDC_SCOPES` (по умолчанию `openid email profile`), `OIDC_AUTO_CREATE_USERS` (по умолчанию true), `OIDC_DEFAULT_ROLE` (по умолчанию `viewer`). В IdP зарегистрируйте redirect URI `https://<ваш-хост>/auth/oidc/callback`. Пошагово для Microsoft Entra ID: [install/azure.ru.md](install/azure.ru.md).

## SAML 2.0

1. Установите доп. пакет на сервере: `pip install "openconstructionerp[saml]"`. Он тянет `python3-saml` и `xmlsec`; в Linux нужна системная библиотека libxmlsec1. Без пакета на странице входа будет сообщение "Вход через SAML недоступен на этом сервере".
2. В IdP создайте SAML-приложение. **ACS URL** (assertion consumer service, привязка HTTP-POST) укажите `https://<ваш-хост>/api/v1/users/auth/saml/acs/`, а entity ID приложения сделайте равным `SAML_SP_ENTITY_ID`.
3. Задайте переменные:

| Переменная | Значение |
|---|---|
| `SAML_ENABLED` | `true` включает вход через SAML |
| `SAML_SP_ENTITY_ID` | Entity ID этого приложения, как в IdP |
| `SAML_ACS_URL` | ACS URL выше, точно как в IdP |
| `SAML_IDP_ENTITY_ID` | Entity ID (издатель) IdP |
| `SAML_IDP_SSO_URL` | URL единого входа IdP (привязка HTTP-Redirect) |
| `SAML_IDP_X509_CERT` | Сертификат подписи IdP, текст PEM без строк BEGIN/END |
| `SAML_EMAIL_ATTRIBUTE` | Атрибут с email (по умолчанию `email`) |
| `SAML_NAME_ATTRIBUTE` | Атрибут с отображаемым именем (по умолчанию `displayName`) |
| `SAML_ROLE_ATTRIBUTE` | Атрибут с группами или ролями (по умолчанию `groups`) |

SAML предлагается, только если заданы SSO URL, entity ID IdP, сертификат и ACS URL. Вход начинается из приложения (SP-initiated).

## Сопоставление групп и ролей

Оба протокола используют `OIDC_GROUP_ROLE_MAP`, JSON-объект "имя группы (или object id группы Entra, или значение app role) -> роль":

    OIDC_GROUP_ROLE_MAP={"estimators":"editor","site-managers":"manager","finance":"viewer"}

Если человек состоит в нескольких сопоставленных группах, он получает наивысшую роль. Новый пользователь вне сопоставленных групп получает `OIDC_DEFAULT_ROLE`. При `OIDC_AUTO_CREATE_USERS=false` войти могут только те, у кого уже есть учётная запись. Обязательный SSO для целых почтовых доменов и автоматическое создание пользователей: см. [SCIM](scim.ru.md).

## Что видит пользователь при ошибке

Браузер возвращается на страницу входа с короткой понятной фразой, без технических деталей:

- Ответ провайдера не удалось проверить: неверный сертификат, расхождение часов или ACS URL не совпадает с зарегистрированным. Админу нужно сверить `SAML_*` с IdP.
- Для этого входа нет учётной записи, а автосоздание отключено: попросите админа пригласить вас.
- Провайдер не вернул идентификатор пользователя или email: проверьте имена атрибутов.
- Вход через SAML недоступен на этом сервере: не установлен доп. пакет `[saml]`.
- Только OIDC: запрос входа устарел (повторите), провайдер недоступен или отклонил код входа.
