import json
import pytest
from bustag.recommender import model
from conftest import work


def labelled(store):
    for i in range(60):
        wid, _, _ = work(store, i, 'a' if i%2 else 'b', 'g' if i%2 else 'h')
        store.feedback(wid, i%2, at='2025-{:02}-{:02}T00:00:00'.format(1+i//28, 1+i%28))


def test_comparison_final_refit_checksum_runtime_and_rollback(store, tmp_path):
    labelled(store)
    directory = str(tmp_path / 'models')
    report = model.train(store, directory)
    assert set(report['comparison']) == {'legacy_knn', 'branch_v2', 'canonical_knn', 'final_lr'}
    assert report['sample_count'] == 60
    assert report['collection_weight'] == 0
    first = store.meta('active_model')
    loaded = model.load(store, directory)
    assert loaded['manifest']['report']['sample_count'] == 60
    assert store.rows('SELECT count(*) AS n FROM v2_recommendation_score')[0]['n'] == 60
    model.train(store, directory)
    model.rollback(store, directory)
    assert store.meta('active_model') == first
    path = tmp_path / 'models' / (first + '.json')
    manifest = json.loads(path.read_text(encoding='utf-8'))
    manifest['runtime']['sklearn'] = 'incompatible'
    path.write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(ValueError, match='runtime mismatch'):
        model.load(store, directory)
    manifest['runtime'] = model.runtime()
    path.write_text(json.dumps(manifest), encoding='utf-8')
    (tmp_path / 'models' / (first + '.pkl')).write_bytes(b'corrupt')
    with pytest.raises(ValueError, match='checksum'):
        model.load(store, directory)


def test_low_samples_fail_without_switching(store, tmp_path):
    work(store, 1)
    with pytest.raises(ValueError, match='40'):
        model.train(store, str(tmp_path / 'models'))
    assert store.meta('active_model') is None


def test_mapping_invalidates_model_and_explicit_not_overwritten(store, tmp_path):
    labelled(store)
    directory = str(tmp_path / 'models')
    model.train(store, directory)
    wid = store.rows('SELECT work_id FROM work_identity LIMIT 1')[0]['work_id']
    original = store.rows('SELECT * FROM explicit_work_feedback')
    tag = store.rows('SELECT tag_id FROM canonical_tag LIMIT 1')[0]['tag_id']
    store.correct_tag(wid, tag, False)
    with pytest.raises(ValueError, match='Mapping changed'):
        model.load(store, directory)
    assert store.rows('SELECT * FROM explicit_work_feedback') == original


def test_stale_scoring_cannot_overwrite_active_generation(store, tmp_path):
    labelled(store)
    directory = str(tmp_path / 'models')
    model.train(store, directory)
    old = model.load(store, directory)
    model.train(store, directory)
    active = store.meta('active_model')
    with pytest.raises(ValueError, match='Stale scoring'):
        model.rescore(store, old)
    assert store.rows('SELECT DISTINCT model_version FROM v2_recommendation_score') == [{'model_version': active}]


def test_mapping_race_rejected_before_publish(store, tmp_path, monkeypatch):
    labelled(store)
    directory = str(tmp_path / 'models')
    model.train(store, directory)
    active = store.meta('active_model')
    atomic = model._atomic_json

    def change_mapping(path, manifest):
        atomic(path, manifest)
        from bustag.recommender.store import Store
        other = Store(store.path)
        wid = other.rows('SELECT work_id FROM work_identity LIMIT 1')[0]['work_id']
        tag = other.rows('SELECT tag_id FROM canonical_tag LIMIT 1')[0]['tag_id']
        other.correct_tag(wid, tag, False)
        other.close()
    monkeypatch.setattr(model, '_atomic_json', change_mapping)
    with pytest.raises(ValueError, match='changed while fitting'):
        model.train(store, directory)
    assert store.meta('active_model') == active
