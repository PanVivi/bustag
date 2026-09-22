"""Generate a public-safe synthetic diagnostic; never use a user's database."""
import json
import tempfile
from pathlib import Path

from bustag.recommender.model import train, runtime
from bustag.recommender.store import Store


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        store = Store(root / 'synthetic.db')
        try:
            store.migrate(root / 'empty-backup.db')
            for i in range(60):
                with store.transaction():
                    work = store.work('synthetic', str(i), 'Generated test work', 'SYN-{:03}'.format(i))
                    store.add_actor(work, 'synthetic', 'actor-' + str(i % 2), 'Synthetic actor')
                    store.add_tag(work, 'synthetic', 'genre', 'tag-' + str(i % 2), 'Synthetic tag ' + str(i % 2))
                store.feedback(work, i % 2, at='2025-{:02}-{:02}T00:00:00'.format(1+i//28, 1+i%28))
            result = {'synthetic_only': True, 'personal_model_acceptance': False,
                      'purpose': 'Pipeline smoke diagnostic; generated separable labels do not measure personal recommendation quality.',
                      'runtime': runtime(), 'report': train(store, str(root / 'models'))}
            print(json.dumps(result, ensure_ascii=False, indent=2))
        finally:
            store.close()


if __name__ == '__main__':
    main()
