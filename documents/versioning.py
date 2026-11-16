"""
Version chains for documents.

A document is never edited in place. Uploading a replacement creates a
new `Document` row that points at the version it replaces, and retires
the old row. Two things follow from that and both matter:

* The old row keeps its text and its file, so a citation that was
  issued last month still resolves to the passage the user actually
  read. Deleting it would rewrite history.
* The old row loses its embeddings. The HNSW index is the one place
  where a stale version would come back to life: a vector search does
  not know that a chunk is obsolete, so the cheapest correct answer is
  to remove the vectors and leave the text.

`archive_document` is the only place that changes a status to
`Archived`, so the invariant "archived means no vectors" is enforced in
one place instead of at every call site.
"""

import logging

from django.utils import timezone

from .models import Document, Embedding


logger = logging.getLogger(__name__)


ARCHIVED_STATUS = "Archived"

# A chain longer than this is a bug or an import gone wrong. The cap
# keeps a malformed parent link from turning into an infinite loop.
MAX_CHAIN_LENGTH = 100


class VersionConflict(Exception):
    """
    The requested operation does not fit the current state of the chain.

    Raised for "this version has already been superseded" and for a
    concurrent upload that lost the race on the unique constraint. The
    view turns it into a 409 with a message the user can act on.
    """


def archive_document(document, when=None):
    """
    Retire a version: mark it, then drop its vectors.

    The order matters. The status change is what the API reports and
    what every query filters on; the embedding delete is what keeps the
    vector index honest. Both happen in the caller's transaction, so no
    reader can observe "archived but still searchable".

    Returns the number of embedding rows removed.
    """

    document.status = ARCHIVED_STATUS
    document.archived_at = when or timezone.now()

    document.save(update_fields=["status", "archived_at"])

    deleted, _ = Embedding.objects.filter(
        chunk__document_id=document.id,
    ).delete()

    logger.info(
        "Archived document %s (v%s), removed %s embeddings.",
        document.id,
        document.version,
        deleted,
    )

    return deleted


def next_version_number(parent):
    """The number the replacement of `parent` must carry."""

    return (parent.version or 1) + 1


def version_chain(document):
    """
    Every version of one document, oldest first.

    Walks up to the root and then down through `next_versions`. Both
    walks are bounded: a chain is linear, so each step has at most one
    child, and `MAX_CHAIN_LENGTH` stops a corrupted link from looping.

    Costs one query per hop, which is fine for the two places that use
    it: the versions endpoint (a handful of hops) and the conflict
    message (one hop in the common case).
    """

    seen = {document.id}
    root = document

    while root.parent_document_id is not None:
        parent = root.parent_document

        if parent is None or parent.id in seen:
            break

        seen.add(parent.id)
        root = parent

    chain = [root]
    # A fresh set for the downward walk: the upward one already holds
    # the document we started from, which is a descendant of the root
    # and would otherwise stop the walk at the first hop.
    seen = {root.id}
    current = root

    while len(chain) < MAX_CHAIN_LENGTH:
        child = (
            Document.objects
            .filter(parent_document_id=current.id)
            .order_by("-version")
            .first()
        )

        if child is None or child.id in seen:
            break

        seen.add(child.id)
        chain.append(child)
        current = child

    return chain


def latest_version(document):
    """The newest version in the chain that contains `document`."""

    return version_chain(document)[-1]


def is_current(document):
    """True when this row is the newest, still-active version."""

    if document.status == ARCHIVED_STATUS:
        return False

    return latest_version(document).id == document.id


def delete_chain(document):
    """
    Delete a document and every version of it.

    Deleting only the row the user clicked would leave the archived
    versions behind as invisible zombies: they are hidden from the
    list, so nobody could ever clean them up. A document is one logical
    thing, so its history goes with it.

    Returns the ids that were removed.
    """

    chain = version_chain(document)
    ids = [item.id for item in chain]

    for item in chain:
        if item.file_path:
            item.file_path.delete(save=False)

    Document.objects.filter(id__in=ids).delete()

    logger.info(
        "Deleted %s version(s) of document %s.",
        len(ids),
        ids[0] if ids else None,
    )

    return ids
