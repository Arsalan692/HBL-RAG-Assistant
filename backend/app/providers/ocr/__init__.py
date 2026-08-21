"""OCR engines, one module per candidate.

Nothing is imported here. Each engine pulls in heavy, optional dependencies —
torch, transformers, engine-specific model code — and the registry has to be
able to report on all of them from a laptop where none are installed. Importing
an engine is what `registry.load_ocr` does, deliberately, at the point of use.
"""
