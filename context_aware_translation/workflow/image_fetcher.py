from context_aware_translation.documents.manga_alignment import extract_ocr_text, list_nonempty_ocr_source_ids
from context_aware_translation.storage.document_repository import DocumentRepository


class RepoImageFetcher:
    """ImageFetcher backed by DocumentRepository with per-document caches."""

    def __init__(self, repo: DocumentRepository) -> None:
        self._repo = repo
        self._cache: dict[int, dict] = {}
        self._source_index: dict[int, dict] = {}
        self._all_documents_cached = False

    def _ensure_cached(self, doc_id: int) -> None:
        if doc_id not in self._cache:
            sources = self._repo.get_document_sources(doc_id)
            source_map = {s["source_id"]: s for s in sources}
            self._cache[doc_id] = source_map
            self._source_index.update(source_map)

    def _ensure_all_cached(self) -> None:
        if self._all_documents_cached:
            return
        for doc_row in self._repo.list_documents():
            self._ensure_cached(doc_row["document_id"])
        self._all_documents_cached = True

    def _get_source(self, source_id: int) -> dict:
        source = self._source_index.get(source_id)
        if source is None:
            if self._all_documents_cached:
                # Document set may have changed since first full scan.
                self._all_documents_cached = False
            self._ensure_all_cached()
            source = self._source_index.get(source_id)
        if source is None:
            raise ValueError(f"Source {source_id} not found")
        return source

    def fetch_source_image(self, source_id: int) -> tuple[bytes, str]:
        source = self._get_source(source_id)
        if source.get("binary_content") is None:
            raise ValueError(f"No image data for source {source_id}")
        return (source["binary_content"], source.get("mime_type", "image/png"))

    def fetch_source_ocr_text(self, source_id: int) -> str:
        source = self._get_source(source_id)
        return extract_ocr_text(source.get("ocr_json"))

    def list_page_source_ids(self, document_id: int) -> list[int]:
        """Return non-empty OCR source ids ordered by sequence_number."""
        self._ensure_cached(document_id)
        return list_nonempty_ocr_source_ids(list(self._cache[document_id].values()))
