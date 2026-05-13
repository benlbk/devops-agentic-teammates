"""RAG pipeline for codebase knowledge retrieval."""

from __future__ import annotations

from typing import Any

import structlog
from langchain_aws import BedrockEmbeddings
from opensearchpy import OpenSearch, RequestsHttpConnection

from shared.config import settings

logger = structlog.get_logger()

EMBEDDING_MODEL = "amazon.titan-embed-text-v2:0"
INDEX_NAME = "codebase-knowledge"

INDEX_BODY = {
    "settings": {
        "index": {
            "knn": True,
            "number_of_shards": 2,
            "number_of_replicas": 1,
        }
    },
    "mappings": {
        "properties": {
            "embedding": {
                "type": "knn_vector",
                "dimension": 1024,
                "method": {
                    "engine": "faiss",
                    "space_type": "l2",
                    "name": "hnsw",
                    "parameters": {"ef_construction": 256, "m": 48},
                },
            },
            "content": {"type": "text"},
            "file_path": {"type": "keyword"},
            "repository": {"type": "keyword"},
            "language": {"type": "keyword"},
            "chunk_index": {"type": "integer"},
            "metadata": {"type": "object"},
        }
    },
}


class RAGPipeline:
    """Codebase indexing and retrieval using OpenSearch vector search."""

    def __init__(self) -> None:
        self._embeddings = BedrockEmbeddings(
            model_id=EMBEDDING_MODEL,
            region_name=settings.bedrock_region,
        )
        self._client: OpenSearch | None = None

    @property
    def client(self) -> OpenSearch:
        if self._client is None:
            self._client = OpenSearch(
                hosts=[settings.opensearch_endpoint],
                use_ssl=True,
                verify_certs=True,
                connection_class=RequestsHttpConnection,
            )
        return self._client

    def ensure_index(self) -> None:
        """Create the index if it doesn't exist."""
        if not self.client.indices.exists(INDEX_NAME):
            self.client.indices.create(INDEX_NAME, body=INDEX_BODY)
            logger.info("Created OpenSearch index", index=INDEX_NAME)

    def _chunk_code(self, content: str, chunk_size: int = 1500, overlap: int = 200) -> list[str]:
        """Split code content into overlapping chunks."""
        lines = content.split("\n")
        chunks: list[str] = []
        current_chunk: list[str] = []
        current_size = 0

        for line in lines:
            current_chunk.append(line)
            current_size += len(line) + 1

            if current_size >= chunk_size:
                chunks.append("\n".join(current_chunk))
                # Keep last few lines for overlap
                overlap_lines = []
                overlap_size = 0
                for prev_line in reversed(current_chunk):
                    overlap_lines.insert(0, prev_line)
                    overlap_size += len(prev_line) + 1
                    if overlap_size >= overlap:
                        break
                current_chunk = overlap_lines
                current_size = overlap_size

        if current_chunk:
            chunks.append("\n".join(current_chunk))

        return chunks

    async def index_file(
        self, repository: str, file_path: str, content: str,
        language: str, metadata: dict[str, Any] | None = None,
    ) -> int:
        """Index a single file's contents into the vector store."""
        chunks = self._chunk_code(content)
        indexed = 0

        for i, chunk in enumerate(chunks):
            embedding = self._embeddings.embed_query(chunk)
            doc = {
                "content": chunk,
                "embedding": embedding,
                "repository": repository,
                "file_path": file_path,
                "language": language,
                "chunk_index": i,
                "metadata": metadata or {},
            }
            doc_id = f"{repository}/{file_path}#{i}"
            self.client.index(
                index=INDEX_NAME,
                id=doc_id,
                body=doc,
            )
            indexed += 1

        logger.info("Indexed file", file_path=file_path, chunks=indexed)
        return indexed

    async def search(
        self, query: str, repository: str | None = None,
        language: str | None = None, top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Search for relevant code chunks."""
        query_embedding = self._embeddings.embed_query(query)

        must_clauses: list[dict[str, Any]] = [
            {
                "knn": {
                    "embedding": {
                        "vector": query_embedding,
                        "k": top_k,
                    }
                }
            }
        ]

        if repository:
            must_clauses.append({"term": {"repository": repository}})
        if language:
            must_clauses.append({"term": {"language": language}})

        body = {
            "size": top_k,
            "query": {
                "bool": {
                    "must": must_clauses,
                }
            },
        }

        response = self.client.search(index=INDEX_NAME, body=body)
        results = []
        for hit in response["hits"]["hits"]:
            source = hit["_source"]
            results.append({
                "content": source["content"],
                "file_path": source["file_path"],
                "repository": source["repository"],
                "language": source["language"],
                "score": hit["_score"],
            })

        return results

    async def delete_repository(self, repository: str) -> int:
        """Delete all indexed documents for a repository."""
        response = self.client.delete_by_query(
            index=INDEX_NAME,
            body={"query": {"term": {"repository": repository}}},
        )
        deleted = response.get("deleted", 0)
        logger.info("Deleted repository index", repository=repository, deleted=deleted)
        return deleted


rag_pipeline = RAGPipeline()
