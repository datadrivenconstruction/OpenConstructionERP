# Module Template

Use this as a starting point for creating OpenEstimate modules.

## Structure

```
your-module/
├── manifest.py      # REQUIRED: module metadata, version, dependencies
├── __init__.py      # Package init
├── router.py        # API routes (auto-mounted)
├── models.py        # Database models (auto-registered)
├── schemas.py       # Pydantic request/response models
├── service.py       # Business logic
├── repository.py    # Data access
├── hooks.py         # Hook handlers (filters & actions)
├── events.py        # Event handlers
├── validators.py    # Custom validation rules
├── locales/         # Module-specific translations
│   ├── en.json
│   └── de.json
└── tests/           # Module tests
```

## Quick Start

```bash
# From project root
make module-new NAME=oe_my_module

# Or manually:
cp -r modules/oe-module-template modules/my_module
# Edit manifest.py with your module details
```

## Installation

Users install your module by:
```bash
# From zip file
openestimate module install my-module-1.0.0.zip

# Or copy to modules/ directory and restart
```
