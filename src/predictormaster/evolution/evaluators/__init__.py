"""Strategy-specific evaluators for the AlphaEvolve loop.

An Evaluator turns a Genome into per-bet returns. The contract is
narrow on purpose — the fitness machinery in ``..fitness`` is
strategy-agnostic and only consumes the resulting return arrays.
"""
from .arb_replay import ArbReplayEvaluator
from .sentiment_daily import SentimentDailyEvaluator, build_sentiment_daily_evaluator

__all__ = [
    "ArbReplayEvaluator",
    "SentimentDailyEvaluator",
    "build_sentiment_daily_evaluator",
]
