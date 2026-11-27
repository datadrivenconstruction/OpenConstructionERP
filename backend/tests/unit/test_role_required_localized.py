"""A role refusal answers in the caller's language and names the role."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.core.i18n import set_locale
from app.dependencies import RequireRole


@pytest.mark.asyncio
async def test_role_refusal_is_localized() -> None:
    set_locale("de")
    try:
        with pytest.raises(HTTPException) as exc:
            await RequireRole("manager")({"role": "editor", "sub": "u"})
    finally:
        set_locale("en")
    assert exc.value.status_code == 403
    assert "manager" in exc.value.detail
    assert "Role '" not in exc.value.detail
    assert "Rolle" in exc.value.detail
