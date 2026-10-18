"""Document intelligence building blocks: extraction, normalization and chunking.

Framework-free (no database, no Celery) so they can be unit-tested and reused by the
worker pipeline (``app/workers/steps.py``) and the evaluation script.
"""
