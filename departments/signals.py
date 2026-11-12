"""
Department lifecycle hooks.

The only thing that happens here is the cold-start guide: a department
without any document cannot answer anything, so every new department is
born with one small guide that explains how to use the platform.

A signal is used instead of a view hook on purpose. Departments can be
created through the API, the Django admin, a management command or a
fixture, and the guarantee "a new department always has a guide" must
hold for all of them.

Attribution is the one thing a signal cannot know by itself, so callers
that care wrap their write in `attributed_to(user)`. Everything else
falls back to the tenant's first admin.
"""

import contextvars
import logging
from contextlib import contextmanager

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Department

logger = logging.getLogger(__name__)

# The admin who is creating the department *right now*, if the caller
# told us. A ContextVar (not a thread-local) keeps the value scoped to
# the current request or task, which is what makes this safe under both
# WSGI and ASGI.
_pending_creator = contextvars.ContextVar(
    "department_creator",
    default=None,
)


@contextmanager
def attributed_to(user):
    """
    Attribute anything created inside this block to `user`.

    Used by the API so the generated guide belongs to the admin who
    actually created the department instead of an arbitrary one.
    """

    token = _pending_creator.set(user)

    try:
        yield
    finally:
        _pending_creator.reset(token)


@receiver(
    post_save,
    sender=Department,
    dispatch_uid="departments_seed_onboarding_document",
)
def seed_onboarding_document(sender, instance, created, **kwargs):
    """
    Give every new department its onboarding guide.

    Everything is wrapped in a try/except: this runs inside the
    department's own transaction, so an exception here would roll the
    department back. A missing guide is a degraded experience; a
    department that cannot be created at all is an outage.
    """

    if not created:
        return

    if getattr(instance, "_skip_onboarding", False):
        return

    # Imported here so app loading never depends on the documents app
    # being fully initialised.
    from documents.onboarding import (
        ensure_onboarding_document,
        resolve_guide_author,
    )

    try:
        ensure_onboarding_document(
            instance,
            created_by=resolve_guide_author(
                instance,
                _pending_creator.get(),
            ),
        )
    except Exception:
        logger.exception(
            "Could not create the onboarding guide for department %s.",
            instance.pk,
        )
