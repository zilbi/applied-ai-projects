# Safety-Aware RUL Prediction

## Overview

This implementation predicts the remaining useful life of turbofan engines using
the NASA C-MAPSS FD001 dataset.

The final pipeline combines rolling-window features, a Random Forest quantile
ensemble and out-of-fold residual correction.

## Final Notebook

- [safety-aware-rul-prediction.ipynb](safety-aware-rul-prediction.ipynb)
- [Interactive RUL Explorer](simulator/) — browser-based view of selected C-MAPSS
  test-engine trajectories

## Results

| Metric | Dummy mean regressor | Final model |
| --- | ---: | ---: |
| MAE | 40.88 | **8.79** |
| RMSE | 52.62 | **12.48** |
| R² | -0.604 | **0.910** |
| Asymmetric NASA score | 269,287.50 | **207.04** |
| Overestimation share | 71% | **47%** |
| Maximum overestimation | 100.81 | **31.10** |
| Near-failure MAE | 90.09 | **2.32** |

The dummy model predicts the training-set mean for every test engine. It is included
as a simple lower-bound reference; the intermediate experiments are summarized in
the root project README.

Final correction parameters:

- model: `RF_depth6`
- residual clipping: 5 cycles
- safety shift: 2 cycles

## Structure

- `safety-aware-rul-prediction.ipynb` — final experiment
- `CMAPSSData/` — FD001 train, test and RUL files
- `architecture_diagram.png` — Random Forest model illustration
- `requirements.txt` — Python dependencies

## Run

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
jupyter lab safety-aware-rul-prediction.ipynb
```

Run the notebook from this directory so that the relative `CMAPSSData` path is
resolved correctly.
