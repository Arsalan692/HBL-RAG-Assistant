"""Embedding providers, one module per implementation.

Not imported here: `bge_m3` needs torch and sentence-transformers, and the
registry has to be able to describe it from a machine where neither exists.
"""
