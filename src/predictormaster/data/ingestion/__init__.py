"""Ingestion adapters. Each adapter has a refresh cadence, latency budget, and
schema validation pass. Network calls are isolated behind a Source ABC so the
test suite can run hermetic.
"""
