import logging
import threading
from typing import List

import chromadb
from chromadb.config import Settings
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from app.core.storage import current_storage

log = logging.getLogger(__name__)


# Use a fast, local, lightweight embedding model
EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
COLLECTION_NAME = "crucible_documents"
_embeddings = None
_clients: dict = {}
_vector_stores: dict = {}
# Graph nodes are sync and run on executor threads, so parallel models reach
# these lazy singletons at the same moment. Two concurrent PersistentClient
# inits fail with "Could not connect to tenant default_tenant".
_init_lock = threading.RLock()


class SerializedEmbeddings(Embeddings):
    """Runs one embedding call at a time on the wrapped model.

    Parallel models in one turn (RAG retrieval, debate stability) embed on
    executor threads at the same moment, and concurrent inference on one
    sentence-transformers model is not thread-safe: with torch 2.14 and
    sentence-transformers 6 two simultaneous embed_query calls segfault the
    whole server. A call takes milliseconds, so queueing costs nothing.
    """

    def __init__(self, inner: Embeddings):
        self.inner = inner
        self._lock = threading.Lock()

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        with self._lock:
            return self.inner.embed_documents(texts)

    def embed_query(self, text: str) -> List[float]:
        with self._lock:
            return self.inner.embed_query(text)


def get_embeddings() -> Embeddings:
    global _embeddings
    if _embeddings is None:
        with _init_lock:
            if _embeddings is None:
                _embeddings = SerializedEmbeddings(HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL_NAME))
    return _embeddings


def _get_client():
    """The persistent Chroma client for the run's Chroma directory
    (core/storage.py), shared by the vector store and deletes; one per
    directory, created once."""
    path = current_storage().chroma_dir
    if path not in _clients:
        with _init_lock:
            if path not in _clients:
                _clients[path] = chromadb.PersistentClient(path=path, settings=Settings(anonymized_telemetry=False))
    return _clients[path]


def get_vector_store() -> Chroma:
    path = current_storage().chroma_dir
    if path not in _vector_stores:
        with _init_lock:
            if path not in _vector_stores:
                _vector_stores[path] = Chroma(
                    client=_get_client(),
                    collection_name=COLLECTION_NAME,
                    embedding_function=get_embeddings(),
                )
    return _vector_stores[path]


def get_chunk_collection():
    """The raw Chroma collection holding every thread's chunks. Deleting by
    metadata needs no embeddings, so this does not load the embedding model
    the way get_vector_store() does."""
    # embedding_function=None as langchain_chroma creates it: it embeds itself.
    return _get_client().get_or_create_collection(name=COLLECTION_NAME, embedding_function=None)


def delete_thread_chunks(thread_id: str, collection=None) -> None:
    """Remove every indexed chunk of one thread.

    Chunks are tagged with the thread_id the upload named (the parent thread;
    debate sub-threads index nothing of their own). `collection` is anything
    with Chroma's delete(where=...); by default the app's collection.
    """
    if not thread_id:
        raise ValueError("thread_id is required")
    (collection if collection is not None else get_chunk_collection()).delete(where={"thread_id": thread_id})


def index_document(text: str, filename: str, thread_id: str) -> int:
    """
    Split a document into semantic chunks and index it in ChromaDB, tagged
    with its thread and filename; an earlier upload of the same file in the
    thread is replaced.
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
    # Re-uploading a file replaces its chunks instead of adding a second copy.
    get_chunk_collection().delete(where={"$and": [{"thread_id": thread_id}, {"filename": filename}]})
    vs.add_documents(chunks)
    log.info(f"[RAG] Indexed {len(chunks)} chunks (thread {thread_id})")

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

    # returns [(Document, score), ...] - score is L2 distance for default Chroma.
    # Errors propagate: the graph reports them as a notice on the turn rather
    # than answering as if the thread had no documents.
    docs_and_scores = vs.similarity_search_with_score(query, k=k, filter=filter_dict)
    log.info(f"[RAG] Retrieved {len(docs_and_scores)} chunks (thread {thread_id})")
    return [doc for doc, score in docs_and_scores]
