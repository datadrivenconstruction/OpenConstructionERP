# Windows блокирует приложение (неизвестный издатель)

Эта страница есть также на [English](WINDOWS_BLOCKED.md) и [Deutsch](WINDOWS_BLOCKED.de.md).

Если при установке или запуске появилось другое предупреждение или ошибка, смотрите [помощь с установкой](../INSTALL_TROUBLESHOOTING.ru.md) (также [онлайн](https://openconstructionerp.com/install-help)).

Эта страница для вас, если Windows не даёт запустить OpenConstructionERP, называет его программой неизвестного или непроверенного издателя, или один раз запустила его, а с тех пор блокирует при каждом запуске.

Названия элементов Windows даны так, как их показывает русская Windows 11, с английским названием в скобках. В зависимости от версии Windows русская формулировка может немного отличаться.

## Почему так происходит

Сборки OpenConstructionERP для Windows пока не подписаны цифровой подписью. По подписи Windows узнаёт, кто выпустил программу, и без неё считает приложение программой неизвестного издателя. На это реагируют две разные функции Windows, и для каждой нужны свои шаги:

- **Microsoft Defender SmartScreen** показывает синее окно "Система Windows защитила ваш компьютер" (Windows protected your PC), когда вы запускаете скачанную из интернета программу, которую Windows ещё не знает. SmartScreen предупреждает, но позволяет продолжить.
- **Интеллектуальное управление приложениями** (Smart App Control) это более строгая функция Windows 11. Когда она включена, она блокирует любой программный файл, за который не может поручиться облачная служба Microsoft и у которого нет доверенной подписи. Кнопки "продолжить" и исключения для отдельного приложения у неё нет. Её сообщение называет Smart App Control и обычно говорит, что приложение или его часть заблокированы.

Этим же объясняется самый непонятный случай, когда приложение один раз запустилось, а потом блокируется при каждом запуске. После чистой установки Windows функция Smart App Control начинает работу в режиме оценки (Evaluation): она только наблюдает и ничего не блокирует. Позже Windows решает, включить её насовсем или выключить, и после включения программа, которая работала вчера, сегодня заблокирована, хотя с нашей стороны ничего не менялось. Кроме того, настольное приложение при каждом запуске распаковывает несколько сотен вспомогательных файлов, среди них встроенную базу PostgreSQL, и Smart App Control проверяет каждый из них, а не только скачанный файл.

Название в уведомлении может сбить с толку. Блокировка приходит из приложения "Безопасность Windows", как бы ни выглядело всплывающее окно, поэтому следующий шаг это выяснить, какая именно функция её сделала.

## Шаг 1: выясните, что заблокировало приложение

1. Откройте **Пуск**, введите **Безопасность Windows** и откройте приложение.
2. Перейдите в **Защита от вирусов и угроз** (Virus & threat protection), затем в **Журнал защиты** (Protection history).
3. Посмотрите на самые новые записи. Запись, в которой упоминается **Smart App Control** (интеллектуальное управление приложениями) или **заблокированное приложение**, означает Smart App Control. Запись об обнаруженной угрозе означает антивирус Microsoft Defender.

Затем проверьте, включена ли Smart App Control: в "Безопасности Windows" откройте **Управление приложениями/браузером** (App & browser control), затем **Параметры интеллектуального управления приложениями** (Smart App Control settings). Там будет **Вкл.**, **Оценка** или **Выкл.**

Какой именно файл был отклонён, видно в **Просмотре событий** (Event Viewer): **Журналы приложений и служб** > **Microsoft** > **Windows** > **CodeIntegrity** > **Operational**, событие **3077**. У настольного приложения этот файл обычно лежит в `%LOCALAPPDATA%\OpenConstructionERP\extract`, куда приложение при каждом запуске распаковывает вспомогательные файлы. Для неподписанной сборки такая блокировка ожидаема и не означает, что файл вирус.

## Шаг 2а: SmartScreen ("Система Windows защитила ваш компьютер")

Это предупреждение можно безопасно пропустить, когда вы убедились, что файл наш (см. "Проверьте, что файл настоящий" ниже).

1. В окне нажмите **Подробнее** (More info).
2. Проверьте имя файла и нажмите **Выполнить в любом случае** (Run anyway).

SmartScreen спрашивает только о файлах, скачанных из интернета. Если он снова и снова спрашивает об одном и том же установщике, можно также щёлкнуть скачанный `.exe` правой кнопкой, выбрать **Свойства**, внизу вкладки **Общие** поставить галочку **Разблокировать** (Unblock) и нажать **ОК**. Это снимает с одного этого файла отметку "скачан из интернета". На Smart App Control это не влияет: она проверяет каждый программный файл, откуда бы он ни взялся.

## Шаг 2б: включена Smart App Control

Разрешить одно приложение, пока Smart App Control включена, нельзя. Сама Microsoft советует либо выключить функцию, либо попросить издателя подписать приложение, а наши сборки для Windows сейчас не подписаны. Остаются два честных варианта.

**Вариант 1: оставить Smart App Control включённой и запускать приложение по-другому.** Его мы и советуем, если хотите сохранить защиту. Docker и WSL запускают OpenConstructionERP внутри небольшой среды Linux, а программы Linux Smart App Control не проверяет. Оба способа описаны ниже.

**Вариант 2: выключить Smart App Control.** Это снижает защиту всего компьютера, а не только для нашего приложения, поэтому делайте так, только если вас это устраивает. В актуальных сборках Windows 11 функцию можно позже снова включить на той же странице, но в более старых сборках выключение окончательно до сброса или переустановки Windows. Если после выключения страница не даёт включить её обратно, у вас как раз такая сборка.

1. Откройте **Безопасность Windows**, затем **Управление приложениями/браузером** и **Параметры интеллектуального управления приложениями**.
2. Выберите **Выкл.** и подтвердите.
3. Снова запустите OpenConstructionERP.

Антивирус Microsoft Defender и SmartScreen в любом случае остаются включёнными.

Если в журнале защиты вместо этого видно срабатывание антивируса Microsoft Defender, а файл вы проверили, как описано ниже, можно открыть эту запись и выбрать **Действия** (Actions), затем **Разрешить на устройстве** (Allow on device). Если сомневаетесь, не разрешайте, а напишите нам.

## Запуск через Docker (работает при включённой Smart App Control)

1. Установите **Docker Desktop** с docker.com и один раз запустите его. Docker Desktop бесплатен для личного использования, обучения и небольших компаний; крупным компаниям нужна платная подписка Docker.
2. Создайте папку, например `C:\OpenConstructionERP`, откройте в ней **Windows PowerShell** и выполните:

```powershell
curl.exe -fsSL https://raw.githubusercontent.com/datadrivenconstruction/OpenConstructionERP/main/docker-compose.quickstart.yml -o docker-compose.yml
curl.exe -fsSL https://raw.githubusercontent.com/datadrivenconstruction/OpenConstructionERP/main/docker-compose.quickstart.image.yml -o docker-compose.override.yml
function New-Secret([int]$n) { $b = New-Object byte[] $n; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); -join ($b | ForEach-Object { $_.ToString("x2") }) }
Set-Content -Path .env -Encoding ascii -Value @("POSTGRES_PASSWORD=$(New-Secret 24)", "JWT_SECRET=$(New-Secret 32)")
docker compose pull app
docker compose up -d
```

3. Откройте в браузере **http://localhost:8080** и войдите как `demo@openconstructionerp.com` / `DemoPass1234!`.

В файле `.env` лежат пароль базы данных и секрет для входа, сохраните его. В следующий раз достаточно `docker compose up -d` в той же папке.

## Запуск в WSL (работает при включённой Smart App Control)

WSL это встроенная в Windows среда Linux от Microsoft.

1. Откройте **Windows PowerShell от имени администратора**, выполните `wsl --install` и перезагрузите компьютер, когда система попросит. При первом запуске Ubuntu попросит придумать имя пользователя и пароль.
2. В окне **Ubuntu** выполните:

```bash
sudo apt update && sudo apt install -y python3-venv
python3 -m venv ~/openconstructionerp
~/openconstructionerp/bin/pip install --upgrade openconstructionerp
~/openconstructionerp/bin/openconstructionerp
```

3. Откройте **http://localhost:8080** в браузере Windows. Первый запуск занимает минуту-две, пока создаётся база данных. В следующий раз откройте Ubuntu и выполните только последнюю строку.

## Запуск через pip в Windows (только при выключенной Smart App Control)

Если Smart App Control выключена или никогда не включалась, а установщик вы использовать не хотите, приложение можно запустить прямо из Python. Не рассчитывайте на этот способ как на обход Smart App Control: приложение запускает собственную базу PostgreSQL, программные файлы которой тоже не подписаны, и при включённой Smart App Control база будет заблокирована точно так же.

1. Скачайте Python 3.12 с [python.org/downloads/windows](https://www.python.org/downloads/windows/) и запустите установщик. На первом экране поставьте галочку **Add python.exe to PATH**, затем нажмите **Install Now**.
2. Откройте новое окно **Windows PowerShell** и выполните:

```powershell
py -3.12 -m pip install --upgrade openconstructionerp
py -3.12 -m openconstructionerp
```

3. Первый запуск создаёт локальную базу данных и загружает демо-данные, это занимает около минуты. Дальше приложение работает на **http://localhost:8080**; вход `demo@openconstructionerp.com` / `DemoPass1234!`. В следующий раз нужна только вторая команда.

## Проверьте, что файл настоящий

В каждом релизе рядом с установщиками лежит файл `SHA256SUMS`. Скачайте его в ту же папку, что и установщик, откройте там **Windows PowerShell** и выполните:

```powershell
$exe = Get-ChildItem OpenConstructionERP_*_x64-setup.exe | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$line = Select-String -Path SHA256SUMS -Pattern $exe.Name -SimpleMatch
(Get-FileHash $exe.FullName -Algorithm SHA256).Hash -eq $line.Line.Split(' ')[0]
```

`True` значит, что файл в точности тот, который собрала наша релизная сборка. `False` значит, что по дороге он повреждён или изменён, и запускать его не надо. Красное сообщение об ошибке вместо `True` или `False` значит, что `SHA256SUMS` в папке из другого релиза, чем установщик: скачайте оба файла с одной и той же страницы релиза. Если остаётся `False`, скачайте файл заново со [страницы релиза на GitHub](https://github.com/datadrivenconstruction/OpenConstructionERP/releases/latest). Проверка подтверждает, что файл цел. На решение SmartScreen или Smart App Control она не влияет. Для более строгой проверки у самого `SHA256SUMS` есть подпись Sigstore, она описана в [RELEASE_SIGNATURE_INVENTORY.md](RELEASE_SIGNATURE_INVENTORY.md).

## Если ничего не помогло

Напишите на info@datadrivenconstruction.io или откройте issue на GitHub. Укажите версию Windows (Пуск, введите `winver`), что показывает страница параметров Smart App Control, и точный текст сообщения.

## Источники

- Microsoft Learn, [SmartScreen reputation for Windows app developers](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation)
- Microsoft Learn, [Smart App Control overview](https://learn.microsoft.com/en-us/windows/apps/develop/smart-app-control/overview)
- Microsoft Support, [Вопросы и ответы об интеллектуальном управлении приложениями](https://support.microsoft.com/ru-ru/windows/smart-app-control-frequently-asked-questions-285ea03d-fa88-4d56-882e-6698afdb7003)
- Microsoft Support, [Smart App Control заблокировала часть этого приложения](https://support.microsoft.com/ru-ru/windows/security/threat-malware-protection/smart-app-control-has-blocked-part-of-this-app)
- Microsoft Support, [Управление приложениями и браузером в приложении "Безопасность Windows"](https://support.microsoft.com/ru-ru/windows/security/windows-security/app-browser-control-in-the-windows-security-app)
