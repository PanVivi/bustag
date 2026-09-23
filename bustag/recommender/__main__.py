"""Explicit local maintenance commands; no deployment or production connection."""
import argparse
import json

from .store import Store


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', required=True)
    parser.add_argument('--models', default='data/model/final-v2')
    commands = parser.add_subparsers(dest='command', required=True)
    migration = commands.add_parser('migrate')
    migration.add_argument('--backup', required=True)
    for name in ('stats', 'sync-legacy', 'train', 'rescore', 'rollback-model', 'sync-emby', 'reset-job'):
        commands.add_parser(name)
    args = parser.parse_args()
    store = Store(args.db)
    try:
        if args.command == 'migrate':
            result = store.migrate(args.backup)
        elif not store.enabled():
            raise ValueError('Run explicit backup + migration first')
        elif args.command == 'stats':
            result = store.statistics()
        elif args.command == 'sync-legacy':
            result = store.import_legacy()
        elif args.command == 'sync-emby':
            from .emby import Emby, sync
            result = sync(store, Emby.from_environment())
        elif args.command == 'reset-job':
            with store.transaction():
                store.conn.execute("UPDATE v2_job SET state='interrupted',message='operator reset after stopping worker' WHERE id=1")
            result = {'status': 'reset; only run when old worker is stopped'}
        else:
            from . import model
            if args.command == 'train':
                result = model.train(store, args.models)
            elif args.command == 'rescore':
                with store.transaction():
                    result = model.rescore(store, model.load(store, args.models))
            else:
                result = model.rollback(store, args.models)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        store.close()


if __name__ == '__main__':
    main()
