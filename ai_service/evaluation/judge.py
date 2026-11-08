"""
LLM-as-judge helpers.

Every metric that needs reasoning is expressed as a single, short prompt
that must return JSON. Small local models are unreliable at strict JSON,
so this module owns all the defensive parsing: it extracts the first
balanced JSON value, repairs the common mistakes (trailing commas,
single quotes, Python booleans) and coerces loose answers such as
``["yes", "no"]`` or ``[1, 0]`` into booleans.

If the judge cannot produce a usable answer after the configured
retries, :class:`JudgeError` is raised and the caller falls back to the
deterministic lexical implementation. The report records which method
produced each score, so a degraded run is never mistaken for a good one.
"""

import json
import re


class JudgeError(RuntimeError):
    """The language model did not return usable JSON."""


_TRUTHY = {"true", "yes", "y", "1", "supported", "relevant", "useful"}
_FALSY = {"false", "no", "n", "0", "unsupported", "irrelevant", "not useful"}

_FENCE_PATTERN = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _strip_code_fences(text):
    match = _FENCE_PATTERN.search(text)

    if match:
        return match.group(1).strip()

    return text.strip()


def _repair_json(text):
    """Apply the small fixes that local models commonly need."""

    repaired = text.strip()

    # Trailing commas before a closing bracket or brace.
    repaired = re.sub(r",(\s*[\]}])", r"\1", repaired)

    # Python/JavaScript literals that json.loads rejects.
    repaired = re.sub(r"\bTrue\b", "true", repaired)
    repaired = re.sub(r"\bFalse\b", "false", repaired)
    repaired = re.sub(r"\bNone\b", "null", repaired)
    repaired = re.sub(r"\bNaN\b", "null", repaired)

    # Single-quoted strings (only when there is no double quote at all,
    # otherwise legitimate apostrophes would be mangled).
    if '"' not in repaired and "'" in repaired:
        repaired = repaired.replace("'", '"')

    return repaired


def _balanced_slice(text, open_char, close_char):
    """Return the first balanced ``open_char ... close_char`` block."""

    start = text.find(open_char)

    if start == -1:
        return None

    depth = 0
    in_string = False
    escape = False

    for index in range(start, len(text)):
        char = text[index]

        if escape:
            escape = False
            continue

        if char == "\\":
            escape = True
            continue

        if char == '"':
            in_string = not in_string
            continue

        if in_string:
            continue

        if char == open_char:
            depth += 1
        elif char == close_char:
            depth -= 1

            if depth == 0:
                return text[start:index + 1]

    return None


def extract_json(text, expect):
    """Best-effort extraction of a JSON value from a model response."""

    if not isinstance(text, str) or not text.strip():
        raise JudgeError("The model returned an empty response.")

    candidates = []

    stripped = _strip_code_fences(text)
    candidates.append(stripped)

    if expect == "array":
        block = _balanced_slice(stripped, "[", "]")
    else:
        block = _balanced_slice(stripped, "{", "}")

    if block:
        candidates.append(block)

    for candidate in candidates:
        for variant in (candidate, _repair_json(candidate)):
            try:
                value = json.loads(variant)
            except (json.JSONDecodeError, TypeError):
                continue

            if expect == "array" and not isinstance(value, list):
                continue

            if expect == "object" and not isinstance(value, dict):
                continue

            return value

    raise JudgeError(
        "The model did not return valid JSON. "
        f"First 200 characters: {stripped[:200]!r}"
    )


def coerce_bool(value):
    """Turn a loose model answer into a boolean, or ``None``."""

    if isinstance(value, bool):
        return value

    if isinstance(value, (int, float)):
        return bool(value)

    if isinstance(value, str):
        normalized = value.strip().strip(".").lower()

        if normalized in _TRUTHY:
            return True

        if normalized in _FALSY:
            return False

    return None


def coerce_bool_list(value, expected_length):
    """
    Coerce a model answer into exactly ``expected_length`` booleans.

    Anything that cannot be interpreted is dropped; the caller decides
    whether a partial answer is good enough.
    """

    if isinstance(value, dict):
        # Accept {"1": true, "2": false} as well as a nested list.
        for key in ("results", "verdicts", "answers", "supported"):
            if key in value:
                return coerce_bool_list(value[key], expected_length)

        ordered = []

        for index in range(1, expected_length + 1):
            for key in (str(index), index, f"s{index}", f"statement_{index}"):
                if key in value:
                    coerced = coerce_bool(value[key])

                    if coerced is not None:
                        ordered.append(coerced)
                        break

        return ordered

    if not isinstance(value, list):
        coerced = coerce_bool(value)
        return [coerced] if coerced is not None else []

    results = []

    for item in value:
        coerced = coerce_bool(item)

        if coerced is not None:
            results.append(coerced)

    return results


def coerce_str_list(value, *, limit=None):
    """Coerce a model answer into a list of non-empty strings."""

    if isinstance(value, dict):
        for key in ("statements", "questions", "items", "results"):
            if key in value:
                return coerce_str_list(value[key], limit=limit)

        return []

    if isinstance(value, str):
        value = [value]

    if not isinstance(value, list):
        return []

    cleaned = []

    for item in value:
        if isinstance(item, str) and item.strip():
            cleaned.append(item.strip())
        elif isinstance(item, dict):
            for key in ("statement", "question", "text"):
                if isinstance(item.get(key), str) and item[key].strip():
                    cleaned.append(item[key].strip())
                    break

    if limit is not None:
        cleaned = cleaned[:limit]

    return cleaned


