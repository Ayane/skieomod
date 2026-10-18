"""Local operator commands; requires access to the repository data directory."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from repository.server.app import Repository
from tools.custom_packages import inspect_package


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    seed = commands.add_parser('import', help='publish a validated package on behalf of the specified Steam publisher')
    seed.add_argument('archive', type=Path)
    seed.add_argument('--owner', required=True)
    commands.add_parser('status', help='report storage and package counts')
    commands.add_parser('refresh-profiles', help='refresh cached public Steam names and avatars')
    args = parser.parse_args()
    repo = Repository()
    if args.command == 'import':
        import re, time
        if not re.fullmatch(r'7656119[0-9]{10}', args.owner):
            parser.error('--owner must be a SteamID64')
        kind, manifest, _ = inspect_package(args.archive)
        with repo.db() as db:
            db.execute('INSERT OR IGNORE INTO users VALUES (?,?)', (args.owner, int(time.time())))
        with args.archive.open('rb') as source:
            result = repo.publish({'CONTENT_LENGTH': str(args.archive.stat().st_size), 'wsgi.input': source}, kind, owner=args.owner)
        print(json.dumps(result, ensure_ascii=False))
    elif args.command == 'refresh-profiles':
        with repo.db() as db:
            identifiers = [row['id'] for row in db.execute('SELECT id FROM users')]
        for identifier in identifiers:
            print(json.dumps(repo.refresh_profile(identifier, force=True), ensure_ascii=False))
    else:
        with repo.db() as db:
            print(json.dumps({'packages': db.execute('SELECT count(*) FROM packages').fetchone()[0],
                'releases': db.execute('SELECT count(*) FROM releases').fetchone()[0],
                'archive_bytes': db.execute('SELECT coalesce(sum(size),0) FROM releases').fetchone()[0],
                'storage_limit': repo.storage_limit}, indent=2))


if __name__ == '__main__':
    main()
