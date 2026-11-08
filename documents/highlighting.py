"""
Locate the parts of a chunk that actually matched the user's question.

The citation drawer shows the whole chunk, but the useful part is the
sentence the retrieval picked up. The backend computes the ranges so
the frontend does not have to re-implement tokenization, stopword
filtering, and Persian/Arabic character normalization in TypeScript.

Ranges are `[start, end)` offsets into the *original* chunk text, which
is what makes them safe to use directly on the string the API returns.
"""

import re


WORD_PATTERN = re.compile(r"\w+", re.UNICODE)

# Words that carry no retrieval signal. Kept deliberately small: a
# domain word like "code" or "policy" must never be dropped.
STOPWORDS = {
    # English
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "of", "to", "in", "on", "at", "by", "for", "with", "from", "into",
    "and", "or", "but", "if", "then", "than", "so", "as", "that", "this",
    "these", "those", "there", "their", "it", "its", "i", "you", "we",
    "they", "he", "she", "my", "our", "your", "me", "us", "them",
    "what", "which", "who", "whom", "whose", "how", "when", "where", "why",
    "do", "does", "did", "done", "can", "could", "should", "would", "will",
    "shall", "may", "might", "must", "not", "no", "yes", "please", "tell",
    "about", "has", "have", "had", "any", "all", "some", "more", "most",
    "other", "over", "under", "between", "during", "before", "after",
    "again", "once", "here", "both", "each", "few", "own", "same", "too",
    "very", "just", "now", "also",
    # Persian
    "و", "در", "به", "از", "که", "این", "آن", "را", "با", "برای", "است",
    "هست", "هستند", "بود", "شد", "شده", "می", "نمی", "های", "ها", "یک",
    "دو", "تا", "بر", "هم", "یا", "اگر", "چون", "چه", "چی", "چیه",
    "چیست", "کدام", "کجا", "کی", "چگونه", "چطور", "چند", "آیا", "من",
    "تو", "او", "ما", "شما", "آنها", "خود", "ولی", "اما", "پس", "نیز",
    "خیلی", "همه", "هر", "هیچ", "بین", "روی", "زیر", "وقتی", "مورد",
    "درباره", "طبق", "طور", "لطفا", "بگو", "بگویید", "کنید", "کن", "نه",
    "بله", "دارد", "دارند", "دارم", "داشتن", "بودن",
}

# Arabic forms that Persian text mixes in. Each replacement is 1:1 so
# string offsets stay valid.
CHARACTER_MAP = str.maketrans({
    "\u064a": "\u06cc",  # ي → ی
    "\u0643": "\u06a9",  # ك → ک
    "\u0629": "\u0647",  # ة → ه
})

MAX_TERMS = 12
MAX_RANGES = 60
MIN_TERM_LENGTH = 2

# Characters that glue the parts of one identifier together. Matching
# "ORBIT" and "742" separately should still highlight "ORBIT-742" as a
# single phrase, not two fragments with a gap in the middle.
JOINER_CHARACTERS = frozenset("-/_.:@")


def normalize_for_match(text):
    """
    Lowercase and unify Arabic/Persian letter variants without changing
    the string length, so indices still map to the original text.
    """

    return text.lower().translate(CHARACTER_MAP)


def extract_terms(query, max_terms=MAX_TERMS):
    """
    Turn a question into the terms worth highlighting, in order of
    first appearance and without duplicates.
    """

    if not query:
        return []

    terms = []

    for token in WORD_PATTERN.findall(normalize_for_match(query)):
        if len(token) < MIN_TERM_LENGTH or token in STOPWORDS:
            continue

        if token not in terms:
            terms.append(token)

        if len(terms) >= max_terms:
            break

    return terms


def merge_ranges(ranges, text=None):
    """
    Merge overlapping or adjacent ranges so the frontend can render a
    single `<mark>` per matched phrase instead of nested ones.

    When `text` is given, two ranges separated only by a joiner
    character (`-`, `/`, `_`, `.`, `@`, `:`) are merged too, so a code
    like `ORBIT-742` is highlighted as one phrase.
    """

    if not ranges:
        return []

    ranges = sorted(ranges)
    merged = [list(ranges[0])]

    for start, end in ranges[1:]:
        last_start, last_end = merged[-1]

        if start <= last_end:
            merged[-1][1] = max(last_end, end)
        elif (
            text is not None
            and start == last_end + 1
            and text[last_end] in JOINER_CHARACTERS
        ):
            merged[-1][1] = end
        else:
            merged.append([start, end])

    return merged


def find_highlights(content, query):
    """
    Return `(ranges, matched_terms)` for a chunk and a question.

    `ranges` is a list of `[start, end]` pairs into `content`; `terms`
    lists the query words that were found at least once.
    """

    if not content or not query:
        return [], []

    haystack = normalize_for_match(content)
    ranges = []
    matched_terms = []

    for term in extract_terms(query):
        start = 0
        found = False

        while len(ranges) < MAX_RANGES:
            index = haystack.find(term, start)

            if index == -1:
                break

            ranges.append([index, index + len(term)])
            found = True
            start = index + len(term)

        if found:
            matched_terms.append(term)

        if len(ranges) >= MAX_RANGES:
            break

    return merge_ranges(ranges, content), matched_terms
