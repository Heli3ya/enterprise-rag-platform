"""
The prompt has to make two things explicit, because the renderer and the
answer language both depend on them:

1. the answer must be written in the language of the question, and
2. the answer must be plain text, not Markdown.

Neither is a style preference. The renderer is a small Markdown subset
(``frontend/lib/answerFormat.ts``); a model that emits tables and code
fences produces an answer the user reads as broken markup. And a Persian
question answered in English is unreadable for the people this product is
built for, even when every fact is correct.
"""

from api.services import build_rag_prompt


RESULTS = [
    {
        "chunk_id": 93,
        "content": "Employees receive 20 days of annual leave.",
    },
    {
        "chunk_id": 94,
        "content": "Leave requests require the direct manager's approval.",
    },
]

PERSIAN_QUESTION = "مرخصی سالانه چند روز است؟"


def test_prompt_answers_in_the_language_of_the_question():
    prompt = build_rag_prompt("How many leave days?", RESULTS)

    assert "Answer in the language of the user question." in prompt
    assert "A Persian question must get a Persian answer" in prompt
    assert "an English question must get an English answer" in prompt


def test_prompt_asks_for_persian_punctuation_and_verbatim_numbers():
    prompt = build_rag_prompt(PERSIAN_QUESTION, RESULTS)

    assert "، ؛ ؟" in prompt
    # Codes, prices and dates must not be transliterated: the answer has
    # to match the source card. An earlier version asked for Persian
    # digits; a live run turned "60" into "۰۶", so the rule now says to
    # copy the digits instead of converting them.
    assert "copy numbers, codes, IDs, prices, dates and names" in prompt
    assert "Never translate, convert or reorder digits." in prompt


def test_prompt_forbids_markdown_constructs():
    prompt = build_rag_prompt("How many leave days?", RESULTS)

    assert "Do not use Markdown" in prompt
    for construct in ("headings (#)", "bold (**)", "tables", "code blocks"):
        assert construct in prompt


def test_prompt_keeps_every_citation_rule():
    prompt = build_rag_prompt("How many leave days?", RESULTS)

    assert "Use the provided context only." in prompt
    assert "add the chunk ID in square brackets" in prompt
    assert "Do not invent or modify citation IDs." in prompt
    assert "cite all relevant IDs" in prompt
    assert "before the final punctuation" in prompt


def test_prompt_asks_for_latin_digits_in_the_citation_marker():
    # The answer-language rule asks for Persian digits, and a live run
    # showed the model applying it to the marker too (`[۶۶]`). The id is
    # a database integer; the rule keeps it readable for the renderer,
    # and the normalization on both sides is the safety net.
    prompt = build_rag_prompt(PERSIAN_QUESTION, RESULTS)

    assert "Write the citation ID in Latin digits" in prompt
    assert "[66], not [۶۶]" in prompt


def test_persian_question_is_embedded_verbatim_and_once():
    prompt = build_rag_prompt(PERSIAN_QUESTION, RESULTS)

    assert prompt.count(PERSIAN_QUESTION) == 1


def test_braces_and_quotes_in_the_question_do_not_break_the_template():
    question = 'کد {ORBIT-742} و "خط نقل قول" چیست؟'

    prompt = build_rag_prompt(question, RESULTS)

    assert question in prompt
    assert "[93]" in prompt


def test_every_chunk_id_and_its_content_reach_the_prompt():
    prompt = build_rag_prompt(PERSIAN_QUESTION, RESULTS)

    assert "[93]" in prompt
    assert "[94]" in prompt
    assert "Employees receive 20 days of annual leave." in prompt
    assert "Leave requests require the direct manager's approval." in prompt
