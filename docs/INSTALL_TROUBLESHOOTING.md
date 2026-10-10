# Installation help and troubleshooting

Also available in [Deutsch](INSTALL_TROUBLESHOOTING.de.md) and [Русский](INSTALL_TROUBLESHOOTING.ru.md).

This page is for you if OpenConstructionERP shows a warning or an error while you install or start it. Find the message you see, read what it means, and do what the third line says. Most cases take a minute to fix and none of them put your projects at risk.

For a normal installation without problems, see [Install OpenConstructionERP](desktop/INSTALL.md).

## Before anything else: the log files

When something goes wrong, the app writes what happened to a log file. If you write to us, attach these files. They help us find the cause on the first try.

| File | Where it is | What it holds |
|---|---|---|
| `desktop-launcher.log` | Windows: `C:\Users\<your name>\.openestimate\`<br>macOS and Linux: `~/.openestimate/` | Everything the desktop app did while starting |
| `backend-crash.log` | the `logs` folder inside your data folder, which is the same `.openestimate` folder unless you set `OE_DATA_DIR` | Details of an unexpected stop |
| `OpenConstructionERP-install-error.log` | Windows: `%TEMP%` (type `%TEMP%` into the Explorer address bar) | Why the installer refused to install |

The `.openestimate` folder is hidden on macOS and Linux. On a Mac, press Cmd+Shift+. in Finder to show hidden folders.

If you installed with pip, run `openconstructionerp doctor` in a terminal. It checks the usual problems, such as a busy port or a missing database, and prints what to do about each one.

## Windows: while installing

**You see:** a blue window "Windows protected your PC".
**It means:** the installer is not code signed yet, so Windows does not know the publisher. It is a warning, not a virus finding.
**Do:** click **More info**, check that the file name starts with `OpenConstructionERP`, then click **Run anyway**. Details and a way to check the download are in [Windows blocks the app](desktop/WINDOWS_BLOCKED.md).

**You see:** Smart App Control says it blocked the app, or the app ran once and is blocked on every start since.
**It means:** Windows 11 Smart App Control refuses unsigned programs and offers no button to continue.
**Do:** follow [Windows blocks the app](desktop/WINDOWS_BLOCKED.md). It explains how to tell which feature blocked the app and how to run it with Docker or WSL while Smart App Control stays on.

**You see:** "Please choose an installation folder whose path uses only Latin letters, digits and spaces. The built-in database cannot start from a folder with other characters in its path".
**It means:** the folder you picked has letters such as Cyrillic, Chinese or accented ones in its path. The built-in database cannot start from such a folder.
**Do:** keep the suggested folder `C:\Program Files\OpenConstructionERP`, or pick one like `C:\OpenConstructionERP`. In a silent installation (`/S`) the installer shows the same message, exits with code 3 and writes the reason to `%TEMP%\OpenConstructionERP-install-error.log`.

**You see:** the installer stops with an error about WebView2.
**It means:** Windows could not install Microsoft WebView2, the component that draws the app window. The installer brings it along, but Windows has to accept it.
**Do:** run the installer again. If it fails again, install "Microsoft Edge WebView2 Runtime" from the Microsoft website and then run our installer once more.

**You see:** your antivirus deletes or quarantines a file during the installation.
**It means:** the program is new and unsigned, so some antivirus products treat it with suspicion.
**Do:** check the download as described in [Windows blocks the app](desktop/WINDOWS_BLOCKED.md). If the check says `True`, restore the file from quarantine and allow the folder `C:\Program Files\OpenConstructionERP` in your antivirus. If you are not sure, write to us before you allow anything.

## Windows: upgrading to a new version

**You see:** a screen asking whether to write over the installed version or to remove it first, with a line above that suggests removing it.
**It means:** that line comes from the installer toolkit and we cannot change it.
**Do:** keep the option that is already selected (write over it). The installer closes the running app for you and keeps all your projects. The first start after an upgrade can take longer while the database updates itself.

**You see:** you also run OpenConstructionERP with pip or from a terminal on the same computer.
**It means:** both use the same `.openestimate` folder and the same database. The installer stops that database to replace the program files, which cuts off the terminal version.
**Do:** stop the terminal version (Ctrl+C in its window) before you install or upgrade, and start it again afterwards.

**You see:** the old version's uninstall window appears in the middle of an upgrade.
**It means:** you chose to remove the old version first. That works, it only takes longer.
**Do:** let it finish. If it offers "Delete the application data", you can leave it unticked. It does not remove your projects either way.

## Windows: while starting

**You see:** the loading screen for a minute or more on the very first start.
**It means:** the app is creating its local database. This takes about 40 to 90 seconds once, and longer on a slow disk.
**Do:** wait and do not close the window. Later starts are fast.

**You see:** a box "OpenConstructionERP failed to start" that names a log file.
**It means:** the app could not open its window at all.
**Do:** start it once more. If the box comes back, send us the log file it names.

**You see:** "The backend started, but the local database is not answering, so the app cannot open."
**It means:** the local database did not come up, often because a previous run did not close cleanly.
**Do:** restart the computer and start the app again. If it repeats, send us `desktop-launcher.log`.

**You see:** "The backend started, but this installation is missing the application files it serves".
**It means:** part of the program folder is missing, usually removed by antivirus.
**Do:** check your antivirus quarantine, then run the installer again over the existing installation. Your projects are not touched.

**You see:** "The application backend did not start in time", or "The application backend stopped responding while preparing the local database" (or another step).
**It means:** the start took longer than the app waits. The message names the step it was on.
**Do:** close the window and start again. On a slow or nearly full disk, free some space first. If it stops at the same step again, send us `desktop-launcher.log`.

**You see:** "The drive ran out of space while the application was starting" or "There is not enough free space to start the application".
**It means:** exactly that. The message names the folder and how much space is left on its drive.
**Do:** free space on that drive and start the app again.

**You see:** a message that the folder for the local database "sits too deep in the filesystem", with two numbers in characters.
**It means:** Windows limits how long a full file path may be, and your data folder path is too long for the database files inside it. Reinstalling into the same place will not help, and switching on long paths in Windows does not help either.
**Do:** use a shorter data folder. Set the user environment variable `OE_DATA_DIR` to a short path such as `C:\OpenConstructionERP\data` (Start, type "environment variables", "Edit environment variables for your account", New), then start the app again. If you run it from a terminal, use `openconstructionerp serve --data-dir C:\OpenConstructionERP\data`.

**You see:** your Windows user name has non-Latin letters (for example Cyrillic or Chinese), and you look for your database.
**It means:** the database cannot work from such a path, so the app keeps it in `C:\ProgramData\OpenConstructionERP\clusters\<id>\pgdata`. The file `pgdata.location` in your `.openestimate` folder names the exact folder.
**Do:** nothing to fix. For backups, copy both `.openestimate` and the folder named in `pgdata.location`.

**You see:** "The application backend stopped, restarting" and the window reloads.
**It means:** the background part of the app stopped unexpectedly and the app restarted it. Your saved work is kept. It does this at most twice in 30 minutes.
**Do:** carry on. If it happens again and again, or you then see "The application backend has stopped", send us `desktop-launcher.log` and `logs\backend-crash.log`.

**You see:** after a restart you are signed out and the language is back to English.
**It means:** another program was using the app's usual port 8732, so the app picked a different one. The browser view treats a different port as a different site.
**Do:** sign in again. To keep it from happening, close the other program that uses port 8732.

**You see:** "The application could not unpack itself into the temporary folder it uses."
**It means:** antivirus removed or locked files while the app unpacked them, or the drive with the temporary folder is full. On Windows this applies to versions up to 18.4; from 18.5 the Windows app no longer unpacks itself on each start.
**Do:** free space on that drive, or allow the app in your antivirus, then start again.

## macOS

**You see:** the `.dmg` does not open on your Mac at all.
**It means:** the Mac build is for Apple Silicon (M1 and later) only. There is no build for Intel Macs.
**Do:** on an Intel Mac, use pip or Docker as described in the README.

**You see:** "OpenConstructionERP is damaged and can't be opened", or "cannot be opened because the developer cannot be verified".
**It means:** the app is not notarized by Apple yet, and macOS blocks downloaded apps it cannot check. The app is not damaged.
**Do:** open Terminal and run once:

```
xattr -dr com.apple.quarantine /Applications/OpenConstructionERP.app
```

Or right-click the app in Applications and choose **Open**. On recent macOS go to **System Settings**, **Privacy & Security**, scroll down and click **Open Anyway**. You need to do this only once.

## Linux

**You see:** the `.deb` asks for `libwebkit2gtk-4.1-0` or refuses to install.
**It means:** the app needs the WebKitGTK 4.1 library to draw its window.
**Do:** install it with `sudo apt install ./OpenConstructionERP_*_amd64.deb`, which pulls the library in. On older distributions that do not offer version 4.1, use the AppImage or pip.

**You see:** the AppImage does nothing when you double-click it.
**It means:** the file is not marked as a program yet.
**Do:** run `chmod +x OpenConstructionERP*.AppImage` and start it again.

**You see:** an AppImage error that mentions FUSE or `libfuse.so.2`.
**It means:** newer distributions no longer install the FUSE 2 library that AppImages use.
**Do:** install it, for example `sudo apt install libfuse2` (on Ubuntu 24.04 the package is `libfuse2t64`), or use the `.deb`, `.rpm` or pip instead.

**You see:** a release has no AppImage.
**It means:** the AppImage is built separately and occasionally fails while the other files are fine.
**Do:** use the `.deb` or `.rpm` from the same release.

## pip (any system)

**You see:** pip says no matching version was found, or that Python is too old.
**It means:** OpenConstructionERP needs Python 3.12 or newer.
**Do:** install Python 3.12 or newer and run `python3.12 -m pip install --upgrade openconstructionerp` (on Windows `py -3.12 -m pip ...`).

**You see:** "Port 8080 is already in use. Try: openconstructionerp serve --port 8081".
**It means:** another program uses port 8080.
**Do:** run the command it suggests and open the address it prints.

**You see:** you are not sure where your data is.
**It means:** pip keeps everything in `.openestimate` in your home folder, the same folder the desktop app uses.
**Do:** to keep it elsewhere, start with `openconstructionerp serve --data-dir <folder>` or set `OE_DATA_DIR`.

## Docker

**You see:** http://localhost:8080 does not open.
**It means:** the container is not running, or another program uses port 8080.
**Do:** run `docker compose ps` in the folder with `docker-compose.yml` and `docker compose logs app` to see why. Keep the `.env` file in that folder safe: it holds the database password and the sign-in secret.

## Uninstalling and your data

Uninstalling removes the program and keeps your projects. They live in the `.openestimate` folder in your home folder (plus the `ProgramData` folder above, if your user name has non-Latin letters). Reinstalling therefore does not start you over. To start from scratch, uninstall and then delete `.openestimate` yourself, after you have copied it somewhere safe.

## Still stuck

Write to info@datadrivenconstruction.io or open an issue at [github.com/datadrivenconstruction/OpenConstructionERP/issues](https://github.com/datadrivenconstruction/OpenConstructionERP/issues). Please include:

- the version you installed and how (Windows installer, `.dmg`, `.deb`, `.rpm`, AppImage, pip or Docker),
- your system (Windows: Start, type `winver`; macOS: Apple menu, About This Mac),
- the exact text of the message, or a screenshot,
- the log files from the top of this page.
