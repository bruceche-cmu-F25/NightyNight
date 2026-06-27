"""PDF ingestion pipeline — three independently testable modules:

  PDFLoader        — walks a sources directory, yields (domain, filename, text)
  Chunker          — splits extracted text into LangChain Documents
  VectorIndexWriter — batches Documents into Milvus with rate-limited uploads

Top-level `ingest_sources` orchestrates all three.
"""

import logging
import os
import time
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple

from langchain_core.documents import Document
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_milvus import Milvus
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

logger = logging.getLogger(__name__)

# ── Config (overridable via env) ──────────────────────────────────────────────

_MILVUS_URI        = os.getenv("MILVUS_URI",        "http://34.67.37.109:19530")
_MILVUS_TOKEN      = os.getenv("MILVUS_TOKEN",      "")
_MILVUS_COLLECTION = os.getenv("MILVUS_COLLECTION", "science_knowledge")
_MILVUS_INDEX      = os.getenv("INDEX_TYPE",        "HNSW").upper()
_EMB_MODEL         = os.getenv("GEMINI_EMB_MODEL",  "gemini-embedding-001")
_CHUNK_SIZE        = int(os.getenv("CHUNK_SIZE",    "800"))
_CHUNK_OVERLAP     = int(os.getenv("CHUNK_OVERLAP", "120"))


# ── PDFLoader ─────────────────────────────────────────────────────────────────

def load_pdfs(
    sources_dir: str,
) -> Generator[Tuple[str, str, str], None, None]:
    """Yield ``(domain, filename, full_text)`` for every readable PDF.

    Expected layout::

        sources_dir/
            cosmos/          ← folder name becomes the domain tag
                book.pdf
            life/
                bio.pdf

    Files that cannot be read or contain no extractable text are logged and
    skipped; the caller never sees them.
    """
    for domain_entry in sorted(os.scandir(sources_dir), key=lambda e: e.name):
        if not domain_entry.is_dir():
            continue
        domain = domain_entry.name
        for file_entry in sorted(os.scandir(domain_entry.path), key=lambda e: e.name):
            if not file_entry.is_file() or not file_entry.name.lower().endswith(".pdf"):
                continue
            try:
                raw_bytes = Path(file_entry.path).read_bytes()
                reader    = PdfReader(BytesIO(raw_bytes))
                text      = "\n".join(p.extract_text() or "" for p in reader.pages).strip()
                if not text:
                    raise ValueError("no extractable text")
            except Exception as exc:
                logger.warning("Skipping %s: %s", file_entry.path, exc)
                continue
            yield domain, file_entry.name, text


# ── Chunker ───────────────────────────────────────────────────────────────────

def chunk_document(
    domain:   str,
    filename: str,
    text:     str,
    chunk_size:    int = _CHUNK_SIZE,
    chunk_overlap: int = _CHUNK_OVERLAP,
) -> List[Document]:
    """Split ``text`` into overlapping chunks tagged with ``domain``/``filename`` metadata."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", " ", ""],
    )
    return [
        Document(
            page_content=chunk,
            metadata={"domain": domain, "source": filename, "chunk_id": i},
        )
        for i, chunk in enumerate(splitter.split_text(text))
    ]


# ── VectorIndexWriter ─────────────────────────────────────────────────────────

def make_vector_store(
    embeddings: GoogleGenerativeAIEmbeddings,
    drop_old:   bool = False,
) -> Milvus:
    """Open (or create) the Milvus collection and return a ready-to-use store."""
    conn_args: Dict[str, Any] = {"uri": _MILVUS_URI}
    if _MILVUS_TOKEN:
        conn_args["token"] = _MILVUS_TOKEN
    return Milvus(
        embedding_function=embeddings,
        collection_name=_MILVUS_COLLECTION,
        connection_args=conn_args,
        index_params={
            "index_type": _MILVUS_INDEX, "metric_type": "COSINE",
            "params": {"M": 16, "efConstruction": 200},
        },
        search_params={"metric_type": "COSINE", "params": {"ef": 64}},
        auto_id=True,
        drop_old=drop_old,
    )


def write_to_vector_store(
    vs:         Milvus,
    docs:       List[Document],
    batch_size: int   = 200,
    pause_sec:  float = 5.0,
) -> None:
    """Upload ``docs`` to ``vs`` in rate-limited batches."""
    for start in range(0, len(docs), batch_size):
        batch = docs[start: start + batch_size]
        vs.add_documents(batch)
        logger.info("Ingested chunks %d–%d / %d", start + 1, start + len(batch), len(docs))
        if start + batch_size < len(docs):
            time.sleep(pause_sec)


# ── Orchestrator ──────────────────────────────────────────────────────────────

def ingest_sources(sources_dir: str, drop_old: bool = False) -> Dict[str, Any]:
    """Chunk and index all PDFs under ``sources_dir/{domain}/`` into Milvus."""
    embeddings = GoogleGenerativeAIEmbeddings(model=_EMB_MODEL)
    vs         = make_vector_store(embeddings, drop_old=drop_old)

    batch_size = int(os.getenv("INGEST_BATCH_SIZE",    "200"))
    pause_sec  = float(os.getenv("INGEST_BATCH_PAUSE_SEC", "5"))

    all_docs:     List[Document]    = []
    domain_stats: Dict[str, int]    = {}
    skipped:      List[str]         = []

    for domain, filename, text in load_pdfs(sources_dir):
        chunks = chunk_document(domain, filename, text)
        all_docs.extend(chunks)
        domain_stats[domain] = domain_stats.get(domain, 0) + 1

    write_to_vector_store(vs, all_docs, batch_size=batch_size, pause_sec=pause_sec)
    logger.info("Ingested %d chunks across domains: %s", len(all_docs), domain_stats)

    return {
        "total_chunks": len(all_docs),
        "chunk_size":   _CHUNK_SIZE,
        "chunk_overlap": _CHUNK_OVERLAP,
        "domains":      domain_stats,
        "skipped":      skipped,
    }
