
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from api.services import (
    build_rag_prompt,
    extract_citation_ids,
    generate_embeddings,
    generate_query_embedding,
    get_user_department_id,
    normalize_scores,
    rerank_results,
    semantic_search,
)


def test_normalize_scores_returns_empty_dict_for_empty_input():
    assert normalize_scores({}) == {}


def test_normalize_scores_returns_one_for_equal_scores():
    scores = {"first": 0.5, "second": 0.5}

    assert normalize_scores(scores) == {
        "first": 1.0,
        "second": 1.0,
    }


def test_normalize_scores_scales_values_between_zero_and_one():
    scores = {
        "low": 2.0,
        "middle": 4.0,
        "high": 6.0,
    }

    assert normalize_scores(scores) == {
        "low": 0.0,
        "middle": 0.5,
        "high": 1.0,
    }


def test_extract_citation_ids_returns_unique_sorted_ids():
    answer = "First statement [12]. Second statement [4]. Again [12]."

    assert extract_citation_ids(answer) == [4, 12]


def test_extract_citation_ids_returns_empty_list_without_citations():
    assert extract_citation_ids("No citations in this answer.") == []


def test_build_rag_prompt_includes_question_context_and_citation_rules():
    results = [
        {
            "chunk_id": 17,
            "content": "Employees receive annual leave.",
        },
        {
            "chunk_id": 23,
            "content": "Leave requests require approval.",
        },
    ]

    prompt = build_rag_prompt(
        "How does annual leave work?",
        results,
    )

    assert "How does annual leave work?" in prompt
    assert "[17]" in prompt
    assert "[23]" in prompt
    assert "Employees receive annual leave." in prompt
    assert "Leave requests require approval." in prompt
    assert "Do not invent or modify citation IDs." in prompt


def test_get_user_department_id_returns_none_for_missing_user():
    assert get_user_department_id(None) is None


def test_get_user_department_id_returns_none_for_anonymous_user():
    user = SimpleNamespace(
        is_authenticated=False,
        department_id=7,
    )

    assert get_user_department_id(user) is None


def test_get_user_department_id_returns_department_for_authenticated_user():
    user = SimpleNamespace(
        is_authenticated=True,
        department_id=7,
    )

    assert get_user_department_id(user) == 7


def test_semantic_search_returns_empty_without_user():
    with patch("api.services.requests.post") as post:
        assert semantic_search("annual leave") == []

    post.assert_not_called()


def test_semantic_search_returns_empty_without_department():
    user = SimpleNamespace(department_id=None)

    with patch("api.services.requests.post") as post:
        assert semantic_search("annual leave", user=user) == []

    post.assert_not_called()


def test_semantic_search_maps_ai_results():
    user = SimpleNamespace(department_id=7)

    response = Mock()
    response.json.return_value = {
        "results": [
            {
                "document_id": 10,
                "document_title": "HR Policy",
                "department_id": 7,
                "chunk_id": 25,
                "content": "Annual leave policy.",
                "chunk_index": 2,
                "distance": 0.15,
            }
        ]
    }

    with patch(
        "api.services.requests.post",
        return_value=response,
    ) as post:
        results = semantic_search(
            "annual leave",
            limit=6,
            user=user,
        )

    response.raise_for_status.assert_called_once()
    post.assert_called_once()

    request_data = post.call_args.kwargs["json"]
    assert request_data["query"] == "annual leave"
    assert request_data["limit"] == 6
    assert request_data["allowed_department_ids"] == [7]

    assert len(results) == 1
    assert results[0].chunk_id == 25
    assert results[0].distance == 0.15
    assert results[0].chunk.content == "Annual leave policy."
    assert results[0].chunk.document.title == "HR Policy"
    assert results[0].chunk.document.department_id == 7


