# data-verify: PASSED

55 passed, 0 blocking, 1 warning(s), 14 skipped, 2 off. Train split: `train`. Splits: `train` 7597961 rows, `val` 1077429 rows, `test` 825321 rows.

| status | check | result |
|---|---|---|
| WARN | `assert.cohort_drives_have_snapshots` | query returned 16 violating row(s) |
| pass | `schema.splits_present` | 3 split(s): train=7597961, val=1077429, test=825321 |
| pass | `schema.roles` | 64 features and 6 role columns present |
| pass | `schema.consistent` | 70 columns, same types in 3 splits |
| pass | `schema.expected` | 70 columns as declared |
| pass | `schema.dtypes` | 3 column types as declared |
| pass | `schema.ranges` | 2 column range(s) respected |
| pass | `schema.allowed` | 1 column(s) within allowed values |
| pass | `schema.not_null` | 6 column(s) complete |
| pass | `schema.unique` | 1 key(s) unique |
| pass | `features.non_finite` | 64 numeric features finite |
| pass | `features.empty` | 64 features have values |
| pass | `features.constant` | 64 features vary |
| pass | `split.group_overlap` | group disjoint across 3 splits |
| pass | `split.rule` | 57293 serial_number value(s) in the split their sha256 rule assigns |
| pass | `temporal.parse` | time ranges train 2016-01-01 00:00:00..2023-12-31 00:00:00, val 2016-01-01 00:00:00..2023-12-31 00:00:00, test 2024-01-01 00:00:00..2025-12-31 00:00:00 |
| pass | `temporal.bounds` | 3 split(s) within bounds |
| pass | `temporal.order` | time order holds: train < test, val < test |
| pass | `duplicates.cross_split` | duplicates within tolerance: train/val 818 rows (0.08%), train/test 61 rows (0.01%), val/test 59 rows (0.01%); no more than different train entities share by chance (0.101%) |
| pass | `duplicates.near_cross_split` | near-duplicates within tolerance: train/val 1698 rows (0.16%), train/test 7 rows (0.00%), val/test 7 rows (0.00%); no more than different train entities share by chance (0.266%) |
| pass | `duplicates.within_split` | 0.06% repeated rows, largest copy count 174 |
| pass | `duplicates.conflicting_labels` | rows whose identical copies carry another label: event 944 (0.01%) <= 1% |
| pass | `target.forbidden_features` | 64 features, none forbidden |
| pass | `target.suspicious_names` | 64 feature names look neutral |
| pass | `target.label_copy` | no feature copies event, duration_days |
| pass | `target.perfect_predictor` | no feature reaches 0.99; strongest: event: model_code AUC 0.707917; duration_days: smart_242_raw \|Spearman\| 0.44829 |
| pass | `target.strong_predictor` | no feature reaches 0.95; strongest: event: model_code AUC 0.707917; duration_days: smart_242_raw \|Spearman\| 0.44829 |
| pass | `target.score_gap` | single-feature scores agree across splits |
| pass | `target.id_like` | no identifier-like features |
| pass | `preprocessing.global_scaling` | no feature is standardised or min-max scaled over evaluation rows (64 numeric features tested) |
| pass | `preprocessing.global_scaling_near` | no feature is nearly standardised over evaluation rows |
| pass | `preprocessing.fitted_levels` | 1 fitted vocabulary(ies) come from training data |
| pass | `labels.valid` | 2 label(s) valid in 3 splits |
| pass | `labels.unseen_classes` | every evaluation class occurs in training |
| pass | `labels.class_presence` | every class present in every split |
| pass | `weights.valid` | weights valid in 3 split(s) |
| pass | `weights.concentration` | top 1% of rows hold 1.8% of the weight |
| pass | `poisoning.outliers` | extreme rows: train 50.15%, held-out 48.77% |
| pass | `poisoning.spurious_association` | no training-only value/class associations found |
| pass | `poisoning.label_consistency` | training labels fit the features as well as evaluation labels (4 comparison(s)) |
| pass | `assert.cohort_serials_unique` | query returned no violating rows |
| pass | `assert.snapshot_split_matches_cohort` | query returned no violating rows |
| pass | `assert.cohort_weights_match_sampling` | query returned no violating rows |
| pass | `assert.one_model_per_drive` | query returned no violating rows |
| pass | `assert.no_snapshot_after_failure` | query returned no violating rows |
| pass | `assert.labels_match_cohort` | query returned no violating rows |
| pass | `assert.train_labels_do_not_see_test_period` | query returned no violating rows |
| pass | `assert.no_visible_failure_labelled_censored` | query returned no violating rows |
| pass | `assert.snapshot_weights_valid` | query returned no violating rows |
| pass | `assert.dense_rows_before_visible_failure` | query returned no violating rows |
| pass | `assert.failures_present_in_every_split` | query returned no violating rows |
| pass | `assert.enough_failures_per_split` | query returned no violating rows |
| pass | `custom.stride_rows_on_stride_days` | 0 rows with weight drive_weight * 7 off the drive's stride day |
| pass | `custom.cohort_split_matches_stable_bucket` | 0 of 57309 cohort drives in the wrong split |
| pass | `custom.features_are_float` | 0 non-float32 feature(s): {} |
| pass | `custom.few_sparse_features` | 0 feature(s) < 1% filled in train: [] |
| skip | `integrity.pins` | no params.pins; pin raw inputs to detect tampering |
| skip | `split.id_unique` | no params.id |
| skip | `split.id_overlap` | no params.id |
| skip | `split.ratios` | no params.split_ratios |
| skip | `split.conservation` | no params.source (the pre-split data) |
| skip | `split.undeclared_group` | params.group is set (split.group_overlap checks it) |
| skip | `temporal.overlap` | time_order / time_bounds are declared and checked instead |
| skip | `temporal.rows_after_outcome` | no params.label_time |
| skip | `temporal.label_after_cutoff` | no params.label_time |
| skip | `temporal.point_in_time` | no params.point_in_time |
| skip | `temporal.undeclared_time` | params.time is set |
| skip | `duplicates.repeated_across_splits` | no key column, or nothing left to compare once the keys are ignored |
| skip | `duplicates.text_cross_split` | no text features (average length >= 30 characters) |
| skip | `drift.unseen_categories` | needs categorical features and two splits |
| off | `labels.shift` | turned off in params.checks |
| off | `drift.features` | turned off in params.checks |

## How to fix

- `assert.cohort_drives_have_snapshots`: Expected only for drives with fewer than stride_days rows in their split window (the offset is random, so weights stay unbiased)
