"""Deployment settings (Design 021): who can reach the history, and what
it holds.

Three environment variables, read in one place so the app and the CLI
cannot disagree about them:

``MAPCHECK_MODE``
    ``single`` (default) is one operator on a laptop or a private
    container: one history, all of it visible. ``shared`` assumes more
    than one person can reach the URL, so the app scopes history to the
    browser session and offers no database download.

``MAPCHECK_HISTORY_VALUES``
    What a recorded finding keeps: ``full`` (expected and actual
    verbatim), ``redacted`` (a keyed hash, so a change is still detected
    but never shown) or ``none`` (counts and results only). Unset, it
    follows the mode: ``full`` in ``single``, ``redacted`` in ``shared``.

``MAPCHECK_PASSWORD``
    Optional shared secret in front of the whole app. Off unless set.

An unknown value is an error, never a fallback. A typo in
``MAPCHECK_MODE`` that quietly meant ``single`` would publish every
visitor's runs to every other visitor, which is the failure this module
exists to prevent.
"""

from __future__ import annotations

import hmac
import os
from collections.abc import Mapping

MODE_SINGLE = "single"
MODE_SHARED = "shared"
MODES = (MODE_SINGLE, MODE_SHARED)

VALUES_FULL = "full"
VALUES_REDACTED = "redacted"
VALUES_NONE = "none"
VALUES_MODES = (VALUES_FULL, VALUES_REDACTED, VALUES_NONE)

ENV_MODE = "MAPCHECK_MODE"
ENV_VALUES = "MAPCHECK_HISTORY_VALUES"
ENV_PASSWORD = "MAPCHECK_PASSWORD"


class DeploymentConfigError(ValueError):
    """A deployment variable holds a value this version does not know."""


def _setting(
    name: str, allowed: tuple[str, ...], environ: Mapping[str, str] | None
) -> str | None:
    """The named variable, normalized, or None when unset or blank."""
    env = os.environ if environ is None else environ
    raw = env.get(name, "").strip().lower()
    if not raw:
        return None
    if raw not in allowed:
        raise DeploymentConfigError(
            f"{name}={env.get(name)!r} is not valid; use one of: "
            + ", ".join(allowed)
        )
    return raw


def deployment_mode(environ: Mapping[str, str] | None = None) -> str:
    """``single`` unless ``MAPCHECK_MODE`` says ``shared``."""
    return _setting(ENV_MODE, MODES, environ) or MODE_SINGLE


def history_values_explicit(environ: Mapping[str, str] | None = None) -> bool:
    """Whether the operator chose the storage setting themselves."""
    return _setting(ENV_VALUES, VALUES_MODES, environ) is not None


def history_values(environ: Mapping[str, str] | None = None) -> str:
    """What recorded findings keep.

    An explicit ``MAPCHECK_HISTORY_VALUES`` always wins. Without one the
    setting follows the mode: a shared store holds several people's
    partner data in one file, so it keeps hashes unless told otherwise.
    """
    explicit = _setting(ENV_VALUES, VALUES_MODES, environ)
    if explicit is not None:
        return explicit
    if deployment_mode(environ) == MODE_SHARED:
        return VALUES_REDACTED
    return VALUES_FULL


def app_password(environ: Mapping[str, str] | None = None) -> str | None:
    """The shared secret gating the app, or None when the gate is off.

    A blank value counts as unset: an empty password would be a gate
    that opens for anyone who submits the form untouched.
    """
    env = os.environ if environ is None else environ
    return env.get(ENV_PASSWORD) or None


def password_matches(entered: str, expected: str) -> bool:
    """Constant-time comparison of the entered password with the secret."""
    return hmac.compare_digest(entered.encode("utf-8"), expected.encode("utf-8"))