def test_generate_embeddings_returns_vectors_and_dimension():
    response = Mock()
    response.json.return_value = {
        "embeddings": [[0.1, 0.2, 0.3]],
        "dimension": 3,
    }

    with patch(
        "api.services.requests.post",
        return_value=response,
    ) as post:
        vectors, dimension = generate_embeddings(["test text"])

    response.raise_for_status.assert_called_once()
    assert vectors == [[0.1, 0.2, 0.3]]
    assert dimension == 3
    assert post.call_args.kwargs["json"] == {
        "texts": ["test text"],
    }


def test_generate_query_embedding_returns_single_vector():
    response = Mock()
    response.json.return_value = {
        "embeddings": [[0.1] * 384],
        "dimension": 384,
    }

    with patch(
        "api.services.requests.post",
        return_value=response,
    ):
        vector = generate_query_embedding("annual leave")

    assert len(vector) == 384
    assert vector[0] == 0.1


def test_generate_query_embedding_rejects_multiple_vectors():
    response = Mock()
    response.json.return_value = {
        "embeddings": [[0.1] * 384, [0.2] * 384],
        "dimension": 384,
    }

    with patch(
        "api.services.requests.post",
        return_value=response,
    ):
        with pytest.raises(
            ValueError,
            match="exactly one vector",
        ):
            generate_query_embedding("annual leave")


def test_generate_query_embedding_rejects_wrong_dimension():
    response = Mock()
    response.json.return_value = {
        "embeddings": [[0.1] * 3],
        "dimension": 3,
    }

    with patch(
        "api.services.requests.post",
        return_value=response,
    ):
        with pytest.raises(
            ValueError,
            match="dimension must be 384",
        ):
            generate_query_embedding("annual leave")


def test_rerank_results_returns_empty_for_empty_input():
    assert rerank_results("annual leave", []) == []


def test_rerank_results_sorts_by_score_and_handles_missing_scores():
    results = [
        {"chunk_id": 1, "content": "First result"},
        {"chunk_id": 2, "content": "Second result"},
        {"chunk_id": 3, "content": "Third result"},
    ]

    response = Mock()
    response.json.return_value = {
        "results": [
            {"content": "First result", "score": 0.2},
            {"content": "Second result", "score": 0.9},
        ]
    }

    with patch(
        "api.services.requests.post",
        return_value=response,
    ):
        reranked = rerank_results("annual leave", results)

    assert [item["chunk_id"] for item in reranked] == [2, 1, 3]
    assert reranked[0]["rerank_score"] == 0.9
    assert reranked[1]["rerank_score"] == 0.2
    assert reranked[2]["rerank_score"] == float("-inf")

def test_generate_rag_answer_returns_message_when_no_results():
    with patch("api.services.hybrid_search", return_value=[]):
        result = __import__(
            "api.services",
            fromlist=["generate_rag_answer"],
        ).generate_rag_answer("annual leave")

    assert result == {
        "answer": "No relevant documents were found.",
        "citations": [],
    }


def test_generate_rag_answer_returns_answer_and_citations():
    from api.services import generate_rag_answer

    search_results = [
        {"chunk_id": 12, "content": "Employees receive annual leave."}
    ]
    citation_data = [
        {
            "document_id": 5,
            "filename": "leave-policy.txt",
            "department": "HR",
            "chunk_id": 12,
        }
    ]

    response = Mock()
    response.json.return_value = {
        "response": "Employees receive annual leave. [12]"
    }

    with (
        patch("api.services.hybrid_search", return_value=search_results),
        patch("api.services.requests.post", return_value=response),
        patch("api.services.build_citations", return_value=citation_data),
    ):
        result = generate_rag_answer("annual leave")

    assert result["answer"] == "Employees receive annual leave. [12]"
    assert result["citations"] == citation_data
    response.raise_for_status.assert_called_once()


def test_generate_rag_answer_raises_error_when_response_is_missing():
    from api.services import generate_rag_answer

    response = Mock()
    response.json.return_value = {"response": ""}

    with (
        patch(
            "api.services.hybrid_search",
            return_value=[{"chunk_id": 12, "content": "Annual leave"}],
        ),
        patch("api.services.requests.post", return_value=response),
        pytest.raises(RuntimeError, match="LLM response text is missing"),
    ):
        generate_rag_answer("annual leave")


