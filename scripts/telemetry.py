#!/usr/bin/env python3
"""Project-scoped cutover. Never resets groups, acknowledges or trims events."""
import argparse
import contextlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
LEGACY_SHA = '4d83b0382b838e0a6f63c37edd365e6d761b2ca1'


def run(argv, **kwargs):
    return subprocess.run(argv, check=True, text=True, capture_output=True, **kwargs).stdout.strip()


@contextlib.contextmanager
def lock(project):
    path = Path(tempfile.gettempdir()) / f'vulture-telemetry-{project}.lock'
    with path.open('a+b') as file:
        try:
            if os.name == 'nt':
                import msvcrt
                file.seek(0)
                file.write(b'0')
                file.flush()
                file.seek(0)
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError('Another operator holds this project lock') from exc
        yield


class Operation:
    def __init__(self, project, disposable=False):
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]*', project):
            raise ValueError('Invalid project name')
        self.project = project
        self.disposable = disposable
        self.env = os.environ.copy()
        if disposable:
            if not project.startswith('vulture-qa-'):
                raise ValueError('Disposable project must start with vulture-qa-')
            self.env['DATABASE_URL'] = ''
            self.env.setdefault('PERSIST_SOURCE_ID', f'{project}-redis-history')
        self.args = ['docker', 'compose', '--project-name', project, '--env-file', str(ROOT / '.env') if not disposable and (ROOT / '.env').exists() else os.devnull, '-f', str(ROOT / 'docker-compose.yml')]
        if disposable:
            self.args += ['-f', str(ROOT / 'docker-compose.test.yml')]

    def compose(self, *args):
        return run(self.args + list(args), cwd=ROOT, env=self.env)

    def containers(self):
        ids = run(['docker', 'ps', '-aq', '--filter', f'label=com.docker.compose.project={self.project}']).split()
        return json.loads(run(['docker', 'inspect', *ids])) if ids else []

    def writers(self):
        result = []
        for item in self.containers():
            service = item['Config']['Labels'].get('com.docker.compose.service', '')
            cmd = item['Config'].get('Cmd') or []
            if item['State']['Running'] and (service in ('recepcao-persist', 'persistencia') or 'persist' in cmd or 'consume' in cmd):
                result.append((service, item['Id']))
        return result

    def probe(self):
        # Only public settings and the package startup schema guard. No migrations.
        program = '''import asyncio,json
import asyncpg
from redis.asyncio import Redis
from station_persist.config import Settings
from station_persist.persistence import validate_storage_schema
async def main():
 s=Settings(); assert s.source_id, 'PERSIST_SOURCE_ID required'
 r=Redis.from_url(s.redis_url.get_secret_value(),decode_responses=True)
 c=await asyncpg.connect(s.database_url.get_secret_value(),timeout=10)
 try:
  async with c.transaction(readonly=True): await validate_storage_schema(c)
  assert await r.ping()
  names=await r.exists(s.stream)
  groups=await r.xinfo_groups(s.stream) if names else []
  bound=await r.get('vulture:source:'+s.stream+':'+s.group)
  assert bound in (None,s.source_id), 'Redis history belongs to another SOURCE_ID'
  print(json.dumps(dict(stream=s.stream,group=s.group,source_id=s.source_id,groups=groups,redis_time=await r.time())))
 finally: await c.close(); await r.aclose()
asyncio.run(main())'''
        return json.loads(self.compose('run', '--rm', '--no-deps', '-T', '--entrypoint', 'python', 'persistencia', '-c', program).splitlines()[-1])

    def preflight(self):
        config = json.loads(self.compose('config', '--format', 'json'))
        receiver = config['services']['recepcao']['environment']
        worker = config['services']['persistencia']['environment']
        if any('DATABASE' in key for key in receiver):
            raise RuntimeError('Reception must not receive PostgreSQL configuration')
        required = json.loads(receiver['INGEST_RETENTION_REQUIRED_GROUPS'])
        if worker['PERSIST_GROUP'] not in required:
            raise RuntimeError('Retention required groups omit the configured treatment group')
        if receiver['INGEST_REDIS_STREAM'] != worker['PERSIST_STREAM']:
            raise RuntimeError('Reception and treatment Streams differ')
        snapshot = self.probe()
        # Inventory excludes Env: it may contain credentials.
        snapshot['infra_revision'] = run(['git', 'rev-parse', 'HEAD'], cwd=ROOT)
        snapshot['gitlinks'] = run(['git', 'submodule', 'status'], cwd=ROOT).splitlines()
        snapshot['containers'] = [dict(service=i['Config']['Labels'].get('com.docker.compose.service'), image=i['Image'], running=i['State']['Running'], mounts=[dict(type=m['Type'], name=m.get('Name'), destination=m['Destination']) for m in i['Mounts']]) for i in self.containers()]
        snapshot['writers'] = [service for service, _ in self.writers()]
        return snapshot

    def activate(self):
        self.compose('build', 'persistencia')
        snapshot = self.preflight()
        # Orphan legacy containers from the previous Compose are included.
        for _, cid in self.writers():
            run(['docker', 'stop', '--time', '45', cid])
        if self.writers():
            raise RuntimeError('A writer is still running; activation aborted')
        program = '''import asyncio
from redis.asyncio import Redis
from station_persist.config import Settings
async def main():
 s=Settings(); r=Redis.from_url(s.redis_url.get_secret_value(),decode_responses=True)
 try:
  key='vulture:source:'+s.stream+':'+s.group
  await r.set(key,s.source_id,nx=True)
  assert await r.get(key)==s.source_id, 'SOURCE_ID mismatch'
 finally: await r.aclose()
asyncio.run(main())'''
        self.compose('run', '--rm', '--no-deps', '-T', '--entrypoint', 'python', 'persistencia', '-c', program)
        self.compose('up', '-d', '--no-deps', '--wait', '--wait-timeout', '120', 'persistencia')
        snapshot['after'] = json.loads(self.compose('exec', '-T', 'persistencia', 'python', '-m', 'station_persist', 'status').splitlines()[-1])
        return snapshot

    def pause(self):
        for service, cid in self.writers():
            if service != 'persistencia':
                raise RuntimeError('Unexpected legacy writer: inspect before pausing')
            run(['docker', 'stop', '--time', '45', cid])
        return dict(project=self.project, writers=[s for s, _ in self.writers()], action='paused; ingress, Redis, PEL and PostgreSQL preserved')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['preflight', 'activate', 'pause', 'build-legacy'])
    parser.add_argument('--project', required=True)
    parser.add_argument('--test', action='store_true', help='Disposable internal PostgreSQL')
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    operation = Operation(args.project, args.test)
    with lock(args.project):
        if args.action == 'build-legacy':
            if not args.test:
                parser.error('Legacy image is restricted to a disposable rehearsal')
            archive = subprocess.check_output(['git', '-C', str(ROOT / 'services/API-DSM-4-RECEPCAO-DADOS'), 'archive', LEGACY_SHA])
            subprocess.run(['docker', 'build', '-t', f'vulture-recepcao-legacy:{LEGACY_SHA}', '-'], input=archive, check=True)
            result = dict(legacy_revision=LEGACY_SHA)
        else:
            result = getattr(operation, args.action)()
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result))


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        # Do not echo Compose output/configuration or DSNs on operational errors.
        print(f'Operation failed ({type(exc).__name__}); no destructive recovery was attempted.', file=sys.stderr)
        sys.exit(1)
