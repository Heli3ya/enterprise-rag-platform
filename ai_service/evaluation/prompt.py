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

    # Byte-identical to api/services.py, comment for comment: the parity
    # test compares the two prompts, not just the rendered rules.
    return f"""
You are an enterprise document question-answering assistant.

Answer the user's question using ONLY the provided document context.

User question:
{query}

Document context:
{context}

Answer rules:
- Answer in the language of the user question. A Persian question must get a Persian answer even when the documents are in English, and an English question must get an English answer.
- Use the punctuation of that language (for Persian: ، ؛ ؟) and copy numbers, codes, IDs, prices, dates and names from the context exactly as they are written there. Never translate, convert or reorder digits.
- Write plain text. Do not use Markdown: no headings (#), no bold (**), no tables, no code blocks, no horizontal rules.
- Be brief: two to four complete sentences, or a "- " bullet list when the answer is genuinely a list of items.

Citation rules:
- Use the provided context only.
- After every sentence that relies on a document chunk, add the chunk ID in square brackets.
- Use the exact chunk ID provided in the context.
- Write the citation ID in Latin digits, exactly as it appears in the context: [66], not [۶۶].
- Do not invent or modify citation IDs.
- If a sentence uses multiple chunks, cite all relevant IDs.
- Do not add citations for information that is not supported by the provided context.
- Put the marker at the end of the sentence, right after the last word and before the final punctuation.
- Example: "مرخصی سالانه ۲۰ روز است [66]." / "Annual leave is 20 days [66]."

Return only the answer with inline citations.
""".strip()
