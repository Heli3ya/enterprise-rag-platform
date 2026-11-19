"""
The evaluation must send the model exactly the prompt the chat endpoint
sends, otherwise the scores describe a different system.

``api/services.py`` and ``ai_service/evaluation/prompt.py`` each own a
copy of the template because they run in separate containers. This test
is the guard against the two copies drifting apart.
"""

from api.services import build_rag_prompt as production_prompt
from ai_service.evaluation.prompt import build_rag_prompt as evaluation_prompt


RESULTS = [
    {"chunk_id": 93, "content": "The unique project verification code is ORBIT-742."},
    {"chunk_id": 94, "content": "The support team is the Atlas team."},
]


def test_evaluation_prompt_is_byte_identical_to_production():
    query = "What is the verification code?"

    assert evaluation_prompt(query, RESULTS) == production_prompt(query, RESULTS)


def test_evaluation_prompt_is_identical_for_a_persian_question():
    # The answer-language and formatting rules are the newest part of the
    # template, and the easiest to forget in the second copy: a Persian
    # question is the case where the two prompts would diverge visibly.
    query = "مرخصی سالانه چند روز است؟"

    assert evaluation_prompt(query, RESULTS) == production_prompt(query, RESULTS)


def test_prompt_embeds_every_chunk_id_and_the_question():
    prompt = evaluation_prompt("Who supports this document?", RESULTS)

    assert "[93]" in prompt
    assert "[94]" in prompt
    assert "Who supports this document?" in prompt
    assert "ORBIT-742" in prompt
