# Remaining Useful Life Prediction for Aerospace Technical Systems

## Overview

This project focuses on predicting the remaining useful life of aerospace
technical systems using multivariate sensor time series.

The goal is to estimate how many operating cycles remain before engine failure
and to reduce dangerous RUL overestimation in safety-critical maintenance tasks.

## Task

- input: multivariate sensor time series
- output: remaining useful life, measured in operating cycles
- task type: time-series regression

## Data

Main dataset:

- NASA C-MAPSS Jet Engine Simulated Data
- FD001 subset
- 100 training engines
- 100 test engines
- 21 sensor channels and 3 operating settings

## Approach

- data preprocessing and sensor analysis
- rolling-window feature construction
- Random Forest regression with a capped RUL target
- quantile ensemble for conservative prediction
- out-of-fold residual correction
- safety-oriented error analysis

## Models

- Dummy mean regressor
- Random Forest rolling-window model
- Random Forest quantile ensemble
- Random Forest residual correction

## Metrics

- MAE
- RMSE
- R²
- asymmetric NASA RUL score
- overestimation share
- near-failure MAE

## Results

The public comparison uses a deliberately simple reference model. The dummy
regressor predicts the same value for every engine: the mean RUL observed in the
training rows.

| Metric | Dummy mean regressor | Final model |
| --- | ---: | ---: |
| MAE | 40.88 | **8.79** |
| RMSE | 52.62 | **12.48** |
| R² | -0.604 | **0.910** |
| Asymmetric NASA score | 269,287.50 | **207.04** |
| Overestimation share | 71% | **47%** |
| Maximum overestimation | 100.81 | **31.10** |
| Near-failure MAE | 90.09 | **2.32** |

The final configuration uses `RF_depth6`, residual clipping at 5 cycles and a
2-cycle safety shift.

## Development Path

The final notebook keeps only the reproducible pipeline. The main experimental
steps and their outcomes are summarized here instead of storing every intermediate
implementation in the public project.

| Stage | Approach | Outcome |
| --- | --- | --- |
| Naive reference | Constant prediction based on the training-set mean | MAE 40.88; used only as a lower-bound reference |
| Initial Random Forest | Flattened sensor history from the latest 100 cycles | MAE 13.30; near-failure MAE 6.31 |
| Aggregated features | Rolling statistics, trends, deltas, ranges and conservative shifting | MAE 12.50; near-failure MAE 3.83 |
| Broad evolutionary search | Automated search over feature blocks, window size, RUL cap and Random Forest settings | Internal MAE 5.33 but official-test MAE 14.80; rejected because the validation winner did not generalize |
| Robust candidate selection | Official robustness check across 25 shortlisted configurations | MAE 9.48; near-failure MAE 2.58 |
| Quantile calibration | Conservative tree-quantile prediction and safety shift | Best MAE 9.10; stronger than the tested direct residual branch at 9.51 |
| Alternative estimator | CatBoost was evaluated as a parallel modeling experiment | It did not improve the selected Random Forest pipeline and was not retained |
| OOF residual correction | Engine-level out-of-fold residual model with clipped correction | Final MAE 8.79; near-failure MAE 2.32 |
| Alternative branch stacking | Convex blending and safety-weighted stacking of team model branches | Best new blend MAE 8.92; did not improve the selected final pipeline |

This sequence also changed the evaluation strategy. Later experiments were judged
not only by MAE, but also by asymmetric error cost, overestimation share, maximum
overestimation and near-failure behavior.

## Research Focus

- effect of time-window features on RUL prediction
- conservative prediction for safety-critical systems
- reduction of RUL overestimation
- error analysis across degradation stages

## Structure

- [presentation](presentation/project-overview-presentation.pdf) — project overview
  presentation
- [interim-results](interim-results/) — intermediate experimental reports
- [aerospace-rul-prediction](aerospace-rul-prediction/) — final notebook,
  requirements and FD001 data
