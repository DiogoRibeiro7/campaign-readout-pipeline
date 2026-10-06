# Results

Written by `readout report` from the registry. Do not edit by hand.

The tables show estimates of refused readouts. They come from the internal audit trail and are here to explain the refusals. What a consumer would receive is in `readouts.jsonl`.

## Data and contracts

Snapshot `0f1a9272f3d09d52`: 2,469 households, 127,431 household-days with a purchase, 2017-01-01 to 2017-12-31, 27 campaigns.

- `campaign_readout@v1:124ebe4b4c55`: history 56 days, outcome 28 days, primary method weighting, tolerance for placebos $5, 2000 bootstrap replications, assignment rule not documented.
- `campaign_readout@v2:868c0ad30f14`: history 112 days, outcome 28 days, primary method weighting, tolerance for placebos $5, 2000 bootstrap replications, assignment rule not documented.

## From the prototype to production rules

Mean estimate over the prototype's 16 campaigns, in US dollars per targeted household. `published by prototype` is the prototype's own output; `pipeline as prototype` is this code given the prototype's inputs and choices; `data as of readout` restricts the data to what existed on the readout date; `production rules` also restricts the households to those that had shopped before the day the covariates are dated.

| window | estimator | campaigns | published by prototype | pipeline as prototype | data as of readout | production rules |
| --- | --- | --- | --- | --- | --- | --- |
| main | regression | 16 | 17.37 | 17.37 | 17.37 | 17.39 |
| main | weighting | 16 | -12.78 | -12.78 | -12.94 | -13.01 |
| placebo | regression | 16 | 13.95 | 13.95 | 13.98 | 13.97 |
| placebo | weighting | 16 | -17.53 | -17.53 | -17.63 | -17.70 |

Largest difference between the prototype's published numbers and the pipeline run the prototype's way: 0.

How much each of the two changes moves one campaign's estimate, in absolute value:

| window | estimator | mean change from data as of readout | largest change from data as of readout | mean change from population at launch | largest change from population at launch |
| --- | --- | --- | --- | --- | --- |
| main | regression | 0.08 | 0.30 | 0.06 | 0.32 |
| main | weighting | 0.17 | 0.83 | 0.07 | 0.28 |
| placebo | regression | 0.07 | 0.32 | 0.08 | 0.50 |
| placebo | weighting | 0.14 | 0.58 | 0.29 | 1.78 |

