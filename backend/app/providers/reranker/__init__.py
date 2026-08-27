"""Reranking providers, one module per implementation.

Not imported here, for the same reason as the embedding package: the registry
must be able to describe `bge_reranker` from a machine where torch is not
installed, and importing it would defeat that.
"""
