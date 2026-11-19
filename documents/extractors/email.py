"""
Turn an RFC 822 message into searchable passages.

A `.eml` file is headers, a blank line, then a body that may be split
into parts (plain text, HTML, attachments) and encoded in anything from
UTF-8 to base64 to Windows-1256.

The body alone is not enough. Two of the fields a user actually searches
for — who sent it and what it is about — live in the headers, and an
answer drawn from the body without them cannot be attributed. So each
passage carries the metadata and the text together, which is also what
the acceptance criteria for this feature ask for: a search for a sender
or a subject must return the email.

Long emails are still split, because the embedding model truncates
around 512 tokens and anything past that would be unsearchable. Every
continuation chunk repeats a compact header, so the sender and subject
stay reachable no matter which chunk the search lands on.
"""

import email
import email.policy
import logging
import os
from datetime import timezone
from email.header import decode_header, make_header
from email.utils import getaddresses, parsedate_to_datetime
from html.parser import HTMLParser

from ..chunking import chunk_text


logger = logging.getLogger(__name__)


# The same chunk geometry the rest of the pipeline uses, so an email
# chunk sits in the index next to a PDF chunk without behaving
# differently at retrieval time.
CHUNK_SIZE = 400
CHUNK_OVERLAP = 10

# A thread with a long history can carry megabytes of quoted replies.
# The cap is on the body only; the headers are always kept.
MAX_BODY_CHARACTERS = int(
    os.getenv("EMAIL_MAX_BODY_CHARS", "40000")
)

# Headers worth carrying. `Message-ID` is kept because two emails with
# the same subject are otherwise indistinguishable in the preview.
HEADER_FIELDS = (
    ("Subject", "Subject"),
    ("From", "From"),
    ("To", "To"),
    ("Cc", "Cc"),
    ("Date", "Date"),
    ("Message-ID", "Message-ID"),
)

# A file that claims to be an email has to look like one: at least one
# of these headers, before the first blank line. This is the check that
# stops a renamed `.txt` from being accepted at upload and failing in a
# worker twenty seconds later.
REQUIRED_ANY_HEADERS = frozenset(
    {
        "from",
        "to",
        "subject",
        "date",
        "message-id",
        "return-path",
        "received",
        "mime-version",
        "content-type",
        "cc",
        "reply-to",
    }
)


class _HtmlToText(HTMLParser):
    """
    A tolerant HTML-to-text pass, without a parser dependency.

    Email HTML is machine-generated and frequently malformed, so the
    goal is readable prose, not a DOM: block elements become newlines,
    `<script>` and `<style>` are dropped, everything else is kept as
    text. `convert_charrefs` turns `&nbsp;` and friends back into
    characters, which matters for Persian text full of `&zwnj;`.
    """

    BLOCK_TAGS = frozenset(
        {
            "br",
            "p",
            "div",
            "li",
            "tr",
            "td",
            "th",
            "table",
            "blockquote",
            "section",
            "article",
            "header",
            "footer",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
        }
    )

    SKIP_TAGS = frozenset({"script", "style", "head", "title"})

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._parts = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
        elif tag in self.BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in self.BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data):
        if not self._skip_depth:
            self._parts.append(data)

    def text(self):
        return "".join(self._parts)


def _collapse(text):
    """
    Normalise whitespace without destroying paragraph structure.

    HTML-to-text and quoted-printable both produce runs of spaces and
    blank lines. Collapsing to a single blank line keeps the paragraph
    breaks the chunker uses as natural boundaries.
    """

    lines = [line.rstrip() for line in (text or "").replace("\r\n", "\n").split("\n")]
    cleaned = []
    blank = False

    for line in lines:
        if line:
            cleaned.append(line)
            blank = False
        elif not blank:
            cleaned.append("")
            blank = True

    return "\n".join(cleaned).strip()


