import os
from typing import List

import chromadb
from chromadb.config import Settings
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

# Persistence directory for ChromaDB (points to backend/chroma_db)
DB_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "chroma_db",
)

# Use a fast, local, lightweight embedding model
EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
_embeddings = None


def get_embeddings():
    global _embeddings
    if _embeddings is None:
        _embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL_NAME)
    return _embeddings


_vector_store = None


def get_vector_store() -> Chroma:
    global _vector_store

    if _vector_store is None:
        client = chromadb.PersistentClient(
            path=DB_DIR, settings=Settings(anonymized_telemetry=False)
        )
        _vector_store = Chroma(
            client=client,
            collection_name="crucible_documents",
            embedding_function=get_embeddings(),
        )
    return _vector_store


def index_document(text: str, filename: str, thread_id: str) -> int:
    """
    Split a document into semantic chunks and index it in ChromaDB.
    Associates the chunks with a specific thread_id.
    """
    if not text.strip():
        return 0

    # Configure an aggressive splitter suitable for dense academic/research text
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
        length_function=len,
        separators=["\n\n", "\n", ".", r"(?<=\. )", " ", ""],
    )

    chunks = splitter.create_documents(
        [text], metadatas=[{"filename": filename, "thread_id": thread_id}]
    )

    if not chunks:
        return 0

    vs = get_vector_store()
    vs.add_documents(chunks)
    print(f"[RAG] Indexed {len(chunks)} chunks for {filename} (Thread: {thread_id})")

    return len(chunks)


def retrieve_context(query: str, thread_id: str, k: int = 5) -> List[Document]:
    """
    Retrieve the most relevant context chunks for a given query,
    filtered to the specific thread.
    """
    if not query.strip() or not thread_id:
        return []

    vs = get_vector_store()

    # Filter strictly by thread_id so models don't cross-contaminate conversations
    filter_dict = {"thread_id": thread_id}

    try:
        # returns [(Document, score), ...] - score is L2 distance for default Chroma
        docs_and_scores = vs.similarity_search_with_score(
            query, k=k, filter=filter_dict
        )
        print(
            f"[RAG] Retrieved {len(docs_and_scores)} relevant chunks for query: '{query[:30]}...'"
        )

        # Unpack just the Document objects
        return [doc for doc, score in docs_and_scores]
    except Exception as e:
        print(f"[RAG] Retrieval error: {e}")
        return []
