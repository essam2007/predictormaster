"""Transformer sequence model for game-by-game form sequences.

The HuggingFace `transformers` integration is optional; this module provides
the training-loop interface and a pure-NumPy attention reference used in
tests. In production we fine-tune `microsoft/deberta-v3-small` on a sports
domain corpus from a Hugging Face checkpoint.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


def softmax(x: np.ndarray, axis: int = -1) -> np.ndarray:
    x = x - x.max(axis=axis, keepdims=True)
    e = np.exp(x)
    return e / e.sum(axis=axis, keepdims=True)


def scaled_dot_product_attention(
    Q: np.ndarray, K: np.ndarray, V: np.ndarray, mask: np.ndarray | None = None
) -> np.ndarray:
    """Reference implementation. Useful for unit tests."""
    d = Q.shape[-1]
    scores = (Q @ np.swapaxes(K, -1, -2)) / np.sqrt(d)
    if mask is not None:
        scores = np.where(mask, scores, -1e30)
    return softmax(scores, axis=-1) @ V


@dataclass
class SeqModelConfig:
    base_checkpoint: str = "microsoft/deberta-v3-small"
    seq_len: int = 64
    hidden_size: int = 384
    n_heads: int = 6
    n_layers: int = 6
    dropout: float = 0.1
    learning_rate: float = 1e-4
    weight_decay: float = 1e-2
    batch_size: int = 64
    max_steps: int = 20_000
    warmup_steps: int = 1_000


@dataclass
class TransformerSeqTrainer:
    config: SeqModelConfig = field(default_factory=SeqModelConfig)
    state: dict[str, Any] | None = None

    def fit(self, train_loader, val_loader) -> None:  # pragma: no cover - integration
        try:
            import torch
            from torch.optim import AdamW
            from transformers import (
                AutoConfig,
                AutoModelForSequenceClassification,
                get_cosine_schedule_with_warmup,
            )
        except Exception as exc:
            raise RuntimeError("PyTorch + transformers are required to train") from exc

        cfg = AutoConfig.from_pretrained(self.config.base_checkpoint, num_labels=3)
        model = AutoModelForSequenceClassification.from_pretrained(
            self.config.base_checkpoint, config=cfg
        )
        opt = AdamW(model.parameters(), lr=self.config.learning_rate, weight_decay=self.config.weight_decay)
        sched = get_cosine_schedule_with_warmup(opt, self.config.warmup_steps, self.config.max_steps)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model.to(device)
        for step, batch in enumerate(train_loader, start=1):
            opt.zero_grad()
            out = model(**{k: v.to(device) for k, v in batch.items()})
            out.loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sched.step()
            if step >= self.config.max_steps:
                break
        self.state = {"model": model.state_dict(), "config": cfg.to_dict()}
