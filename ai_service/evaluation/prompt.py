"""
The production RAG prompt.

This template is intentionally identical to ``api/services.py``
(``build_rag_prompt``). The evaluation is only meaningful if the model
sees exactly the prompt the chat endpoint sends, so a Django test
(``tests/test_eval_prompt_parity.py``) asserts byte equality between the
two implementations. Change both or neither.
"""


import os


# Mirrors api/services.py: the evaluation must see the same context budget
# the chat endpoint uses, otherwise the scores describe a different prompt.
RAG_CONTEXT_CHARS = int(os.getenv("RAG_CONTEXT_CHARS", "700"))


def _prompt_excerpt(content):
    """Trim a chunk to the prompt budget, marking the cut."""

    text = (content or "").strip()

    if len(text) <= RAG_CONTEXT_CHARS:
        return text

    return text[:RAG_CONTEXT_CHARS].rstrip() + " …"


def build_rag_prompt(query, results):
    context_parts = []

    for result in results:
        context_parts.append(
            f"[{result['chunk_id']}]\n"
            f"{_prompt_excerpt(result['content'])}"
        )

    context = "\n\n".join(context_parts)

    return f"""
You are an enterprise document question-answering assistant.

Answer the user's question using ONLY the provided document context.

User question:
{query}

Document context:
{context}

Citation rules:
- Use the provided context only.
- After every sentence that relies on a document chunk, add the chunk ID in square brackets.
- Use the exact chunk ID provided in the context.
- Do not invent or modify citation IDs.
- If a sentence uses multiple chunks, cite all relevant IDs.
- Do not add citations for information that is not supported by the provided context.

Return only the answer with inline citations.
""".strip()
