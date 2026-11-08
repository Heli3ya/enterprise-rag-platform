"""
Ground-truth dataset loading and validation.

The dataset is a JSONL file: one JSON object per line, so it diffs well
in review and can be extended by non-developers without touching code.

Required fields
---------------
``question``      the user question sent to the RAG pipeline
``ground_truth``  the reference answer used by the reference metrics

Optional fields
---------------
``id``                stable identifier (defaults to ``q-<line number>``)
``reference_contexts`` list of verbatim passages that should be retrieved
``document``          source document filename, purely informational
``tags``              list of labels for slicing the report
"""

import json
from dataclasses import dataclass, field
from pathlib import Path


class DatasetError(ValueError):
    """The dataset file is missing, malformed or empty."""


@dataclass(frozen=True)
class EvalSample:
    id: str
    question: str
    ground_truth: str
    reference_contexts: tuple = ()
    document: str = ""
    tags: tuple = ()
    metadata: dict = field(default_factory=dict, compare=False)

    def to_dict(self):
        return {
            "id": self.id,
            "question": self.question,
            "ground_truth": self.ground_truth,
            "reference_contexts": list(self.reference_contexts),
            "document": self.document,
            "tags": list(self.tags),
        }


def _as_text(value, field_name, line_number):
    if not isinstance(value, str) or not value.strip():
        raise DatasetError(
            f"Line {line_number}: '{field_name}' must be a non-empty string."
        )

    return value.strip()


def _as_text_list(value, field_name, line_number):
    if value is None:
        return ()

    if isinstance(value, str):
        return (value.strip(),) if value.strip() else ()

    if not isinstance(value, list):
        raise DatasetError(
            f"Line {line_number}: '{field_name}' must be a list of strings."
        )

    cleaned = []

    for item in value:
        if not isinstance(item, str):
            raise DatasetError(
                f"Line {line_number}: '{field_name}' contains a "
                "non-string value."
            )

        if item.strip():
            cleaned.append(item.strip())

    return tuple(cleaned)


def parse_sample(payload, line_number, index):
    if not isinstance(payload, dict):
        raise DatasetError(
            f"Line {line_number}: each record must be a JSON object."
        )

    question = _as_text(payload.get("question"), "question", line_number)
    ground_truth = _as_text(
        payload.get("ground_truth"),
        "ground_truth",
        line_number,
    )

    sample_id = payload.get("id")

    if not isinstance(sample_id, str) or not sample_id.strip():
        sample_id = f"q-{index:03d}"

    document = payload.get("document")

    if not isinstance(document, str):
        document = ""

    return EvalSample(
        id=sample_id.strip(),
        question=question,
        ground_truth=ground_truth,
        reference_contexts=_as_text_list(
            payload.get("reference_contexts"),
            "reference_contexts",
            line_number,
        ),
        document=document.strip(),
        tags=_as_text_list(payload.get("tags"), "tags", line_number),
    )


def load_dataset(path):
    """Load and validate every sample in a JSONL dataset file."""

    path = Path(path)

    if not path.exists():
        raise DatasetError(f"Dataset file not found: {path}")

    samples = []
    seen_ids = set()

    with path.open("r", encoding="utf-8") as handle:
        line_number = 0

        for raw_line in handle:
            line_number += 1
            stripped = raw_line.strip()

            if not stripped or stripped.startswith("#"):
                continue

            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise DatasetError(
                    f"Line {line_number}: invalid JSON ({exc.msg})."
                ) from exc

            sample = parse_sample(payload, line_number, len(samples) + 1)

            if sample.id in seen_ids:
                raise DatasetError(
                    f"Line {line_number}: duplicate sample id "
                    f"'{sample.id}'."
                )

            seen_ids.add(sample.id)
            samples.append(sample)

    if not samples:
        raise DatasetError(f"Dataset file contains no samples: {path}")

    return samples


def select_samples(samples, *, limit=None, sample_ids=None):
    """Filter by explicit ids and/or cap the number of samples."""

    selected = list(samples)

    if sample_ids:
        wanted = {str(value) for value in sample_ids}
        selected = [
            sample for sample in selected if sample.id in wanted
        ]

        if not selected:
            raise DatasetError(
                "None of the requested sample ids exist in the dataset."
            )

    if limit is not None and limit > 0:
        selected = selected[:limit]

    return selected


def dataset_summary(samples):
    """Small descriptive payload for the dataset info endpoint."""

    documents = sorted(
        {sample.document for sample in samples if sample.document}
    )

    tags = sorted({tag for sample in samples for tag in sample.tags})

    with_reference_contexts = sum(
        1 for sample in samples if sample.reference_contexts
    )

    return {
        "samples": len(samples),
        "documents": documents,
        "document_count": len(documents),
        "tags": tags,
        "with_reference_contexts": with_reference_contexts,
        "ids": [sample.id for sample in samples],
    }