def _repair_surrogates(value):
    """
    Recover header bytes that were not ASCII.

    `compat32` decodes header bytes as ASCII with `surrogateescape`, so a
    message whose `Subject:` carries raw UTF-8 — which is technically
    invalid and extremely common, because many clients do it — arrives as
    a string of lone surrogates. Encoding back with the same error
    handler restores the original bytes, which then decode normally.

    Nothing is done when there are no surrogates, so a well-formed header
    is untouched.
    """

    if not any("\udc80" <= character <= "\udcff" for character in value):
        return value

    raw = value.encode("utf-8", "surrogateescape")

    for charset in ("utf-8", "cp1256", "latin-1"):
        try:
            return raw.decode(charset)
        except UnicodeDecodeError:
            continue

    return raw.decode("utf-8", errors="replace")


def _decode_header(raw):
    """
    Read a header the way the sender meant it.

    A Persian subject arrives as `=?UTF-8?B?...?=`, and showing that
    verbatim would make the subject unsearchable — which is precisely
    what the acceptance criteria test. An unknown charset keeps the raw
    value rather than dropping it.
    """

    if not raw:
        return ""

    value = _repair_surrogates(str(raw))

    # `policy.default` decodes RFC 2047 already, so the encoded-word
    # pass is only needed for values it left alone.
    if "=?" not in value:
        return value.strip()

    try:
        return str(make_header(decode_header(value))).strip()
    except (UnicodeDecodeError, LookupError, ValueError):
        return value.strip()


def _addresses(raw):
    if not raw:
        return ""

    formatted = []

    for name, address in getaddresses([_repair_surrogates(str(raw))]):
        name = _decode_header(name)

        if name and address:
            formatted.append(f"{name} <{address}>")
        elif address:
            formatted.append(address)
        elif name:
            formatted.append(name)

    return ", ".join(formatted)


def _date(raw):
    if not raw:
        return ""

    try:
        moment = parsedate_to_datetime(str(raw))
    except (TypeError, ValueError, IndexError):
        return str(raw).strip()

    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)

    return moment.isoformat(timespec="minutes")


def _payload(part):
    """
    The decoded bytes of one MIME part, as text.

    `get_payload(decode=True)` undoes base64 and quoted-printable. The
    charset is then applied in order of trust: what the part declares,
    then UTF-8, then the two legacy encodings that actually show up in
    corporate mail, then a lossy decode so a single bad byte does not
    lose the whole message.
    """

    try:
        raw = part.get_payload(decode=True)
    except (ValueError, TypeError):
        return ""

    if not raw:
        return ""

    declared = part.get_content_charset()

    for charset in (declared, "utf-8", "cp1256", "latin-1"):
        if not charset:
            continue

        try:
            return raw.decode(charset)
        except (UnicodeDecodeError, LookupError):
            continue

    return raw.decode("utf-8", errors="replace")


def _attachment_names(message):
    names = []

    for part in message.walk():
        if part.is_multipart():
            continue

        filename = part.get_filename()

        if not filename:
            continue

        names.append(_decode_header(filename))

    return names


def _body_text(message):
    """
    The readable text of a message.

    Plain text wins when both a text and an HTML part exist: it is what
    the sender wrote, and converting HTML that duplicates it would double
    every sentence in the index. HTML is the fallback, not the preference.
    """

    plain = []
    markup = []

    for part in message.walk():
        if part.is_multipart():
            continue

        if (part.get_content_disposition() or "").lower() == "attachment":
            continue

        content_type = part.get_content_type()

        if content_type == "text/plain":
            plain.append(_payload(part))
        elif content_type == "text/html":
            markup.append(_payload(part))

    if plain:
        return _collapse("\n\n".join(plain))

    if markup:
        converter = _HtmlToText()

        for document in markup:
            converter.feed(document)

        converter.close()

        return _collapse(converter.text())

    return ""


