import datetime
from types import SimpleNamespace

import pandas as pd

from bustag.model.prepare import item_feature_tokens, time_decay_weights


def test_feature_tokens_preserve_type_and_series():
    item = SimpleNamespace(
        fanhao='ABC-123',
        tags_dict={
            'star': ['Alice'],
            'genre': ['Alice', 'Drama'],
        },
    )
    features = item_feature_tokens(item)
    assert 'star:Alice' in features
    assert 'genre:Alice' in features
    assert 'genre:Drama' in features
    assert 'series:ABC' in features


def test_time_decay_prefers_recent_feedback():
    now = datetime.datetime(2026, 1, 1)
    df = pd.DataFrame({
        'rate_time': [
            now,
            now - datetime.timedelta(days=365),
            now - datetime.timedelta(days=3650),
        ]
    })
    weights = time_decay_weights(
        df, half_life_days=365, min_weight=0.25, now=now
    )
    assert weights[0] == 1.0
    assert 0.49 <= weights[1] <= 0.51
    assert weights[2] == 0.25