Households an analysis runs on: 2,469 in the whole year, as few as 2,322 seen by a readout date and 2,168 seen before the day the covariates are dated (the smallest is a shifted placebo's). The weighting rows include the Type A campaigns, for which weighting has almost no comparable households; the pipeline refuses those at the overlap gate.

## The period, read out campaign by campaign

### Contract v1, primary method (weighting)

24 readouts fell due by the end of the snapshot: 0 published, 24 refused. Readouts failing each gate (a readout that reaches the two placebo gates can fail both): data 8, timing 0, estimator 0, overlap 3, pre-history placebo 13, assignment 13.

| campaign | campaign type | launch | as of | targeted | comparison | verdict | reasons |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 24 | Type C | 2016-11-14 | 2016-12-12 | 0 | 0 | refused | DATA_NO_FEED |
| 25 | Type B | 2016-12-06 | 2017-01-03 | 0 | 0 | refused | DATA_INSUFFICIENT_HISTORY |
| 26 | Type B | 2016-12-28 | 2017-01-25 | 0 | 0 | refused | DATA_INSUFFICIENT_HISTORY |
| 27 | Type A | 2017-02-08 | 2017-03-08 | 344 | 1701 | refused | DATA_INSUFFICIENT_HISTORY |
| 1 | Type B | 2017-03-03 | 2017-03-31 | 13 | 2163 | refused | DATA_INSUFFICIENT_HISTORY |
| 2 | Type B | 2017-03-08 | 2017-04-05 | 48 | 2158 | refused | DATA_INSUFFICIENT_HISTORY |
| 3 | Type C | 2017-03-13 | 2017-04-10 | 12 | 2208 | refused | DATA_INSUFFICIENT_HISTORY |
| 4 | Type B | 2017-03-29 | 2017-04-26 | 81 | 2185 | refused | PREHISTORY_RECORD_TOO_FEW ASSIGNMENT_UNDOCUMENTED_RECORD_TOO_FEW |
| 5 | Type B | 2017-04-03 | 2017-05-01 | 166 | 2121 | refused | PREHISTORY_RECORD_TOO_FEW ASSIGNMENT_UNDOCUMENTED_RECORD_TOO_FEW |
| 6 | Type C | 2017-04-19 | 2017-05-17 | 65 | 2251 | refused | PREHISTORY_OWN_OUTSIDE ASSIGNMENT_UNDOCUMENTED_RECORD_TOO_FEW |
| 7 | Type B | 2017-04-24 | 2017-05-22 | 198 | 2123 | refused | PREHISTORY_RECORD_TOO_FEW ASSIGNMENT_UNDOCUMENTED_RECORD_TOO_FEW |
| 8 | Type A | 2017-05-08 | 2017-06-05 | 1075 | 1267 | refused | OVERLAP_EXTREME_SCORES |
| 9 | Type B | 2017-05-31 | 2017-06-28 | 176 | 2196 | refused | PREHISTORY_RECORD_BIAS ASSIGNMENT_UNDOCUMENTED_RECORD_NOT_CERTIFIED |
| 10 | Type B | 2017-06-28 | 2017-07-26 | 123 | 2268 | refused | PREHISTORY_RECORD_BIAS ASSIGNMENT_UNDOCUMENTED_RECORD_NOT_CERTIFIED |
| 11 | Type B | 2017-07-12 | 2017-08-09 | 214 | 2189 | refused | PREHISTORY_OWN_OUTSIDE ASSIGNMENT_UNDOCUMENTED_RECORD_NOT_CERTIFIED |
| 12 | Type B | 2017-07-12 | 2017-08-09 | 170 | 2233 | refused | PREHISTORY_RECORD_NOT_CERTIFIED ASSIGNMENT_UNDOCUMENTED_RECORD_NOT_CERTIFIED |
| 13 | Type A | 2017-08-08 | 2017-09-05 | 1077 | 1343 | refused | OVERLAP_EXTREME_SCORES |
| 14 | Type C | 2017-09-04 | 2017-10-02 | 224 | 2209 | refused | PREHISTORY_RECORD_NOT_CERTIFIED ASSIGNMENT_UNDOCUMENTED_RECORD_NOT_CERTIFIED |
| 15 | Type C | 2017-09-20 | 2017-10-18 | 17 | 2422 | refused | DATA_TOO_FEW_TREATED |
| 16 | Type B | 2017-10-04 | 2017-11-01 | 188 | 2259 | refused | PREHISTORY_RECORD_NOT_CERTIFIED ASSIGNMENT_UNDOCUMENTED_RECORD_NOT_CERTIFIED |
| 17 | Type B | 2017-10-18 | 2017-11-15 | 202 | 2249 | refused | PREHISTORY_OWN_OUTSIDE ASSIGNMENT_UNDOCUMENTED_RECORD_NOT_CERTIFIED |
| 18 | Type A | 2017-10-30 | 2017-11-27 | 1133 | 1319 | refused | OVERLAP_EXTREME_SCORES |
| 19 | Type B | 2017-11-15 | 2017-12-13 | 130 | 2328 | refused | PREHISTORY_RECORD_NOT_CERTIFIED ASSIGNMENT_UNDOCUMENTED_RECORD_NOT_CERTIFIED |
| 20 | Type C | 2017-11-27 | 2017-12-25 | 244 | 2218 | refused | PREHISTORY_RECORD_NOT_CERTIFIED ASSIGNMENT_UNDOCUMENTED_RECORD_NOT_CERTIFIED |

What the pipeline measured for the campaigns that reached estimation, those refused at the overlap gate included. `largest shift from one household` is the most the estimate moves when a single household is left out; `smallest tolerance` is the smallest tolerance at which the readout would have been published with the rule unknown.

| campaign | estimate (not published) | pre-history placebo | shifted placebo | treated extreme share | effective controls | largest weight share | largest shift from one household | smallest tolerance undocumented |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 4 | 24.3 [-6.8, 56.1] | 33.7 [4.1, 65.0] | 2.5 [-25.7, 30.8] | 0.00 | 975.25 | 0.00 | 10.57 | 64.99 |
| 5 | 2.9 [-57.8, 42.0] | 2.8 [-55.9, 39.3] | -9.8 [-98.3, 40.1] | 0.00 | 395.38 | 0.03 | 23.55 | 98.27 |
| 6 | 37.8 [-9.0, 83.0] | 55.2 [14.1, 94.4] | 14.4 [-27.1, 59.6] | 0.00 | 334.31 | 0.01 | 9.84 | 94.36 |
| 7 | 22.4 [1.3, 44.0] | 26.8 [3.2, 50.2] | 24.9 [1.7, 48.5] | 0.00 | 677.56 | 0.01 | 3.82 | 50.21 |
| 8 | -67.9 [-160.7, -2.7] | -37.8 [-300.0, 33.6] | -64.8 [-264.1, 13.8] | 0.18 | 7.97 | 0.34 | 31.40 | none |
| 9 | -14.5 [-35.3, 6.7] | -3.1 [-25.3, 18.6] | 22.0 [1.2, 45.8] | 0.00 | 962.79 | 0.01 | 4.89 | 45.82 |
| 10 | 3.0 [-35.1, 38.1] | 17.7 [-21.4, 56.1] | 14.0 [-22.9, 47.5] | 0.00 | 478.31 | 0.01 | 11.37 | 56.15 |
| 11 | 0.5 [-25.6, 27.6] | 36.4 [9.4, 63.6] | -12.1 [-40.9, 15.6] | 0.00 | 518.01 | 0.01 | 5.22 | 63.61 |
| 12 | 10.2 [-83.7, 48.2] | 16.7 [-186.5, 68.1] | 8.0 [-41.1, 39.5] | 0.00 | 396.82 | 0.02 | 19.87 | 100.18 |
| 13 | -114.9 [-361.8, 94.9] | -48.9 [-235.5, 34.1] | -134.1 [-294.5, 68.3] | 0.41 | 7.29 | 0.23 | 79.42 | none |
| 14 | 9.6 [-33.0, 43.1] | 38.3 [4.3, 66.4] | -13.6 [-67.1, 22.6] | 0.00 | 420.78 | 0.01 | 14.09 | 66.39 |
| 16 | -6.6 [-58.1, 30.5] | -1.6 [-40.7, 34.6] | 2.1 [-52.9, 35.7] | 0.00 | 392.00 | 0.02 | 16.49 | 40.71 |
| 17 | 3.3 [-21.6, 29.8] | 38.4 [11.5, 66.7] | 15.0 [-9.6, 38.9] | 0.00 | 550.35 | 0.01 | 4.27 | 66.66 |
| 18 | -164.4 [-269.2, -38.9] | -141.6 [-278.1, 11.9] | -147.1 [-313.8, -20.6] | 0.34 | 7.52 | 0.35 | 41.31 | none |
| 19 | 29.9 [2.6, 58.0] | -3.6 [-33.6, 26.1] | 20.1 [-4.4, 45.9] | 0.00 | 776.45 | 0.01 | 5.62 | 34.19 |
| 20 | 16.3 [-16.1, 50.0] | -16.8 [-64.6, 25.4] | -24.8 [-62.2, 13.8] | 0.00 | 268.65 | 0.03 | 9.35 | 64.57 |

Median width of one campaign's shifted-placebo interval, among the campaigns that passed the overlap gate: $70.

### Contract v2, primary method (weighting)

24 readouts fell due by the end of the snapshot: 0 published, 24 refused. Readouts failing each gate (a readout that reaches the two placebo gates can fail both): data 13, timing 0, estimator 0, overlap 2, pre-history placebo 9, assignment 9.

| campaign | campaign type | launch | as of | targeted | comparison | verdict | reasons |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 24 | Type C | 2016-11-14 | 2016-12-12 | 0 | 0 | refused | DATA_NO_FEED |
| 25 | Type B | 2016-12-06 | 2017-01-03 | 0 | 0 | refused | DATA_INSUFFICIENT_HISTORY |
| 26 | Type B | 2016-12-28 | 2017-01-25 | 0 | 0 | refused | DATA_INSUFFICIENT_HISTORY |
| 27 | Type A | 2017-02-08 | 2017-03-08 | 344 | 1701 | refused | DATA_INSUFFICIENT_HISTORY |
| 1 | Type B | 2017-03-03 | 2017-03-31 | 13 | 2163 | refused | DATA_INSUFFICIENT_HISTORY |
| 2 | Type B | 2017-03-08 | 2017-04-05 | 48 | 2158 | refused | DATA_INSUFFICIENT_HISTORY |
| 3 | Type C | 2017-03-13 | 2017-04-10 | 12 | 2208 | refused | DATA_INSUFFICIENT_HISTORY |
| 4 | Type B | 2017-03-29 | 2017-04-26 | 81 | 2185 | refused | DATA_INSUFFICIENT_HISTORY |
| 5 | Type B | 2017-04-03 | 2017-05-01 | 166 | 2121 | refused | DATA_INSUFFICIENT_HISTORY |
| 6 | Type C | 2017-04-19 | 2017-05-17 | 65 | 2251 | refused | DATA_INSUFFICIENT_HISTORY |
| 7 | Type B | 2017-04-24 | 2017-05-22 | 198 | 2123 | refused | DATA_INSUFFICIENT_HISTORY |
| 8 | Type A | 2017-05-08 | 2017-06-05 | 1075 | 1267 | refused | DATA_INSUFFICIENT_HISTORY |
| 9 | Type B | 2017-05-31 | 2017-06-28 | 176 | 2196 | refused | PREHISTORY_RECORD_TOO_FEW ASSIGNMENT_UNDOCUMENTED_RECORD_TOO_FEW |
| 10 | Type B | 2017-06-28 | 2017-07-26 | 123 | 2268 | refused | PREHISTORY_OWN_OUTSIDE ASSIGNMENT_UNDOCUMENTED_RECORD_TOO_FEW |
| 11 | Type B | 2017-07-12 | 2017-08-09 | 214 | 2189 | refused | PREHISTORY_OWN_OUTSIDE ASSIGNMENT_UNDOCUMENTED_RECORD_TOO_FEW |
| 12 | Type B | 2017-07-12 | 2017-08-09 | 170 | 2233 | refused | PREHISTORY_RECORD_TOO_FEW ASSIGNMENT_UNDOCUMENTED_RECORD_TOO_FEW |
| 13 | Type A | 2017-08-08 | 2017-09-05 | 1077 | 1343 | refused | OVERLAP_EXTREME_SCORES |
| 14 | Type C | 2017-09-04 | 2017-10-02 | 224 | 2209 | refused | PREHISTORY_RECORD_BIAS ASSIGNMENT_UNDOCUMENTED_RECORD_NOT_CERTIFIED |
| 15 | Type C | 2017-09-20 | 2017-10-18 | 17 | 2422 | refused | DATA_TOO_FEW_TREATED |
| 16 | Type B | 2017-10-04 | 2017-11-01 | 188 | 2259 | refused | PREHISTORY_RECORD_NOT_CERTIFIED ASSIGNMENT_UNDOCUMENTED_RECORD_NOT_CERTIFIED |
| 17 | Type B | 2017-10-18 | 2017-11-15 | 202 | 2249 | refused | PREHISTORY_OWN_OUTSIDE ASSIGNMENT_UNDOCUMENTED_RECORD_NOT_CERTIFIED |
| 18 | Type A | 2017-10-30 | 2017-11-27 | 1133 | 1319 | refused | OVERLAP_EXTREME_SCORES |
| 19 | Type B | 2017-11-15 | 2017-12-13 | 130 | 2328 | refused | PREHISTORY_RECORD_BIAS ASSIGNMENT_UNDOCUMENTED_RECORD_NOT_CERTIFIED |
| 20 | Type C | 2017-11-27 | 2017-12-25 | 244 | 2218 | refused | PREHISTORY_RECORD_BIAS ASSIGNMENT_UNDOCUMENTED_RECORD_NOT_CERTIFIED |

What the pipeline measured for the campaigns that reached estimation, those refused at the overlap gate included. `largest shift from one household` is the most the estimate moves when a single household is left out; `smallest tolerance` is the smallest tolerance at which the readout would have been published with the rule unknown.

| campaign | estimate (not published) | pre-history placebo | shifted placebo | treated extreme share | effective controls | largest weight share | largest shift from one household | smallest tolerance undocumented |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 9 | -14.5 [-35.4, 7.5] | 15.2 [-3.6, 33.9] | 21.7 [1.0, 45.5] | 0.00 | 790.95 | 0.01 | 4.90 | 45.54 |
| 10 | -1.3 [-33.1, 32.4] | 48.3 [9.2, 85.0] | -6.5 [-42.5, 26.7] | 0.00 | 505.32 | 0.01 | 5.29 | 84.96 |
| 11 | -5.6 [-29.7, 21.5] | 74.0 [47.5, 103.8] | -8.9 [-33.8, 17.1] | 0.00 | 476.70 | 0.01 | 3.80 | 103.78 |
| 12 | -0.9 [-95.1, 37.3] | 38.2 [-114.5, 87.1] | 3.9 [-29.1, 32.9] | 0.00 | 378.79 | 0.02 | 21.69 | 114.48 |
| 13 | -19.2 [-210.9, 139.4] | -59.3 [-207.4, 30.6] | -72.1 [-257.8, 77.0] | 0.41 | 6.58 | 0.30 | 108.37 | none |
| 14 | -11.8 [-103.8, 30.1] | 38.0 [-47.5, 76.7] | -28.1 [-81.7, 7.8] | 0.00 | 393.66 | 0.01 | 20.60 | 81.65 |
| 16 | -6.8 [-57.9, 31.2] | 18.6 [-32.4, 59.1] | 4.1 [-35.5, 35.1] | 0.00 | 391.97 | 0.02 | 13.26 | 59.09 |
| 17 | -4.5 [-30.4, 22.2] | 47.6 [20.0, 75.9] | 6.1 [-17.6, 30.9] | 0.00 | 497.52 | 0.01 | 4.27 | 75.90 |
| 18 | -114.5 [-238.8, -19.9] | -78.6 [-158.5, 13.9] | -70.1 [-167.5, 4.2] | 0.36 | 27.26 | 0.13 | 46.25 | none |
| 19 | 25.6 [-0.5, 53.5] | 20.5 [-5.8, 46.4] | 14.2 [-10.9, 41.6] | 0.00 | 738.76 | 0.01 | 5.62 | 46.41 |
| 20 | 12.8 [-17.2, 44.1] | 6.2 [-39.1, 47.0] | -38.7 [-78.1, 4.0] | 0.00 | 278.65 | 0.02 | 7.87 | 68.97 |

Median width of one campaign's shifted-placebo interval, among the campaigns that passed the overlap gate: $62.

## The campaigns together

Mean across the campaigns whose data, timing and overlap gates passed, each counting once, with 95% intervals from the household bootstrap. `units` is the number of readouts that fell due, `units with estimates` the number averaged. The rows anchored before the launch are readouts of a campaign that had not been sent; the sets of campaigns differ from row to row. `smallest tolerance` is the smallest tolerance for placebos at which the programme readout would have been published.

| contract | method | window | units | units with estimates | estimate | prehistory placebo | shifted placebo | pre-history minus shifted | programme verdict | smallest tolerance undocumented |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| v1 | weighting | at launch | 24 | 13 | 10.69 [-1.13, 20.10] | 18.54 [1.67, 29.73] | 4.83 [-6.77, 15.67] | 13.70 [-4.89, 27.86] | refused | 29.73 |
| v1 | weighting | anchored 28 days before launch | 27 | 13 | 7.45 [-3.39, 16.16] | 23.16 [12.29, 33.07] | 5.01 [-5.14, 15.23] | 18.15 [2.54, 32.68] | refused | 33.07 |
| v1 | weighting | anchored 56 days before launch | 27 | 12 | 7.51 [-3.42, 18.22] | 37.84 [27.35, 48.51] | 4.02 [-5.78, 14.74] | 33.82 [18.33, 48.18] | refused | 48.51 |
| v1 | regression | at launch | 24 | 13 | 18.04 [11.05, 24.80] | 26.31 [19.54, 32.97] | 12.70 [4.61, 20.49] | 13.61 [2.87, 24.66] | refused | 32.97 |
| v1 | regression | anchored 28 days before launch | 27 | 13 | 14.12 [6.81, 21.26] | 31.26 [24.44, 38.24] | 11.12 [4.18, 18.26] | 20.14 [9.69, 30.69] | refused | 38.24 |
| v1 | regression | anchored 56 days before launch | 27 | 12 | 13.67 [6.41, 21.33] | 43.01 [36.08, 50.27] | 8.16 [1.37, 15.69] | 34.85 [22.99, 45.99] | refused | 50.27 |
| v2 | weighting | at launch | 24 | 9 | -0.79 [-21.87, 10.95] | 34.05 [11.08, 47.83] | -3.58 [-16.07, 7.74] | 37.63 [14.07, 54.60] | refused | 47.83 |
| v2 | weighting | anchored 28 days before launch | 27 | 11 | -5.27 [-16.52, 4.99] | 12.46 [1.43, 22.76] | -2.14 [-12.14, 10.12] | 14.60 [-1.77, 28.10] | refused | 22.76 |
| v2 | weighting | anchored 56 days before launch | 27 | 8 | 6.14 [-5.87, 18.72] | 10.00 [-3.90, 25.00] | 3.13 [-8.36, 15.71] | 6.88 [-12.09, 25.63] | refused | 25.00 |
| v2 | regression | at launch | 24 | 9 | 6.93 [-0.67, 14.04] | 39.90 [31.85, 47.54] | 2.92 [-5.13, 11.08] | 36.98 [24.65, 48.99] | refused | 47.54 |
| v2 | regression | anchored 28 days before launch | 27 | 11 | 1.48 [-6.46, 9.34] | 17.30 [10.28, 24.23] | 2.78 [-4.81, 10.37] | 14.52 [3.55, 25.62] | refused | 24.23 |
| v2 | regression | anchored 56 days before launch | 27 | 8 | 6.27 [-2.46, 15.19] | 13.70 [5.33, 22.74] | 3.63 [-4.46, 12.66] | 10.07 [-1.67, 22.38] | refused | 22.74 |

## The contracts on the same campaigns

The campaigns that passed the data, timing and overlap gates under every contract: 9 10 11 12 14 16 17 19 20. The changes are from the first contract, with intervals from the same bootstrap draws. The pre-history placebo of a longer history is measured on an earlier window, so its change mixes two things: more adjustment and an older window.

| contract | history days | method | campaigns | estimate | prehistory placebo | shifted placebo |
| --- | --- | --- | --- | --- | --- | --- |
| v1 | 56 | regression | 9 | 13.63 [6.30, 20.87] | 21.96 [14.27, 29.79] | 11.04 [3.17, 19.38] |
| v2 | 112 | regression | 9 | 6.93 [-0.67, 14.04] | 39.90 [31.85, 47.54] | 2.92 [-5.13, 11.08] |
| v1 | 56 | weighting | 9 | 5.74 [-9.61, 16.98] | 13.61 [-9.60, 27.27] | 3.42 [-10.69, 14.88] |
| v2 | 112 | weighting | 9 | -0.79 [-21.87, 10.95] | 34.05 [11.08, 47.83] | -3.58 [-16.07, 7.74] |

| contract | method | change in estimate | change in prehistory placebo | change in shifted placebo |
| --- | --- | --- | --- | --- |
| v2 | regression | -6.69 [-9.09, -4.63] | 17.94 [6.62, 28.19] | -8.12 [-10.32, -6.04] |
| v2 | weighting | -6.53 [-18.47, 0.71] | 20.44 [3.45, 36.47] | -7.00 [-12.75, 0.16] |

## How long before the launch the two groups already differed

Contract v1, the campaigns that passed the data, timing and overlap gates. Mean spending per household in each window of 28 days, counted from the launch: 0 is the outcome window, -1 the window before the launch. No adjustment.

All campaigns; the early windows exist only for the campaigns launched late enough:

| window | campaigns | targeted | comparison | gap |
| --- | --- | --- | --- | --- |
| -8 | 5 | 341.02 | 123.42 | 217.60 |
| -7 | 5 | 354.21 | 124.71 | 229.50 |
| -6 | 8 | 350.71 | 126.76 | 223.96 |
| -5 | 9 | 344.87 | 127.90 | 216.97 |
| -4 | 10 | 327.79 | 129.62 | 198.16 |
| -3 | 13 | 324.97 | 132.66 | 192.30 |
| -2 | 13 | 320.50 | 133.80 | 186.69 |
| -1 | 13 | 313.29 | 134.28 | 179.00 |
| 0 | 13 | 318.39 | 135.42 | 182.97 |

The 5 campaigns that have every window, so that the rows compare like with like:

| window | campaigns | targeted | comparison | gap |
| --- | --- | --- | --- | --- |
| -8 | 5 | 341.02 | 123.42 | 217.60 |
| -7 | 5 | 354.21 | 124.71 | 229.50 |
| -6 | 5 | 352.69 | 125.70 | 226.99 |
| -5 | 5 | 352.06 | 126.27 | 225.79 |
| -4 | 5 | 338.18 | 127.84 | 210.34 |
| -3 | 5 | 325.61 | 126.42 | 199.19 |
| -2 | 5 | 323.27 | 125.33 | 197.94 |
| -1 | 5 | 315.30 | 127.03 | 188.27 |
| 0 | 5 | 326.84 | 129.90 | 196.93 |

## Is the pre-history placebo driven by households with no recorded spending in its window?

Contract v1, point estimates, mean across campaigns. The placebo is recomputed on the households already seen in the feed when the pre-history window opened. The feed starts on a fixed day, so this is about recorded purchases, not about when a household became a customer.

| method | households | households seen before window | targeted without spending in window | comparison without spending in window | prehistory placebo | prehistory placebo seen before window |
| --- | --- | --- | --- | --- | --- | --- |
| weighting | 2385.38 | 2095.62 | 0.01 | 0.18 | 18.54 | 18.03 |
| regression | 2385.38 | 2095.62 | 0.01 | 0.18 | 26.31 | 26.15 |

## What a looser tolerance would have published

Contract v1, primary method, the real readouts re-read at other tolerances and with the assignment rule taken as documented. Nothing is recomputed.

| assignment documented | tolerance usd | readouts | published | refused before estimation | refused for overlap | failing prehistory placebo | failing assignment |
| --- | --- | --- | --- | --- | --- | --- | --- |
| no | 5.00 | 24 | 0 | 8 | 3 | 13 | 13 |
| no | 10.00 | 24 | 0 | 8 | 3 | 13 | 13 |
| no | 20.00 | 24 | 0 | 8 | 3 | 13 | 13 |
| no | 30.00 | 24 | 0 | 8 | 3 | 12 | 13 |
| no | 40.00 | 24 | 1 | 8 | 3 | 11 | 10 |
| no | 50.00 | 24 | 3 | 8 | 3 | 10 | 2 |
| no | 75.00 | 24 | 10 | 8 | 3 | 2 | 1 |
| no | 100.00 | 24 | 12 | 8 | 3 | 1 | 0 |
| yes | 5.00 | 24 | 0 | 8 | 3 | 13 | 0 |
| yes | 10.00 | 24 | 0 | 8 | 3 | 13 | 0 |
| yes | 20.00 | 24 | 0 | 8 | 3 | 13 | 0 |
| yes | 30.00 | 24 | 1 | 8 | 3 | 12 | 0 |
| yes | 40.00 | 24 | 2 | 8 | 3 | 11 | 0 |
| yes | 50.00 | 24 | 3 | 8 | 3 | 10 | 0 |
| yes | 75.00 | 24 | 11 | 8 | 3 | 2 | 0 |
| yes | 100.00 | 24 | 12 | 8 | 3 | 1 | 0 |

## Readouts anchored before the launch, at other tolerances

Contract v1, primary method. The campaign had not been sent in these windows. Rows with nothing published are omitted: at tolerances below the first row shown for a window, every readout there is refused.

| window | assignment documented | tolerance usd | units with estimates | published | mean estimate of what was published | largest estimate |
| --- | --- | --- | --- | --- | --- | --- |
| anchored 28 days before launch | no | 40.00 | 13 | 1 | 22.01 [1.23, 45.82] | 22.01 |
| anchored 28 days before launch | no | 50.00 | 13 | 2 | 4.94 [-12.93, 22.74] | 22.01 |
| anchored 28 days before launch | no | 75.00 | 13 | 10 | 6.79 [-3.68, 16.34] | 24.92 |
| anchored 28 days before launch | no | 100.00 | 13 | 12 | 6.90 [-4.38, 15.78] | 24.92 |
| anchored 28 days before launch | yes | 30.00 | 13 | 1 | 22.01 [1.23, 45.82] | 22.01 |
| anchored 28 days before launch | yes | 40.00 | 13 | 1 | 22.01 [1.23, 45.82] | 22.01 |
| anchored 28 days before launch | yes | 50.00 | 13 | 3 | -4.98 [-22.35, 13.45] | 24.81 |
| anchored 28 days before launch | yes | 75.00 | 13 | 10 | 6.79 [-3.68, 16.34] | 24.92 |
| anchored 28 days before launch | yes | 100.00 | 13 | 12 | 6.90 [-4.38, 15.78] | 24.92 |
| anchored 56 days before launch | no | 40.00 | 12 | 1 | -5.63 [-34.51, 21.97] | 5.63 |
| anchored 56 days before launch | no | 50.00 | 12 | 3 | 14.03 [-0.80, 29.19] | 28.38 |
| anchored 56 days before launch | no | 75.00 | 12 | 6 | 10.96 [-2.11, 24.34] | 28.69 |
| anchored 56 days before launch | no | 100.00 | 12 | 11 | 7.43 [-4.01, 18.27] | 47.90 |
| anchored 56 days before launch | yes | 40.00 | 12 | 1 | -5.63 [-34.51, 21.97] | 5.63 |
| anchored 56 days before launch | yes | 50.00 | 12 | 3 | 14.03 [-0.80, 29.19] | 28.38 |
| anchored 56 days before launch | yes | 75.00 | 12 | 6 | 10.96 [-2.11, 24.34] | 28.69 |
| anchored 56 days before launch | yes | 100.00 | 12 | 11 | 7.43 [-4.01, 18.27] | 47.90 |

## Synthetic retailers with a known effect

Every campaign adds $10 to the spending of each targeted household. Each world is drawn with 3 seeds and 12 campaigns per seed, and the counts below add the seeds up. Households per world: 50,000; `random_small` has the size of the real panel. `campaign reach` is the share of households a campaign is sent to. Bootstrap replications per readout: 200. `rule as stated holds` says whether a contract that calls the assignment rule documented, reading spending only, is telling the truth in that world. `programmes published` counts the seeds whose last programme readout was published.

### Primary method (weighting)

| world | households | campaign reach | assignment rule | rule as stated holds | readouts | published | published on own placebos | published on the record | published mean error | published largest error | published intervals holding truth | programmes published | programme mean error |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| random | 50000 | 0.25 | undocumented |  | 36 | 35 | 34 | 1 | -0.19 | 3.68 | 32 | 3 | -0.17 |
| random | 50000 | 0.25 | documented | yes | 36 | 35 | 35 | 0 | -0.19 | 3.68 | 32 | 3 | -0.17 |
| observed | 50000 | 0.25 | undocumented |  | 36 | 0 | 0 | 0 |  |  |  | 0 |  |
| observed | 50000 | 0.25 | documented | yes | 36 | 0 | 0 | 0 |  |  |  | 3 | 0.34 |
| long_run | 50000 | 0.25 | undocumented |  | 36 | 0 | 0 | 0 |  |  |  | 0 |  |
| long_run | 50000 | 0.25 | documented | no | 36 | 0 | 0 | 0 |  |  |  | 0 |  |
| foresight | 50000 | 0.25 | undocumented |  | 36 | 31 | 29 | 2 | 17.94 | 20.62 | 0 | 3 | 18.01 |
| foresight | 50000 | 0.25 | documented | no | 36 | 34 | 32 | 2 | 17.94 | 20.62 | 0 | 3 | 18.01 |
| random_small | 2469 | 0.07 | undocumented |  | 36 | 0 | 0 | 0 |  |  |  | 0 |  |
| random_small | 2469 | 0.07 | documented | yes | 36 | 0 | 0 | 0 |  |  |  | 0 |  |

What was estimated in each world, whatever the gates decided (identical under both rules). Means across seeds; the smallest and largest are over seeds:

| world | true effect | mean estimate | mean error | mean error smallest | mean error largest | mean prehistory placebo | mean shifted placebo | mean standard error |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| random | 10.00 | 9.83 | -0.17 | -0.63 | 0.10 | 0.08 | -0.17 | 1.31 |
| observed | 10.00 | 10.34 | 0.34 | 0.05 | 0.64 | 1.51 | 88.57 | 4.39 |
| long_run | 10.00 | 27.29 | 17.29 | 16.48 | 18.10 | 17.81 | 18.26 | 3.78 |
| foresight | 10.00 | 28.01 | 18.01 | 17.74 | 18.22 | 0.21 | -0.07 | 1.37 |
| random_small | 10.00 | 10.74 | 0.74 | -2.20 | 3.75 | 0.33 | 1.96 | 10.43 |

### Shadow methods

| method | world | households | campaign reach | assignment rule | rule as stated holds | readouts | published | published on own placebos | published on the record | published mean error | published largest error | published intervals holding truth | programmes published | programme mean error |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| regression | random | 50000 | 0.25 | undocumented |  | 36 | 35 | 34 | 1 | -0.20 | 3.58 | 32 | 3 | -0.18 |
| regression | random | 50000 | 0.25 | documented | yes | 36 | 35 | 35 | 0 | -0.20 | 3.58 | 32 | 3 | -0.18 |
| regression | observed | 50000 | 0.25 | undocumented |  | 36 | 0 | 0 | 0 |  |  |  | 0 |  |
| regression | observed | 50000 | 0.25 | documented | yes | 36 | 30 | 27 | 3 | 0.17 | 4.68 | 30 | 3 | 0.42 |
| regression | long_run | 50000 | 0.25 | undocumented |  | 36 | 0 | 0 | 0 |  |  |  | 0 |  |
| regression | long_run | 50000 | 0.25 | documented | no | 36 | 0 | 0 | 0 |  |  |  | 0 |  |
| regression | foresight | 50000 | 0.25 | undocumented |  | 36 | 31 | 29 | 2 | 17.93 | 20.65 | 0 | 3 | 18.00 |
| regression | foresight | 50000 | 0.25 | documented | no | 36 | 33 | 31 | 2 | 17.96 | 20.65 | 0 | 3 | 18.00 |
| regression | random_small | 2469 | 0.07 | undocumented |  | 36 | 0 | 0 | 0 |  |  |  | 0 |  |
| regression | random_small | 2469 | 0.07 | documented | yes | 36 | 0 | 0 | 0 |  |  |  | 0 |  |

What was estimated in each world, whatever the gates decided (identical under both rules). Means across seeds; the smallest and largest are over seeds:

| method | world | true effect | mean estimate | mean error | mean error smallest | mean error largest | mean prehistory placebo | mean shifted placebo | mean standard error |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| regression | random | 10.00 | 9.82 | -0.18 | -0.63 | 0.08 | 0.08 | -0.19 | 1.31 |
| regression | observed | 10.00 | 10.42 | 0.42 | 0.22 | 0.63 | 0.06 | 73.01 | 1.90 |
| regression | long_run | 10.00 | 30.16 | 20.16 | 19.94 | 20.56 | 20.69 | 21.11 | 1.65 |
| regression | foresight | 10.00 | 28.00 | 18.00 | 17.73 | 18.21 | 0.20 | -0.08 | 1.36 |
| regression | random_small | 10.00 | 10.65 | 0.65 | -2.26 | 3.59 | 0.21 | 1.92 | 9.79 |

## How long a record the gates need

Chance that the pooled placebo of K campaigns lies within ±$5 when the method's true mean placebo effect is zero, at the noise of this panel (contract v1). A normal approximation; no simulation. With the rule unknown both placebos have to pass.

| method | placebo | assumed correlation | 13 | 25 | 50 | 100 | 200 | 400 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| weighting | prehistory_placebo | 0.00 | 0.00 | 0.00 | 0.00 | 0.05 | 0.64 | 0.96 |
| weighting | prehistory_placebo | 0.01 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| weighting | prehistory_placebo | 0.03 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| weighting | shifted_placebo | 0.00 | 0.00 | 0.00 | 0.00 | 0.46 | 0.91 | 1.00 |
| weighting | shifted_placebo | 0.01 | 0.00 | 0.00 | 0.00 | 0.00 | 0.12 | 0.27 |
| weighting | shifted_placebo | 0.03 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| regression | prehistory_placebo | 0.00 | 0.00 | 0.03 | 0.61 | 0.96 | 1.00 | 1.00 |
| regression | prehistory_placebo | 0.01 | 0.00 | 0.00 | 0.27 | 0.61 | 0.81 | 0.89 |
| regression | prehistory_placebo | 0.03 | 0.00 | 0.00 | 0.00 | 0.03 | 0.14 | 0.20 |
| regression | shifted_placebo | 0.00 | 0.00 | 0.00 | 0.57 | 0.95 | 1.00 | 1.00 |
| regression | shifted_placebo | 0.01 | 0.00 | 0.00 | 0.23 | 0.57 | 0.78 | 0.87 |
| regression | shifted_placebo | 0.03 | 0.00 | 0.00 | 0.00 | 0.00 | 0.10 | 0.16 |

The same when the true mean placebo effect is $5, the edge of the tolerance:

| method | placebo | assumed correlation | 13 | 25 | 50 | 100 | 200 | 400 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| weighting | prehistory_placebo | 0.000 | 0.000 | 0.000 | 0.000 | 0.007 | 0.025 | 0.025 |
| weighting | prehistory_placebo | 0.010 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| weighting | prehistory_placebo | 0.030 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| weighting | shifted_placebo | 0.000 | 0.000 | 0.000 | 0.000 | 0.024 | 0.025 | 0.025 |
| weighting | shifted_placebo | 0.010 | 0.000 | 0.000 | 0.000 | 0.000 | 0.013 | 0.021 |
| weighting | shifted_placebo | 0.030 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| regression | prehistory_placebo | 0.000 | 0.000 | 0.004 | 0.025 | 0.025 | 0.025 | 0.025 |
| regression | prehistory_placebo | 0.010 | 0.000 | 0.000 | 0.021 | 0.025 | 0.025 | 0.025 |
| regression | prehistory_placebo | 0.030 | 0.000 | 0.000 | 0.000 | 0.004 | 0.015 | 0.018 |
| regression | shifted_placebo | 0.000 | 0.000 | 0.000 | 0.025 | 0.025 | 0.025 | 0.025 |
| regression | shifted_placebo | 0.010 | 0.000 | 0.000 | 0.019 | 0.025 | 0.025 | 0.025 |
| regression | shifted_placebo | 0.030 | 0.000 | 0.000 | 0.000 | 0.000 | 0.011 | 0.016 |

What the calculation is built on, and the fewest campaigns at which the pooled interval is narrow enough to fit inside the tolerance at all, and at which an unbiased method passes four times in five (blank: never):

| method | placebo | assumed correlation | campaigns in registry | standard error of one campaign | measured correlation | campaigns for interval to fit | campaigns for 80 percent |
| --- | --- | --- | --- | --- | --- | --- | --- |
| weighting | prehistory_placebo | 0.000 | 13 | 24.645 | 0.008 | 94 | 256 |
| weighting | prehistory_placebo | 0.010 | 13 | 24.645 | 0.008 | 1386 |  |
| weighting | prehistory_placebo | 0.030 | 13 | 24.645 | 0.008 |  |  |
| weighting | shifted_placebo | 0.000 | 13 | 19.404 | 0.005 | 58 | 159 |
| weighting | shifted_placebo | 0.010 | 13 | 19.404 | 0.005 | 136 |  |
| weighting | shifted_placebo | 0.030 | 13 | 19.404 | 0.005 |  |  |
| regression | prehistory_placebo | 0.000 | 13 | 12.545 | -0.003 | 25 | 67 |
| regression | prehistory_placebo | 0.010 | 13 | 12.545 | -0.003 | 32 | 194 |
| regression | prehistory_placebo | 0.030 | 13 | 12.545 | -0.003 | 86 |  |
| regression | shifted_placebo | 0.000 | 13 | 12.868 | 0.022 | 26 | 70 |
| regression | shifted_placebo | 0.010 | 13 | 12.868 | 0.022 | 34 | 227 |
| regression | shifted_placebo | 0.030 | 13 | 12.868 | 0.022 | 105 |  |

