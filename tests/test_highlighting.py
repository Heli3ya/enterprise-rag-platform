import pytest

from documents.highlighting import (
    extract_terms,
    find_highlights,
    merge_ranges,
    normalize_for_match,
)


def slices(content, ranges):
    return [content[start:end] for start, end in ranges]


def test_extract_terms_drops_stopwords_and_keeps_domain_words():
    terms = extract_terms("What is the code for ORBIT-742?")

    assert terms == ["code", "orbit", "742"]


def test_extract_terms_ignores_single_character_tokens():
    assert extract_terms("a b code c") == ["code"]


def test_extract_terms_returns_unique_terms_in_order():
    assert extract_terms("policy and policy") == ["policy"]


def test_extract_terms_handles_persian_stopwords():
    terms = extract_terms("کد پروژه چیست؟")

    assert terms == ["کد", "پروژه"]


def test_normalize_for_match_keeps_the_string_length():
    text = "كتاب"

    assert len(normalize_for_match(text)) == len(text)


def test_find_highlights_returns_offsets_into_the_original_text():
    content = "The launch code for project ORBIT is ORBIT-742."

    ranges, terms = find_highlights(content, "launch code")

    assert terms == ["launch", "code"]
    assert slices(content, ranges) == ["launch", "code"]


def test_find_highlights_is_case_insensitive():
    content = "The ORBIT code is secret."

    ranges, _ = find_highlights(content, "orbit")

    assert slices(content, ranges) == ["ORBIT"]


def test_find_highlights_joins_parts_of_one_identifier():
    content = "Use ORBIT-742 as the code."

    ranges, terms = find_highlights(content, "ORBIT-742")

    assert terms == ["orbit", "742"]
    assert slices(content, ranges) == ["ORBIT-742"]


def test_find_highlights_matches_arabic_letter_variants():
    content = "کد پروژه در سند است."

    ranges, terms = find_highlights(content, "كد")

    assert terms == ["کد"]
    assert slices(content, ranges) == ["کد"]


def test_find_highlights_without_query_returns_nothing():
    assert find_highlights("some text", "") == ([], [])


def test_find_highlights_without_content_returns_nothing():
    assert find_highlights("", "orbit") == ([], [])


def test_find_highlights_reports_no_terms_for_unmatched_query():
    ranges, terms = find_highlights("completely unrelated", "orbit")

    assert ranges == []
    assert terms == []


def test_merge_ranges_combines_overlaps():
    assert merge_ranges([[0, 5], [3, 8], [10, 12]]) == [[0, 8], [10, 12]]


def test_merge_ranges_joins_identifier_parts_only():
    text = "ORBIT-742"

    assert merge_ranges([[0, 5], [6, 9]], text) == [[0, 9]]
    # A space is not a joiner: "code for" stays two highlights.
    assert merge_ranges([[0, 4], [5, 8]], "code for") == [[0, 4], [5, 8]]


@pytest.mark.parametrize(
    "query",
    ["", "   ", "؟؟؟", "the of and"],
)
def test_queries_without_usable_terms_highlight_nothing(query):
    ranges, terms = find_highlights("The policy is documented.", query)

    assert ranges == []
    assert terms == []