def build_context_block(contexts, max_chars=1200):
    """Render retrieved chunks as a numbered block for the judge."""

    parts = []

    for index, context in enumerate(contexts, start=1):
        text = (context or "").strip()

        if not text:
            continue

        parts.append(f"[{index}] {text[:max_chars]}")

    return "\n\n".join(parts)


class LLMJudge:
    """Thin, testable wrapper around the inference service's LLM client."""

    def __init__(
        self,
        client,
        *,
        timeout=180,
        retries=1,
        question_count=3,
        max_statements=8,
    ):
        self.client = client
        self.timeout = timeout
        self.retries = max(0, retries)
        self.question_count = max(1, question_count)
        self.max_statements = max(1, max_statements)

    def complete(self, prompt):
        attempts = self.retries + 1
        last_error = None

        for attempt in range(1, attempts + 1):
            try:
                text = self.client.generate_with_options(
                    prompt,
                    temperature=0.0,
                    max_tokens=512,
                    timeout=self.timeout,
                    seed=7,
                )
            except Exception as exc:  # pragma: no cover - network paths
                last_error = exc

                if attempt < attempts:
                    continue

                raise JudgeError(f"LLM call failed: {exc}") from exc

            if isinstance(text, str) and text.strip():
                return text

            last_error = JudgeError("The model returned an empty response.")

        raise JudgeError(str(last_error or "The model returned no answer."))

    def complete_json(self, prompt, expect="array"):
        attempts = self.retries + 1
        last_error = None

        for attempt in range(1, attempts + 1):
            text = self.complete(prompt)

            try:
                return extract_json(text, expect)
            except JudgeError as exc:
                last_error = exc

                if attempt < attempts:
                    prompt = (
                        prompt
                        + "\n\nYour previous answer was not valid JSON. "
                        "Return ONLY the JSON value, with no prose and no "
                        "code fences."
                    )

        raise JudgeError(str(last_error))

    # -- faithfulness ---------------------------------------------------

    def decompose_statements(self, answer):
        """Split an answer into atomic factual statements."""

        prompt = f"""Break the ANSWER into short, self-contained factual statements.

Rules:
- One claim per statement. Never split a single claim into several statements.
- If the ANSWER is one sentence, return exactly one statement.
- Do not add explanations, implications or restatements of the same fact.
- Keep names, numbers and units exactly as written.
- Ignore greetings, filler and citation markers such as [12].
- Maximum {self.max_statements} statements.
- Return ONLY a JSON array of strings.

ANSWER:
\"\"\"
{answer[:4000]}
\"\"\""""

        payload = self.complete_json(prompt, expect="array")

        return coerce_str_list(payload, limit=self.max_statements)

    def verify_statements(self, statements, contexts):
        """Return one verdict per statement (True = supported)."""

        if not statements:
            return []

        numbered = "\n".join(
            f"{index}. {statement}"
            for index, statement in enumerate(statements, start=1)
        )

        context_block = build_context_block(contexts)

        prompt = f"""You are a strict fact checker.

For each STATEMENT decide whether it is directly supported by the CONTEXT.
Use ONLY the context. Do not use outside knowledge.
If a statement adds information that is not in the context, it is NOT supported.

Return ONLY a JSON array of {len(statements)} booleans, in the same order
as the statements.

CONTEXT:
\"\"\"
{context_block}
\"\"\"

STATEMENTS:
{numbered}"""

        payload = self.complete_json(prompt, expect="array")
        verdicts = coerce_bool_list(payload, len(statements))

        if len(verdicts) != len(statements):
            raise JudgeError(
                "The judge returned "
                f"{len(verdicts)} verdicts for {len(statements)} statements."
            )

        return verdicts

    # -- answer relevancy -----------------------------------------------

    def generate_questions(self, answer, count=None):
        """Reverse-engineer the questions an answer responds to."""

        count = count or self.question_count

        prompt = f"""Write {count} short questions that the ANSWER below directly answers.

Rules:
- Each question must be answerable from the answer alone.
- Do not reuse the wording of the answer as a question.
- Return ONLY a JSON array of {count} strings.

ANSWER:
\"\"\"
{answer[:3000]}
\"\"\""""

        payload = self.complete_json(prompt, expect="array")

        return coerce_str_list(payload, limit=count)

    # -- context precision ----------------------------------------------

    def judge_context_relevance(self, question, ground_truth, contexts):
        """Return one verdict per retrieved chunk (True = useful)."""

        if not contexts:
            return []

        context_block = build_context_block(contexts)

        prompt = f"""You are grading a document retrieval system.

QUESTION:
{question}

REFERENCE ANSWER:
{ground_truth}

For each CONTEXT passage decide whether it is useful for producing the
REFERENCE ANSWER. A passage is useful only if it contains information that
the reference answer actually uses.

Return ONLY a JSON array of {len(contexts)} booleans, in the same order
as the passages.

CONTEXTS:
\"\"\"
{context_block}
\"\"\""""

        payload = self.complete_json(prompt, expect="array")
        verdicts = coerce_bool_list(payload, len(contexts))

        if len(verdicts) != len(contexts):
            raise JudgeError(
                "The judge returned "
                f"{len(verdicts)} verdicts for {len(contexts)} contexts."
            )

        return verdicts