def test_generate_rag_stream_returns_error_when_no_results():
    from api.services import generate_rag_stream

    with patch("api.services.hybrid_search", return_value=[]):
        events = list(generate_rag_stream("annual leave"))

    assert events == [
        {
            "type": "error",
            "message": "No relevant documents were found.",
        }
    ]


def test_generate_rag_stream_emits_tokens_citations_and_done():
    from api.services import generate_rag_stream

    response = Mock()
    response.iter_content.return_value = [
        "Annual leave ",
        "requires approval. [12]",
    ]

    citations = [
        {
            "document_id": 5,
            "filename": "leave-policy.txt",
            "department": "HR",
            "chunk_id": 12,
        }
    ]

    with (
        patch(
            "api.services.hybrid_search",
            return_value=[{"chunk_id": 12, "content": "Annual leave requires approval."}],
        ),
        patch("api.services.requests.post", return_value=response),
        patch("api.services.build_citations", return_value=citations),
    ):
        events = list(generate_rag_stream("annual leave"))

    assert events[0] == {
        "type": "token",
        "content": "Annual leave ",
    }
    assert events[1] == {
        "type": "token",
        "content": "requires approval. [12]",
    }
    assert events[2] == {
        "type": "citations",
        "citations": citations,
    }
    assert events[3] == {"type": "done"}
    response.raise_for_status.assert_called_once()


def test_hybrid_search_returns_empty_when_no_results():
    from api.services import hybrid_search

    user = SimpleNamespace(department_id=7)

    with (
        patch("api.services.semantic_search", return_value=[]) as semantic,
        patch("api.services.keyword_search", return_value=[]) as keyword,
        patch("api.services.rerank_results", return_value=[]) as rerank,
    ):
        result = hybrid_search("annual leave", limit=2, user=user)

    assert result == []
    semantic.assert_called_once_with("annual leave", limit=6, user=user)
    keyword.assert_called_once_with("annual leave", limit=6, user=user)
    rerank.assert_called_once_with("annual leave", [])


def test_hybrid_search_combines_results_and_applies_query_bonus():
    from api.services import hybrid_search

    user = SimpleNamespace(department_id=7)

    semantic_result = SimpleNamespace(
        chunk_id=10,
        distance=0.2,
        chunk=SimpleNamespace(content="Annual leave policy"),
    )
    keyword_result = SimpleNamespace(
        id=20,
        rank=0.8,
        content="Remote work policy",
    )

    def fake_rerank(query, results):
        return [
            {**item, "rerank_score": item["score"]}
            for item in results
        ]

    with (
        patch(
            "api.services.semantic_search",
            return_value=[semantic_result],
        ),
        patch(
            "api.services.keyword_search",
            return_value=[keyword_result],
        ),
        patch(
            "api.services.rerank_results",
            side_effect=fake_rerank,
        ) as rerank,
    ):
        result = hybrid_search("annual leave", limit=5, user=user)

    assert len(result) == 2
    assert result[0]["chunk_id"] == 10
    assert result[0]["content"] == "Annual leave policy"
    assert result[0]["score"] > result[1]["score"]
    assert {item["chunk_id"] for item in result} == {10, 20}
    rerank.assert_called_once()
    assert rerank.call_args.args[0] == "annual leave"
    assert len(rerank.call_args.args[1]) == 2


def test_hybrid_search_respects_result_limit():
    from api.services import hybrid_search

    user = SimpleNamespace(department_id=7)
    semantic_results = [
        SimpleNamespace(
            chunk_id=index,
            distance=0.1 * index,
            chunk=SimpleNamespace(content=f"Policy {index}"),
        )
        for index in range(1, 5)
    ]

    with (
        patch(
            "api.services.semantic_search",
            return_value=semantic_results,
        ),
        patch("api.services.keyword_search", return_value=[]),
        patch(
            "api.services.rerank_results",
            side_effect=lambda query, results: results,
        ),
    ):
        result = hybrid_search("policy", limit=2, user=user)

    assert len(result) == 2
