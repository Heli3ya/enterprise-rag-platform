"""
Purging the searchable footprint of superseded document versions.

Archiving a version already takes it out of the search path: every
retrieval query filters on `Document.status`. That is a *logical*
guarantee, and on its own it is not enough. The text and the vectors of
the old version stay on disk, so:

* one query written later that forgets the status filter, a restored
  backup, or a "show archived documents" toggle would put the obsolete
  procedure back in front of a user;
* storage grows with every revision of every document, forever.

So the moment the replacement is fully indexed, a worker walks back up
the chain and erases what it replaced. Two different techniques,
because the two tables have different constraints:

* **Chunks are tombstoned** (`is_active = False`) rather than deleted.
  `build_citations` resolves an old answer's sources by chunk id;
  deleting the row would blank the citations of answers that were
  already delivered. The text stays readable for history and becomes
  invisible to every retrieval path.
* **Embeddings are deleted.** A vector is the one artifact that can
  bring a superseded passage back to life, and leaving it in the HNSW
  graph — even flagged — still costs memory and still leaves it one
  forgotten filter away from being returned.

The purge runs after indexing, not at upload time. Purging on upload
would destroy the old version's index before the new one is usable, and
a failed extraction would leave the department with no searchable text
at all.
"""

import logging

from django.db import transaction
from django.utils import timezone

from .models import Document, DocumentChunk, Embedding
from .versioning import ARCHIVED_STATUS, MAX_CHAIN_LENGTH


logger = logging.getLogger(__name__)


def superseded_ancestors(document):
    """
    Every archived version above `document`, nearest first.

    Walks the parent links rather than loading the whole chain: the
    downward walk `version_chain` does would fetch the current version
    and its descendants, which are exactly the rows we must not touch.

    A version that is not archived is skipped but not a stop sign — a
    half-repaired chain should still let the worker reach the rows
    above it.
    """

    ancestors = []
    seen = {document.id}
    current = document
    hops = 0

    while (
        current.parent_document_id is not None
        and hops < MAX_CHAIN_LENGTH
    ):
        hops += 1

        parent = (
            Document.objects
            .filter(pk=current.parent_document_id)
            .first()
        )

        if parent is None or parent.id in seen:
            break

        seen.add(parent.id)

        if parent.status == ARCHIVED_STATUS:
            ancestors.append(parent)

        current = parent

    return ancestors


def purge_version(document, when=None):
    """
    Remove one archived version from the search index.

    Idempotent by construction: tombstoning already-dead chunks updates
    zero rows, and deleting already-deleted vectors is a no-op. The
    embedding delete runs on every call regardless, because a batch that
    was in flight during the first purge can have written a vector after
    it — and that is the only way a superseded passage gets back into
    the index.

    Returns a per-version summary.
    """

    moment = when or timezone.now()

    with transaction.atomic():
        locked = (
            Document.objects
            .select_for_update()
            .filter(pk=document.pk)
            .first()
        )

        if locked is None:
            return {"document_id": document.id, "skipped": "missing"}

        if locked.status != ARCHIVED_STATUS:
            # Someone restored the version between the trigger and this
            # run. Its text is live again, so it must keep its index.
            return {
                "document_id": locked.id,
                "skipped": "not_archived",
            }

        already_purged = locked.purged_at is not None

        chunks_tombstoned = (
            DocumentChunk.objects
            .filter(document_id=locked.id, is_active=True)
            .update(is_active=False, purged_at=moment)
        )

        embeddings_deleted, _ = (
            Embedding.objects
            .filter(chunk__document_id=locked.id)
            .delete()
        )

        # Keep the first timestamp: it answers "since when is this
        # version out of the index?", and a retry must not move it.
        Document.objects.filter(
            pk=locked.id,
            purged_at__isnull=True,
        ).update(purged_at=moment)

    logger.info(
        "Purged document %s (v%s): %s chunk(s) tombstoned, "
        "%s vector(s) deleted.",
        locked.id,
        locked.version,
        chunks_tombstoned,
        embeddings_deleted,
    )

    return {
        "document_id": locked.id,
        "version": locked.version,
        "chunks_tombstoned": chunks_tombstoned,
        "embeddings_deleted": embeddings_deleted,
        "already_purged": already_purged,
    }


def purge_superseded_versions(document):
    """
    Purge every version `document` replaced, and summarise the total.

    Runs the whole chain rather than only the immediate parent: if an
    earlier cleanup was lost (worker down, task expired), the next
    successful index repairs the gap without a separate repair job.
    """

    results = [
        purge_version(ancestor)
        for ancestor in superseded_ancestors(document)
    ]

    return {
        "document_id": document.id,
        "versions_purged": len(results),
        "chunks_tombstoned": sum(
            result.get("chunks_tombstoned", 0)
            for result in results
        ),
        "embeddings_deleted": sum(
            result.get("embeddings_deleted", 0)
            for result in results
        ),
        "results": results,
    }
