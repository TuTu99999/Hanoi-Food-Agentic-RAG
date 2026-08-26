import re

from ingestion.parsers import ParsedSection, slugify
from schemas.course import CourseManifest
from schemas.ingestion import AcademicChunk, CitationMetadata


def _word_windows(
    text: str,
    *,
    max_words: int,
    overlap_words: int,
) -> list[str]:
    if max_words <= 0:
        raise ValueError("max_words phải lớn hơn 0.")
    if overlap_words < 0 or overlap_words >= max_words:
        raise ValueError("overlap_words phải từ 0 đến max_words - 1.")

    words = re.findall(r"\S+", text)
    if not words:
        return []
    step = max_words - overlap_words
    windows = []
    start = 0
    while start < len(words):
        windows.append(" ".join(words[start : start + max_words]))
        if start + max_words >= len(words):
            break
        start += step
    return windows


def _chapter_id(section_title: str | None) -> str | None:
    if not section_title:
        return None
    if not re.match(r"^(chương|phần|bài)\b", section_title, re.I):
        return None
    return slugify(section_title, fallback="chapter")[:100]


def build_academic_chunks(
    *,
    manifest: CourseManifest,
    sections: list[ParsedSection],
    knowledge_version: str,
    max_words: int,
    overlap_words: int,
) -> list[AcademicChunk]:
    chunks: list[AcademicChunk] = []
    document_indexes: dict[str, int] = {}

    for section in sections:
        document_id = section.document.document_id
        for content in _word_windows(
            section.text,
            max_words=max_words,
            overlap_words=overlap_words,
        ):
            document_indexes[document_id] = document_indexes.get(document_id, 0) + 1
            chunk_index = document_indexes[document_id]
            safe_version = manifest.version.replace(".", "_")
            chunk_id = (
                f"{manifest.course_id}__{safe_version}__{document_id}__"
                f"chunk_{chunk_index:04d}"
            )
            section_title = section.section_title or section.document.title
            vector_text = (
                f"Môn học: {manifest.name}\n"
                f"Tài liệu: {section.document.title}\n"
                f"Mục: {section_title}\n"
                f"Nội dung: {content}"
            )
            chunks.append(
                AcademicChunk(
                    chunk_id=chunk_id,
                    chunk_index=chunk_index,
                    course_id=manifest.course_id,
                    course_version=manifest.version,
                    domain=manifest.domain,
                    language=manifest.language,
                    knowledge_version=knowledge_version,
                    document_id=document_id,
                    section_id=section.section_id,
                    chapter_id=_chapter_id(section.section_title),
                    content=content,
                    vector_text=vector_text,
                    word_count=len(content.split()),
                    citation=CitationMetadata(
                        document_id=document_id,
                        document_title=section.document.title,
                        source_path=section.document.source_path,
                        source_type=section.document.source_type,
                        source_authority=section.document.source_authority,
                        publication_year=section.document.publication_year,
                        page_number=section.page_number,
                        section_title=section.section_title,
                        start_line=section.start_line,
                        end_line=section.end_line,
                        start_paragraph=section.start_paragraph,
                        end_paragraph=section.end_paragraph,
                    ),
                )
            )
    return chunks
