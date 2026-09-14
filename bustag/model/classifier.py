''' 
create classifier model and predict
'''
from sklearn.metrics import confusion_matrix
from sklearn.linear_model import LogisticRegression

from bustag.model.prepare import (
    build_training_frame,
    fit_vectorizer,
    split_frame,
    time_decay_weights,
    prepare_predict_data,
)
from bustag.model.persist import load_model, dump_model
from bustag.spider.db import RATE_TYPE, RATE_VALUE, ItemRate, RecommendationScore
from bustag.util import logger, get_data_path, MODEL_PATH, APP_CONFIG

MODEL_FILE = MODEL_PATH + 'model_v2.pkl'
MODEL_VERSION = 2
MIN_TRAIN_NUM = 200
MIN_CLASS_NUM = 10


def _config_float(key, default):
    try:
        return float(APP_CONFIG.get(key, default))
    except (TypeError, ValueError):
        return float(default)


def _threshold():
    value = _config_float('recommend.threshold', 0.50)
    return min(0.95, max(0.05, value))


def _half_life_days():
    return max(1.0, _config_float('recommend.half_life_days', 365.0))


def _min_time_weight():
    value = _config_float('recommend.min_time_weight', 0.25)
    return min(1.0, max(0.05, value))


def load():
    model_data = load_model(get_data_path(MODEL_FILE))
    return model_data


def create_model():
    # Binary tag features work well with a regularized linear model.
    # class_weight balances uneven like/dislike histories without new dependencies.
    return LogisticRegression(
        solver='liblinear',
        class_weight='balanced',
        max_iter=1000,
        random_state=42,
    )


def predict_scores(X_test):
    model, _ = load()
    return model.predict_proba(X_test)[:, 1]


def predict(X_test):
    scores = predict_scores(X_test)
    threshold = _threshold()
    return (scores >= threshold).astype(int)


def _check_training_data(df):
    total = len(df)
    if total < MIN_TRAIN_NUM:
        raise ValueError(
            f'训练数据不足, 无法训练模型. 需要{MIN_TRAIN_NUM}, 当前{total}'
        )
    counts = df['target'].astype(int).value_counts()
    if len(counts) < 2:
        raise ValueError('训练数据必须同时包含喜欢和不喜欢')
    if int(counts.min()) < MIN_CLASS_NUM:
        raise ValueError(
            f'喜欢和不喜欢至少各需要{MIN_CLASS_NUM}条, 当前较少一类只有{int(counts.min())}条'
        )


def train():
    df = build_training_frame()
    _check_training_data(df)

    # 1) Hold-out validation with stratified split.
    train_df, test_df = split_frame(df)
    eval_mlb, X_train = fit_vectorizer(train_df)
    X_test = eval_mlb.transform(test_df.tags.values)
    y_train = train_df['target'].astype(int).values
    y_test = test_df['target'].astype(int).values
    train_weights = time_decay_weights(
        train_df,
        half_life_days=_half_life_days(),
        min_weight=_min_time_weight(),
    )

    eval_model = create_model()
    eval_model.fit(X_train, y_train, sample_weight=train_weights)
    y_pred = (eval_model.predict_proba(X_test)[:, 1] >= _threshold()).astype(int)
    scores = evaluate(y_test, y_pred)

    # 2) Production model is then re-fit on 100% of user-labelled data.
    final_mlb, X_all = fit_vectorizer(df)
    y_all = df['target'].astype(int).values
    all_weights = time_decay_weights(
        df,
        half_life_days=_half_life_days(),
        min_weight=_min_time_weight(),
    )
    model = create_model()
    model.fit(X_all, y_all, sample_weight=all_weights)

    # Save v2 artefacts separately so the old KNN model remains available for rollback.
    from bustag.model.prepare import BINARIZER_PATH
    dump_model(get_data_path(BINARIZER_PATH), final_mlb)

    scores.update({
        'model_version': MODEL_VERSION,
        'algorithm': 'Logistic Regression',
        'samples': int(len(df)),
        'features': int(len(final_mlb.classes_)),
        'threshold': float('{:.2f}'.format(_threshold())),
        'half_life_days': int(_half_life_days()),
    })
    models_data = (model, scores)
    dump_model(get_data_path(MODEL_FILE), models_data)
    logger.warning(
        'recommender v2 trained: samples=%s features=%s threshold=%s',
        scores['samples'], scores['features'], scores['threshold']
    )
    return models_data


def evaluate(y_test, y_pred):
    tn, fp, fn, tp = confusion_matrix(y_test, y_pred, labels=[0, 1]).ravel()
    precision = tp / float(tp + fp) if (tp + fp) else 0.0
    recall = tp / float(tp + fn) if (tp + fn) else 0.0
    f1 = (
        2.0 * precision * recall / (precision + recall)
        if (precision + recall) else 0.0
    )
    logger.info(f'tp: {tp}, fp: {fp}')
    logger.info(f'fn: {fn}, tn: {tn}')
    logger.info(f'precision_score: {precision}')
    logger.info(f'recall_score: {recall}')
    logger.info(f'f1_score: {f1}')
    return {
        'precision': float('{:.2f}'.format(precision)),
        'recall': float('{:.2f}'.format(recall)),
        'f1': float('{:.2f}'.format(f1)),
    }


def recommend():
    '''
    Score all unrated/system-rated items and persist both the binary result
    and the continuous interest score used for ranking.
    '''
    ids, X = prepare_predict_data()
    if len(X) == 0:
        logger.warning('no data for recommend')
        return 0, 0

    threshold = _threshold()
    scores = predict_scores(X)
    total = len(ids)
    count = 0

    for fanhao, score in zip(ids, scores):
        score = float(score)
        rate_value = (
            RATE_VALUE.LIKE.value if score >= threshold
            else RATE_VALUE.DISLIKE.value
        )
        if rate_value == RATE_VALUE.LIKE.value:
            count += 1

        item_rate = ItemRate.get_by_fanhao(fanhao)
        if item_rate is None:
            ItemRate.saveit(RATE_TYPE.SYSTEM_RATE, rate_value, fanhao)
        elif item_rate.rate_type == RATE_TYPE.SYSTEM_RATE.value:
            item_rate.rate_value = rate_value
            item_rate.save()
        else:
            # Safety: never overwrite an explicit user judgement.
            continue

        RecommendationScore.saveit(fanhao, score)

    logger.warning(
        f'predicted {total} items, recommended {count}, threshold={threshold:.2f}'
    )
    return total, count
