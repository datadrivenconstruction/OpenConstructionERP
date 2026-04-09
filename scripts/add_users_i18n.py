"""Add users module translations to all 20 locale files."""
import json
import os

LOCALES_DIR = os.path.join(os.path.dirname(__file__), "..", "backend", "locales")

EN = {
    "management": "User Management",
    "management_desc": "Manage team members, roles, and access",
    "invite_user": "Invite User",
    "invite": "Invite",
    "full_name": "Full Name",
    "email": "Email",
    "password": "Password",
    "role": "Role",
    "status": "Status",
    "last_login": "Last Login",
    "actions": "Actions",
    "name": "Name",
    "total": "Total Users",
    "active": "Active",
    "inactive": "Inactive",
    "admins": "Admins",
    "managers": "Managers",
    "search": "Search by name or email...",
    "no_users": "No users found",
    "updated": "User updated",
    "invited": "User invited successfully",
    "deactivate": "Deactivate",
    "activate": "Activate",
    "never": "Never",
    "role_admin_desc": "Full access to all features",
    "role_manager_desc": "Project and team management",
    "role_editor_desc": "Create and edit content",
    "role_viewer_desc": "Read-only access",
}

OVERRIDES = {
    "de": {"management": "Benutzerverwaltung", "management_desc": "Teammitglieder, Rollen und Zugriff verwalten", "invite_user": "Benutzer einladen", "invite": "Einladen", "full_name": "Vollst. Name", "email": "E-Mail", "password": "Passwort", "role": "Rolle", "last_login": "Letzter Login", "actions": "Aktionen", "total": "Benutzer gesamt", "active": "Aktiv", "inactive": "Inaktiv", "admins": "Administratoren", "search": "Nach Name oder E-Mail suchen...", "no_users": "Keine Benutzer gefunden", "updated": "Benutzer aktualisiert", "invited": "Benutzer eingeladen", "deactivate": "Deaktivieren", "activate": "Aktivieren", "never": "Nie", "role_admin_desc": "Vollzugriff", "role_manager_desc": "Projekt- und Teamverwaltung", "role_editor_desc": "Erstellen und bearbeiten", "role_viewer_desc": "Nur-Lese-Zugriff"},
    "ru": {"management": "\u0423\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u0438\u0435 \u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044f\u043c\u0438", "management_desc": "\u0423\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u0438\u0435 \u0443\u0447\u0430\u0441\u0442\u043d\u0438\u043a\u0430\u043c\u0438, \u0440\u043e\u043b\u044f\u043c\u0438 \u0438 \u0434\u043e\u0441\u0442\u0443\u043f\u043e\u043c", "invite_user": "\u041f\u0440\u0438\u0433\u043b\u0430\u0441\u0438\u0442\u044c", "invite": "\u041f\u0440\u0438\u0433\u043b\u0430\u0441\u0438\u0442\u044c", "full_name": "\u041f\u043e\u043b\u043d\u043e\u0435 \u0438\u043c\u044f", "email": "\u042d\u043b. \u043f\u043e\u0447\u0442\u0430", "password": "\u041f\u0430\u0440\u043e\u043b\u044c", "role": "\u0420\u043e\u043b\u044c", "status": "\u0421\u0442\u0430\u0442\u0443\u0441", "last_login": "\u041f\u043e\u0441\u043b\u0435\u0434\u043d\u0438\u0439 \u0432\u0445\u043e\u0434", "actions": "\u0414\u0435\u0439\u0441\u0442\u0432\u0438\u044f", "name": "\u0418\u043c\u044f", "total": "\u0412\u0441\u0435\u0433\u043e", "active": "\u0410\u043a\u0442\u0438\u0432\u043d\u044b\u0435", "inactive": "\u041d\u0435\u0430\u043a\u0442\u0438\u0432\u043d\u044b\u0435", "admins": "\u0410\u0434\u043c\u0438\u043d\u044b", "managers": "\u041c\u0435\u043d\u0435\u0434\u0436\u0435\u0440\u044b", "search": "\u041f\u043e\u0438\u0441\u043a \u043f\u043e \u0438\u043c\u0435\u043d\u0438 \u0438\u043b\u0438 email...", "no_users": "\u041f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u0438 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u044b", "updated": "\u041f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044c \u043e\u0431\u043d\u043e\u0432\u043b\u0451\u043d", "invited": "\u041f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044c \u043f\u0440\u0438\u0433\u043b\u0430\u0448\u0451\u043d", "deactivate": "\u0414\u0435\u0430\u043a\u0442\u0438\u0432\u0438\u0440\u043e\u0432\u0430\u0442\u044c", "activate": "\u0410\u043a\u0442\u0438\u0432\u0438\u0440\u043e\u0432\u0430\u0442\u044c", "never": "\u041d\u0438\u043a\u043e\u0433\u0434\u0430", "role_admin_desc": "\u041f\u043e\u043b\u043d\u044b\u0439 \u0434\u043e\u0441\u0442\u0443\u043f", "role_manager_desc": "\u0423\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u0438\u0435 \u043f\u0440\u043e\u0435\u043a\u0442\u0430\u043c\u0438", "role_editor_desc": "\u0421\u043e\u0437\u0434\u0430\u043d\u0438\u0435 \u0438 \u0440\u0435\u0434\u0430\u043a\u0442\u0438\u0440\u043e\u0432\u0430\u043d\u0438\u0435", "role_viewer_desc": "\u0422\u043e\u043b\u044c\u043a\u043e \u043f\u0440\u043e\u0441\u043c\u043e\u0442\u0440"},
    "fr": {"management": "Gestion des utilisateurs", "active": "Actif", "inactive": "Inactif", "deactivate": "D\u00e9sactiver", "activate": "Activer", "never": "Jamais"},
    "es": {"management": "Gesti\u00f3n de usuarios", "active": "Activo", "inactive": "Inactivo", "deactivate": "Desactivar", "activate": "Activar", "never": "Nunca"},
    "pt": {"management": "Gest\u00e3o de Utilizadores", "active": "Ativo", "inactive": "Inativo", "never": "Nunca"},
    "it": {"management": "Gestione Utenti", "active": "Attivo", "inactive": "Inattivo", "never": "Mai"},
    "nl": {"management": "Gebruikersbeheer", "active": "Actief", "inactive": "Inactief", "never": "Nooit"},
    "pl": {"management": "Zarz\u0105dzanie u\u017cytkownikami", "active": "Aktywny", "inactive": "Nieaktywny", "never": "Nigdy"},
    "cs": {"management": "Spr\u00e1va u\u017eivatel\u016f", "active": "Aktivn\u00ed", "inactive": "Neaktivn\u00ed", "never": "Nikdy"},
    "tr": {"management": "Kullan\u0131c\u0131 Y\u00f6netimi", "active": "Aktif", "inactive": "Pasif", "never": "Hi\u00e7"},
    "ar": {"management": "\u0625\u062f\u0627\u0631\u0629 \u0627\u0644\u0645\u0633\u062a\u062e\u062f\u0645\u064a\u0646", "active": "\u0646\u0634\u0637", "inactive": "\u063a\u064a\u0631 \u0646\u0634\u0637", "never": "\u0623\u0628\u062f\u0627\u064b"},
    "zh": {"management": "\u7528\u6237\u7ba1\u7406", "active": "\u6d3b\u8dc3", "inactive": "\u672a\u6d3b\u8dc3", "never": "\u4ece\u672a"},
    "ja": {"management": "\u30e6\u30fc\u30b6\u30fc\u7ba1\u7406", "active": "\u30a2\u30af\u30c6\u30a3\u30d6", "inactive": "\u975e\u30a2\u30af\u30c6\u30a3\u30d6", "never": "\u306a\u3057"},
    "ko": {"management": "\uc0ac\uc6a9\uc790 \uad00\ub9ac", "active": "\ud65c\uc131", "inactive": "\ube44\ud65c\uc131", "never": "\uc5c6\uc74c"},
    "hi": {"management": "\u0909\u092a\u092f\u094b\u0917\u0915\u0930\u094d\u0924\u093e \u092a\u094d\u0930\u092c\u0902\u0927\u0928", "active": "\u0938\u0915\u094d\u0930\u093f\u092f", "inactive": "\u0928\u093f\u0937\u094d\u0915\u094d\u0930\u093f\u092f", "never": "\u0915\u092d\u0940 \u0928\u0939\u0940\u0902"},
    "sv": {"management": "Anv\u00e4ndarhantering", "active": "Aktiv", "inactive": "Inaktiv", "never": "Aldrig"},
    "no": {"management": "Brukeradministrasjon", "active": "Aktiv", "inactive": "Inaktiv", "never": "Aldri"},
    "da": {"management": "Brugeradministration", "active": "Aktiv", "inactive": "Inaktiv", "never": "Aldrig"},
    "fi": {"management": "K\u00e4ytt\u00e4j\u00e4hallinta", "active": "Aktiivinen", "inactive": "Ei-aktiivinen", "never": "Ei koskaan"},
}

updated = 0
for fname in sorted(os.listdir(LOCALES_DIR)):
    if not fname.endswith(".json"):
        continue
    lang = fname.replace(".json", "")
    fpath = os.path.join(LOCALES_DIR, fname)
    with open(fpath, "r", encoding="utf-8") as f:
        data = json.load(f)
    merged = dict(EN)
    if lang in OVERRIDES:
        merged.update(OVERRIDES[lang])
    data["users"] = merged
    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    updated += 1

print(f"Updated {updated} locale files with users translations")
