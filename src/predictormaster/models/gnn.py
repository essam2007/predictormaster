"""Graph neural network on the player-team-opponent graph.

We ship a NumPy reference of one GCN layer (used in tests) plus a
PyTorch-Geometric trainer skeleton. Spectral derivation of the GCN
propagation rule is in docs/derivations/graph_laplacian.md.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def normalized_adjacency(A: np.ndarray) -> np.ndarray:
    A_tilde = A + np.eye(A.shape[0])
    deg = A_tilde.sum(axis=1)
    D_inv_sqrt = np.diag(1.0 / np.sqrt(np.maximum(deg, 1e-12)))
    return D_inv_sqrt @ A_tilde @ D_inv_sqrt


def gcn_layer(A_norm: np.ndarray, X: np.ndarray, W: np.ndarray) -> np.ndarray:
    out = A_norm @ X @ W
    return np.maximum(out, 0.0)


@dataclass
class GraphAttentionTrainer:
    hidden_dim: int = 128
    n_heads: int = 4
    n_layers: int = 3
    dropout: float = 0.2

    def fit(self, data, epochs: int = 100) -> None:  # pragma: no cover - integration
        try:
            import torch
            import torch.nn.functional as F
            from torch_geometric.nn import GATv2Conv
        except Exception as exc:
            raise RuntimeError("torch + torch_geometric are required") from exc

        class GAT(torch.nn.Module):
            def __init__(self, in_dim: int, hidden: int, heads: int, n_layers: int, n_classes: int):
                super().__init__()
                self.convs = torch.nn.ModuleList()
                self.convs.append(GATv2Conv(in_dim, hidden, heads=heads))
                for _ in range(n_layers - 2):
                    self.convs.append(GATv2Conv(hidden * heads, hidden, heads=heads))
                self.convs.append(GATv2Conv(hidden * heads, n_classes, heads=1))

            def forward(self, x, edge_index):
                for conv in self.convs[:-1]:
                    x = F.elu(conv(x, edge_index))
                return self.convs[-1](x, edge_index)

        model = GAT(data.num_node_features, self.hidden_dim, self.n_heads, self.n_layers, 3)
        opt = torch.optim.Adam(model.parameters(), lr=1e-3, weight_decay=5e-4)
        for _ in range(epochs):
            model.train()
            opt.zero_grad()
            out = model(data.x, data.edge_index)
            loss = F.cross_entropy(out[data.train_mask], data.y[data.train_mask])
            loss.backward()
            opt.step()
        self.state = model.state_dict()
