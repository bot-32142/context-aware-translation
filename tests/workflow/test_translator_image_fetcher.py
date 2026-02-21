from __future__ import annotations

from context_aware_translation.workflow.image_fetcher import RepoImageFetcher


class DummyRepo:
    def __init__(self) -> None:
        self.list_documents_calls = 0
        self.get_document_sources_calls = 0
        self._documents = [{"document_id": 1}, {"document_id": 2}]
        self._sources_by_doc = {
            1: [
                {
                    "source_id": 11,
                    "sequence_number": 0,
                    "binary_content": b"doc1-image",
                    "mime_type": "image/png",
                    "ocr_json": '{"text":"a"}',
                }
            ],
            2: [
                {
                    "source_id": 22,
                    "sequence_number": 0,
                    "binary_content": b"doc2-image",
                    "mime_type": "image/jpeg",
                    "ocr_json": '{"text":"b"}',
                }
            ],
        }

    def list_documents(self) -> list[dict]:
        self.list_documents_calls += 1
        return list(self._documents)

    def get_document_sources(self, document_id: int) -> list[dict]:
        self.get_document_sources_calls += 1
        return list(self._sources_by_doc[document_id])


def test_repo_image_fetcher_uses_source_index_after_first_full_scan() -> None:
    repo = DummyRepo()
    fetcher = RepoImageFetcher(repo)

    image2, mime2 = fetcher.fetch_source_image(22)
    image1, mime1 = fetcher.fetch_source_image(11)

    assert image2 == b"doc2-image"
    assert mime2 == "image/jpeg"
    assert image1 == b"doc1-image"
    assert mime1 == "image/png"
    assert repo.list_documents_calls == 1
    assert repo.get_document_sources_calls == 2
