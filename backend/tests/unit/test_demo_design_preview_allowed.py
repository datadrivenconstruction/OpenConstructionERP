"""The design editor draws its model from a POST dry run, so the read-only demo must let that one through."""

from fastapi import APIRouter

from app.core.demo_read_only import ALLOWED_ENDPOINTS, WriteScope, endpoint_key


def test_the_model_preview_key_names_the_mounted_endpoint():
    from app.modules.design import model_api

    router = APIRouter()
    model_api.register(router, can_edit=None)
    preview = [r for r in router.routes if r.path.endswith("/model/preview")]
    assert len(preview) == 1
    assert ALLOWED_ENDPOINTS.get(endpoint_key(preview[0].endpoint)) is WriteScope.NONE
    generate = [r for r in router.routes if r.path.endswith("/model/generate")]
    assert endpoint_key(generate[0].endpoint) not in ALLOWED_ENDPOINTS
