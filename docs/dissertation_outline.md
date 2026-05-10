# PhD Dissertation Outline

| Chapter | Title                                                        | System component mapped                          | Research contribution                                   |
| ------- | ------------------------------------------------------------ | ------------------------------------------------ | ------------------------------------------------------- |
| 1       | Introduction and motivation                                  | architecture, slas                               | Problem framing                                         |
| 2       | Probabilistic forecasting under operational latency          | serving, monte_carlo                             | Latency-aware proper-scoring-rule training              |
| 3       | Structural models for low-scoring sports                     | dixon_coles, bayesian_hierarchical, kalman, hmm  | Identifiability, MLE bias bounds, convergence proofs    |
| 4       | Sequence and graph learning over player networks             | transformer_seq, gnn                             | Spectral inductive biases, sample-complexity bounds     |
| 5       | Multi-modal fusion: sentiment, narrative, contagion          | nlp/, simulation/scenario_tree                   | Identification of narrative-velocity as a signal class  |
| 6       | Calibration as a first-class engineering concern             | validation/                                      | Continuous-deployment calibration gates                 |
| 7       | Market efficiency and reflexivity in sports markets          | market/efficiency                                | Reflexivity econometrics; FDR-corrected anomaly catalogue|
| 8       | Drift, regime shifts, and online learning                    | validation/drift, models/online                  | Page-Hinkley detection-latency analysis                 |
| 9       | System design and reproducibility                            | infra/, pipelines/                               | Reproducibility-as-CI                                   |
| 10      | Conclusion and future work                                   | -                                                | Open problems                                           |

Each chapter has a deliverable: a journal article whose preprint and
data-release artefacts live in this monorepo under `docs/papers/<chapter>/`.
