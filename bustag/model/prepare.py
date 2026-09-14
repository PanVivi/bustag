'''
prepare data for recommender training
'''
import datetime

import numpy as np
import pandas as pd
from sklearn.preprocessing import MultiLabelBinarizer
from sklearn.model_selection import train_test_split

from bustag.spider.db import (
    get_items,
    get_recommendation_candidates,
    RATE_TYPE,
)
from bustag.model.persist import dump_model, load_model
from bustag.util import get_data_path, MODEL_PATH

BINARIZER_PATH = MODEL_PATH + 'label_binarizer_v2.pkl'


def load_data():
    '''
    Load explicit user-labelled items from the database.
    '''
    rate_type = RATE_TYPE.USER_RATE.value
    items, _ = get_items(
        rate_type=rate_type,
        rate_value=None,
        page=None,
    )
    return items


def item_feature_tokens(item):
    '''
    Preserve tag type so an actor name and a genre with identical text
    cannot collapse into the same feature. The fanhao series is also useful.
    '''
    features = set()
    for tag_type, tags in item.tags_dict.items():
        for tag in tags:
            features.add(f'{tag_type}:{tag}')

    series = str(item.fanhao).split('-')[0].strip().upper()
    if series:
        features.add(f'series:{series}')
    return features


def as_dict(item):
    item_rate = getattr(item, 'item_rate', None)
    rate_time = getattr(item_rate, 'rete_time', None)
    return {
        'id': item.fanhao,
        'title': item.title,
        'fanhao': item.fanhao,
        'url': item.url,
        'add_date': item.add_date,
        'tags': item_feature_tokens(item),
        'cover_img_url': item.cover_img_url,
        'target': item.rate_value,
        'rate_time': rate_time,
    }


def build_training_frame():
    items = load_data()
    rows = (as_dict(item) for item in items)
    return pd.DataFrame(
        rows,
        columns=[
            'id', 'title', 'fanhao', 'url', 'add_date', 'tags',
            'cover_img_url', 'target', 'rate_time'
        ],
    )


def fit_vectorizer(df):
    mlb = MultiLabelBinarizer()
    X = mlb.fit_transform(df.tags.values)
    return mlb, X


def split_frame(df):
    y = df['target'].astype(int)
    counts = y.value_counts()
    stratify = y if len(counts) == 2 and int(counts.min()) >= 2 else None
    train_df, test_df = train_test_split(
        df,
        test_size=0.25,
        random_state=42,
        stratify=stratify,
    )
    return train_df, test_df


def time_decay_weights(df, half_life_days=365.0, min_weight=0.25, now=None):
    '''
    Recent explicit feedback matters more, while old preferences are retained.
    A one-year half-life with a 0.25 floor is deliberately conservative.
    '''
    if len(df) == 0:
        return np.array([], dtype=float)

    if half_life_days <= 0:
        return np.ones(len(df), dtype=float)

    now = now or datetime.datetime.now()
    weights = []
    for value in df['rate_time'].values:
        if value is None or pd.isnull(value):
            age_days = 0.0
        else:
            rate_time = pd.to_datetime(value).to_pydatetime()
            age_days = max(0.0, (now - rate_time).total_seconds() / 86400.0)
        weight = 0.5 ** (age_days / float(half_life_days))
        weights.append(max(float(min_weight), float(weight)))
    return np.asarray(weights, dtype=float)


def process_data(df):
    '''
    Backwards-compatible helper used by older tests/tools.
    '''
    mlb, X = fit_vectorizer(df)
    dump_model(get_data_path(BINARIZER_PATH), mlb)
    y = df[['target']]
    return X, y


def split_data(X, y):
    y_series = y.iloc[:, 0] if hasattr(y, 'iloc') else y
    counts = pd.Series(y_series).value_counts()
    stratify = y_series if len(counts) == 2 and int(counts.min()) >= 2 else None
    return train_test_split(
        X, y, test_size=0.25, random_state=42, stratify=stratify
    )


def prepare_data():
    df = build_training_frame()
    X, y = process_data(df)
    return split_data(X, y)


def build_predict_frame():
    items = get_recommendation_candidates()
    rows = (as_dict(item) for item in items)
    df = pd.DataFrame(rows, columns=['id', 'tags'])
    if len(df):
        df.set_index('id', inplace=True)
    return df


def prepare_predict_data():
    df = build_predict_frame()
    if len(df) == 0:
        return np.array([]), np.empty((0, 0), dtype=int)

    mlb = load_model(get_data_path(BINARIZER_PATH))
    X = mlb.transform(df.tags.values)
    return df.index.values, X
