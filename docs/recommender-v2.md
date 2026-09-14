# Bustag Recommender V2

This branch replaces the original KNN binary filter with a lightweight personal ranking model while keeping the existing SQLite data, crawler, web UI and Docker deployment model.

## What changes

- Logistic Regression with `class_weight=balanced`
- Typed tag features such as `star:...` and `genre:...`
- Fanhao series feature such as `series:ABC`
- Stratified 75/25 hold-out evaluation
- Final production model re-fitted on 100% of explicit user labels
- Time-decay sample weighting (default one-year half-life, 0.25 minimum)
- Continuous 0-1 recommendation score persisted in a separate table
- Recommendation pages sorted by score
- Existing SYSTEM_RATE items are rescored once after retraining; scheduled downloads score only new items
- Explicit USER_RATE rows are never overwritten

## Compatibility and rollback

The V2 production model is stored as one self-contained, atomically replaced bundle:

- `data/model/model_v2.pkl`

It contains the classifier, feature encoder and metrics together. The original KNN files are left untouched. The database gains only a new `recommendation_score` table; existing tables are not altered.

No new Python dependencies are introduced, so the current NAS Docker image can keep Python 3.7 and the existing scikit-learn version.

## Defaults

Defaults are provided through `DEFAULT_CONFIG` and can be overridden in `data/config.ini`:

```ini
[recommend]
threshold = 0.50
half_life_days = 365
min_time_weight = 0.25
```

After deploying V2, open the model page and train once. Until `model_v2.pkl` exists, scheduled recommendation will safely skip scoring.
