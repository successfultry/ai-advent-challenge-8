from week_05.chunking import FixedSizeChunker, StructureChunker
from week_05.models import Document


def _doc(content: str, *, ext: str = ".txt") -> Document:
    return Document(
        source="sample" + ext,
        title="sample",
        content=content,
        extension=ext,
        language="text",
        metadata={},
    )


def test_fixed_chunking_overlap_and_determinism() -> None:
    chunker = FixedSizeChunker(chunk_size=10, overlap=2)
    content = "abcdefghijklmnopqrstuvwxyz"

    first = chunker.chunk(_doc(content))
    second = chunker.chunk(_doc(content))

    assert len(first) == len(second)
    assert [c.chunk_id for c in first] == [c.chunk_id for c in second]
    assert first[1].start_char == 8
    assert first[1].text.startswith("ijkl")


def test_structure_markdown_sections() -> None:
    md = "# Intro\nHello\n\n## Part\nWorld\n\n### End\nDone"
    chunker = StructureChunker(max_section_chars=100)
    chunks = chunker.chunk(_doc(md, ext=".md"))

    assert len(chunks) == 3
    assert chunks[0].section == "heading:Intro"
    assert chunks[1].section == "heading:Part"
    assert chunks[2].section == "heading:End"


def test_structure_python_ast_split() -> None:
    py = (
        "class A:\n"
        "    pass\n\n"
        "def f():\n"
        "    return 1\n\n"
        "async def g():\n"
        "    return 2\n"
    )
    chunker = StructureChunker(max_section_chars=100)
    chunks = chunker.chunk(_doc(py, ext=".py"))

    sections = [c.section for c in chunks]
    assert "class:A" in sections
    assert "function:f" in sections
    assert "function:g" in sections
