import pytest
from unittest.mock import patch, MagicMock
from app.services.rag import (
    get_embeddings,
    get_vector_store,
    index_document,
    retrieve_context,
)
import app.services.rag as rag_module


@pytest.fixture(autouse=True)
def reset_globals():
    # Reset globals before each test
    rag_module._embeddings = None
    rag_module._vector_store = None
    yield


@patch("app.services.rag.HuggingFaceEmbeddings")
def test_get_embeddings(mock_hfe):
    mock_hf_instance = MagicMock()
    mock_hfe.return_value = mock_hf_instance

    emb1 = get_embeddings()
    emb2 = get_embeddings()

    assert emb1 is emb2
    assert emb1 is mock_hf_instance
    mock_hfe.assert_called_once()


@patch("app.services.rag.chromadb.PersistentClient")
@patch("app.services.rag.Chroma")
@patch("app.services.rag.get_embeddings")
def test_get_vector_store(mock_get_emb, mock_chroma, mock_client):
    mock_vs_instance = MagicMock()
    mock_chroma.return_value = mock_vs_instance

    vs1 = get_vector_store()
    vs2 = get_vector_store()

    assert vs1 is vs2
    assert vs1 is mock_vs_instance
    mock_chroma.assert_called_once()
    mock_client.assert_called_once()


@patch("app.services.rag.get_vector_store")
def test_index_document(mock_get_vs):
    mock_vs = MagicMock()
    mock_get_vs.return_value = mock_vs

    # Empty text
    assert index_document("   ", "test.txt", "thread-1") == 0
    mock_vs.add_documents.assert_not_called()

    # Valid text
    text = "This is a test document. It has some text. " * 50
    chunks_count = index_document(text, "test.txt", "thread-1")
    assert chunks_count > 0
    mock_vs.add_documents.assert_called_once()


@patch("app.services.rag.get_vector_store")
def test_retrieve_context(mock_get_vs):
    mock_vs = MagicMock()
    mock_get_vs.return_value = mock_vs

    # Empty query or thread
    assert retrieve_context("", "thread-1") == []
    assert retrieve_context("query", "") == []

    # Valid query
    mock_doc = MagicMock()
    mock_vs.similarity_search_with_score.return_value = [(mock_doc, 0.8)]

    docs = retrieve_context("test query", "thread-1", k=2)
    assert len(docs) == 1
    assert docs[0] is mock_doc
    mock_vs.similarity_search_with_score.assert_called_once_with(
        "test query", k=2, filter={"thread_id": "thread-1"}
    )

    # Exception handling
    mock_vs.similarity_search_with_score.side_effect = Exception("DB error")
    docs = retrieve_context("test query", "thread-1")
    assert docs == []
