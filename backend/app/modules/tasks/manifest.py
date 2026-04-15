"""Tasks module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_tasks",
    version="0.1.0",
    display_name="Tasks",
    description=(
        "Project task management — tasks, topics, decisions,"
        " and personal items with checklists and assignment workflows"
    ),
    author="OpenEstimate Core Team",
    category="core",
    depends=["oe_users", "oe_projects"],
    auto_install=True,
    enabled=True,
)
