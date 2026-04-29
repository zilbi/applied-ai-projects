# Remaining Useful Life Prediction for Aerospace Technical Systems

Status: in progress

## Overview

This project focuses on predicting the remaining useful life of aerospace technical systems using multivariate sensor time series.

The goal is to build models that estimate how many operating cycles remain before system failure based on historical sensor readings.

## Task

- input: multivariate sensor time series;
- output: remaining useful life, measured as the number of cycles before failure;
- task type: time-series regression.

## Data

Main dataset:
- C-MAPSS Jet Engine Simulated Data.

## Approach

- data preprocessing and exploratory analysis;
- feature construction using time windows;
- model training and evaluation;
- comparison of modeling approaches and error analysis.

## Models

- linear regression;
- random forest;
- gradient boosting.

## Metrics

- MAE;
- RMSE.

## Research focus

- effect of time-window length;
- effect of feature selection;
- comparison of baseline and stronger models;
- error analysis across different degradation stages.

## Structure

- `presentation/` — presentation materials;
- `interim-results/` — intermediate results;
- `aerospace-rul-prediction/` — team working directory for active development and exchange of intermediate files.