def _header_block(message, attachments):
    """
    The metadata, as the first lines of the first passage.

    Written as `Field: value` rather than a sentence so the embedding
    model sees the label next to the value: a query for "who sent the
    invoice" and a query for "Sara Ahmadi" both need `From:` nearby.
    """

    lines = []

    for field, label in HEADER_FIELDS:
        raw = message.get(field)

        if not raw:
            continue

        if field in ("From", "To", "Cc"):
            value = _addresses(raw)
        elif field == "Date":
            value = _date(raw)
        else:
            value = _decode_header(raw)

        if value:
            lines.append(f"{label}: {value}")

    if attachments:
        lines.append(f"Attachments: {', '.join(attachments)}")

    return "\n".join(lines)


def _compact_header(message):
    """
    The one-line header repeated on continuation chunks.

    Without it, the second half of a long email would be findable only
    by its body text, and a search for the subject would return the
    first chunk but not the rest.
    """

    parts = []

    subject = _decode_header(message.get("Subject"))
    sender = _addresses(message.get("From"))
    moment = _date(message.get("Date"))

    if subject:
        parts.append(f"Subject: {subject}")
    if sender:
        parts.append(f"From: {sender}")
    if moment:
        parts.append(f"Date: {moment}")

    return " | ".join(parts)


def looks_like_email(file):
    """
    True when the bytes open with an RFC 822 header block.

    Only the head of the file is read: headers are always at the start,
    and the rest of a message can be megabytes of attachments. The scan
    stops at the first blank line, because everything after it is body.
    """

    file.seek(0)

    try:
        head = file.read(8192)
    except OSError:
        return False
    finally:
        file.seek(0)

    text = head.decode("utf-8", errors="replace")

    for line in text.split("\n"):
        if not line.strip():
            break

        name, separator, _ = line.partition(":")

        if separator and name.strip().lower() in REQUIRED_ANY_HEADERS:
            return True

    return False


def parse_email(file):
    """
    The parsed message, from bytes.

    `policy.default` rather than `compat32`, because it decodes both
    forms a real subject arrives in: an RFC 2047 encoded word
    (`=?UTF-8?B?...?=`) and raw UTF-8 bytes written straight into the
    header, which is invalid and extremely common. Under `compat32` the
    second form comes back as a `Header` object that stringifies to
    question marks — the subject, the thing a user searches for, lost.
    """

    file.seek(0)
    raw = file.read()
    file.seek(0)

    return email.message_from_bytes(raw, policy=email.policy.default)


def extract_email_chunks(file):
    """
    Split an email into passages, metadata attached to each.

    Returns a list of strings. A normal email yields exactly one — the
    header block followed by the body — which is the "single unified
    chunk" this feature is specified around. Only a body too long for one
    embedding window is split further.
    """

    message = parse_email(file)

    body = _body_text(message)

    if not body.strip():
        raise ValueError(
            "This email has no readable text body. It may contain only "
            "attachments or HTML with no text."
        )

    if len(body) > MAX_BODY_CHARACTERS:
        logger.info(
            "Email body truncated from %s to %s characters.",
            len(body),
            MAX_BODY_CHARACTERS,
        )
        body = body[:MAX_BODY_CHARACTERS]

    header = _header_block(message, _attachment_names(message))
    passages = chunk_text(body, chunk_size=CHUNK_SIZE, overlap_percent=CHUNK_OVERLAP)

    if not passages:
        raise ValueError("This email has no readable text body.")

    first = f"{header}\n\n{passages[0]}" if header else passages[0]

    if len(passages) == 1:
        return [first]

    compact = _compact_header(message)

    return [first] + [
        f"{compact}\n\n{passage}" if compact else passage
        for passage in passages[1:]
    ]


def extract_email_text(file):
    """
    The whole email as one string, for the preview drawer.

    The preview shows what was indexed, so it is the same passages joined
    back together — not a second, differently formatted extraction.
    """

    return "\n\n".join(extract_email_chunks(file))
