"""Print top-1 cosine similarity for on-topic vs off-topic queries (evidence threshold).

Usage: uv run python scripts/calibrate_evidence_threshold.py
Loads BAAI/bge-small-en-v1.5 (downloaded on first use) and chunks tests/fixtures/documents
with CHUNK_SIZE 400 / CHUNK_OVERLAP 60. No database needed. Used to pick
MIN_EVIDENCE_SIMILARITY (docs/rag.md).
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

OFF_TOPIC = [
    "What is the capital of Australia?",
    "Explain quantum chromodynamics.",
    "Who won the 1998 football world cup?",
    "Recipe for banana bread",
    "How do black holes evaporate?",
    "What is the boiling point of mercury?",
]
# Questions about a whole document (what users type into a document assistant). They match
# no single passage well, so they show how low genuine-but-generic questions score.
DOCUMENT_LEVEL = [
    "What is this document about?",
    "Summarize the document.",
    "What are the key points?",
    "List the main rules described here.",
    "Who is this policy for?",
    "What are the deadlines mentioned?",
]
QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "


def main() -> None:
    import numpy as np  # noqa: PLC0415
    from sentence_transformers import SentenceTransformer  # noqa: PLC0415

    from app.processing.chunking import RecursiveTokenChunker  # noqa: PLC0415
    from app.processing.extraction import TextExtractor  # noqa: PLC0415
    from app.processing.normalization import normalize_content  # noqa: PLC0415

    model = SentenceTransformer("BAAI/bge-small-en-v1.5", device="cpu")

    class _Counter:
        def count_tokens(self, text: str) -> int:
            return len(model.tokenizer(text, add_special_tokens=False)["input_ids"])

    chunker = RecursiveTokenChunker(_Counter(), chunk_size=400, chunk_overlap=60, max_chunks=1000)
    texts: list[str] = []
    for path in sorted((PROJECT_ROOT / "tests/fixtures/documents").glob("*.txt")):
        content = normalize_content(TextExtractor().extract(path.read_bytes()))
        texts += [chunk.text for chunk in chunker.chunk(content)]
    documents = model.encode(texts, normalize_embeddings=True)
    spec = json.loads((PROJECT_ROOT / "tests/fixtures/eval_queries.json").read_text("utf-8"))
    on_topic = [item["query"] for item in spec["queries"]]
    groups = (("on-topic", on_topic), ("document-level", DOCUMENT_LEVEL), ("off-topic", OFF_TOPIC))
    for name, group in groups:
        queries = model.encode([QUERY_INSTRUCTION + q for q in group], normalize_embeddings=True)
        top = (queries @ documents.T).max(axis=1)
        print(
            f"{name}: queries={len(group)} chunks={len(texts)} "
            f"min={float(top.min()):.3f} median={float(np.median(top)):.3f} "
            f"max={float(top.max()):.3f}"
        )


if __name__ == "__main__":
    main()
