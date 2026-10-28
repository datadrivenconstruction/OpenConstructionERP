# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The weak-JWT-secret rules have one source of truth, and it is strict.

These constants used to exist twice, in ``app/config.py`` and in
``app/main.py``, maintained by hand. They had already drifted: the copy in
``main.py`` omitted three of the denied strings and measured length in UTF-8
bytes where the other measured characters. Nothing compared them, so nothing
reported it.

``scripts/check_secret_denylist_single_source.py`` keeps a second copy from
reappearing. These tests pin the behaviour the single copy must have, including
the cases on which the two old copies disagreed.
"""

import pytest

from app.config import (
    _JWT_SECRET_MIN_LENGTH,
    Settings,
    jwt_secret_is_known_weak,
    jwt_secret_is_too_short,
)


class TestKnownWeakSecrets:
    @pytest.mark.parametrize(
        "secret",
        [
            "openestimate-local-dev-key",
            "change-me",
            "change-me-in-production",
            "secret",
            "jwt-secret",
        ],
    )
    def test_denied_values_are_recognised(self, secret):
        assert jwt_secret_is_known_weak(secret) is True

    @pytest.mark.parametrize("secret", ["change-me", "secret", "jwt-secret"])
    def test_the_three_the_second_copy_had_lost(self, secret):
        """These were denied by config.py and accepted by main.py's own set.

        Whichever file a reader happened to open decided what they believed the
        rule was. That is the whole failure, expressed as three strings.
        """
        assert jwt_secret_is_known_weak(secret) is True

    def test_a_real_secret_is_not_flagged(self):
        assert jwt_secret_is_known_weak("q7Yb2f0Xk9Lm4Rt8Wz1Cv6Nh3Jp5Sd0Ag") is False

    def test_none_and_empty_are_tolerated_not_crashed_on(self):
        assert jwt_secret_is_known_weak("") is False
        assert jwt_secret_is_known_weak(None) is False  # type: ignore[arg-type]


class TestMinimumLength:
    def test_short_ascii_is_short(self):
        assert jwt_secret_is_too_short("x" * (_JWT_SECRET_MIN_LENGTH - 1)) is True

    def test_exactly_the_minimum_is_accepted(self):
        assert jwt_secret_is_too_short("x" * _JWT_SECRET_MIN_LENGTH) is False

    def test_empty_is_short(self):
        assert jwt_secret_is_too_short("") is True

    def test_non_ascii_is_judged_by_the_stricter_of_the_two_measures(self):
        """The case on which the two old copies gave opposite answers.

        Twenty Cyrillic characters are forty UTF-8 bytes. The byte rule in
        ``main.py`` called that long enough; the character rule in
        ``config.py`` called it too short. Keeping both and taking the stricter
        answer means the collapse cannot quietly loosen the check.
        """
        twenty_chars_forty_bytes = "п" * 20
        assert len(twenty_chars_forty_bytes) == 20
        assert len(twenty_chars_forty_bytes.encode("utf-8")) == 40
        assert jwt_secret_is_too_short(twenty_chars_forty_bytes) is True


class TestSettingsRefusesToStart:
    """The validator is a model validator, so it fires on construction.

    This is why the equivalent block in ``main.py`` could never be reached for
    a non-development environment: ``Settings()`` raises long before startup
    code inspects the secret.
    """

    @pytest.mark.parametrize("secret", ["change-me", "secret", "jwt-secret"])
    def test_staging_refuses_a_string_only_the_canonical_list_knew(self, secret):
        with pytest.raises(RuntimeError, match="well-known weak default"):
            Settings(app_env="staging", jwt_secret=secret)

    def test_staging_refuses_a_short_secret(self):
        with pytest.raises(RuntimeError, match="characters"):
            Settings(app_env="staging", jwt_secret="x" * (_JWT_SECRET_MIN_LENGTH - 1))

    def test_development_still_starts_on_the_bundled_default(self):
        """A fresh clone must run with no .env, so dev stays a no-op."""
        settings = Settings(app_env="development", jwt_secret="openestimate-local-dev-key")
        assert settings.app_env == "development"

    def test_staging_accepts_a_strong_secret(self):
        settings = Settings(app_env="staging", jwt_secret="q7Yb2f0Xk9Lm4Rt8Wz1Cv6Nh3Jp5Sd0Ag")
        assert settings.app_env == "staging"
