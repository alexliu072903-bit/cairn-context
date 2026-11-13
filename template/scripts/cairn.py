#!/usr/bin/env python3
"""Cairn's local, standard-library-only navigation and decision mutation boundary."""
import argparse
import contextlib
import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile
from pathlib import Path


def load(name):
    spec = importlib.util.spec_from_file_location('cairn_' + name, Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# An installed CLI must not write import caches into the decision repository.
if __name__ == '__main__':
    sys.dont_write_bytecode = True


reader = load('read')
validator = reader.load_validate()
indexer = load('index')
ID = re.compile(r'^[a-z0-9][a-z0-9-]*$')
BRIEF_KIND = 'cairn.hot-context'
BRIEF_VERSION = 1
SHA256 = re.compile(r'[0-9a-f]{64}')


class Refusal(Exception):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.result = dict(schema=1, ok=False, code=code, message=message, **details)


def identifier(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise Refusal('INVALID_ARGUMENTS', 'Use a lowercase id containing letters, digits and hyphens.')
    return value


def decision_id(value):
    # Older repositories may contain ids that the validator warns about but accepts.
    if not isinstance(value, str) or not value or value in ('.', '..') or any(c in value for c in '/\\\0') or any(ord(c) < 32 for c in value):
        raise Refusal('INVALID_ARGUMENTS', 'A decision id must name exactly one file, not a path.')
    return value


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def fingerprint(files):
    return digest(json.dumps(files, sort_keys=True, ensure_ascii=True))


def safe(root, path):
    if not reader.safe_path(path, root) or (path.is_file() and path.stat().st_nlink > 1):
        raise Refusal('UNSAFE_PATH', 'Linked or redirected paths are not supported.')
    return path


def project_path(root, project):
    path = safe(root, root / 'projects' / identifier(project))
    if not path.is_dir():
        raise Refusal('PROJECT_NOT_FOUND', 'Select an existing project; this command does not create projects.')
    return path


def read_files(root, project):
    directory = safe(root, project_path(root, project) / 'decisions')
    if not directory.is_dir():
        return {}
    return {p.name: safe(root, p).read_bytes().decode('utf-8', errors='surrogateescape') for p in sorted(directory.glob('*.md'))}


def pending_path(root, project):
    return safe(root, project_path(root, project) / '.cairn' / 'pending.json')


def snapshot(root, project, *, fallback_title=True):
    pending = pending_path(root, project)
    if pending.exists():
        raise Refusal('RECOVERY_REQUIRED', 'Finish the pending write before reading this project.')
    before = read_files(root, project)
    data, _ = reader.read_repository(validator, root, [project], include_revisions=True,
                                     fallback_title=fallback_title)
    if pending.exists() or read_files(root, project) != before:
        raise Refusal('REVISION_CONFLICT', 'Project changed while reading; retry the read.')
    return data, before, fingerprint(before)


def checked_content(project, files):
    # Validate the proposed whole project without exposing partial writes to readers.
    with tempfile.TemporaryDirectory(prefix='cairn-validate-') as tmp:
        root = Path(tmp)
        folder = root / 'projects' / project / 'decisions'
        folder.mkdir(parents=True)
        for name, text in files.items():
            decision_id(name.removesuffix('.md'))
            (folder / name).write_bytes(text.encode('utf-8'))
        data, _ = reader.read_repository(validator, root, [project])
    if data['errors']:
        raise Refusal('VALIDATION_FAILED', 'Decision fields or history are invalid; no proposed changes committed.',
                      errors=data['errors'], warnings=data['warnings'])
    return data


def atomic_text(root, path, text):
    safe(root, path)
    fd, name = tempfile.mkstemp(prefix='.cairn-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        safe(root, path)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def save_json(root, path, value):
    atomic_text(root, path, json.dumps(value, ensure_ascii=True, indent=2) + '\n')


@contextlib.contextmanager
def project_lock(root, project):
    state = safe(root, project_path(root, project) / '.cairn')
    state.mkdir(exist_ok=True)
    # Serialize writers across projects too: correction feedback is repository-wide.
    locks = safe(root, root / '.cairn')
    locks.mkdir(exist_ok=True)
    path = safe(root, locks / 'writer.lock')
    if (locks / 'sync.lock').exists():
        raise Refusal('BUSY', 'Git synchronization is in progress; retry when it finishes.')
    with path.open('a+b') as stream:
        try:
            if os.name == 'nt':
                import msvcrt
                if path.stat().st_size == 0:
                    stream.write(b'0')
                    stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise Refusal('BUSY', 'Another Cairn writer owns this project; retry later.')
        try:
            yield state
        finally:
            if os.name == 'nt':
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def status_field(content, status):
    match = re.match(r"\A(\ufeff?---\r?\n)(.*?)(\r?\n---(?:\r?\n|$))", content, re.S)
    if not match:
        raise Refusal('VALIDATION_FAILED', 'Cannot find the decision frontmatter.')
    head = re.sub(r'^status:[^\r\n]*', 'status: ' + status, match[2], flags=re.M)
    return match[1] + head + match[3] + content[match.end():]


def plan(root, request):
    project = identifier(request.get('project'))
    id_ = decision_id(request.get('id'))
    action = request.get('action')
    if action not in ('create', 'supersede', 'revoke', 'correct'):
        raise Refusal('INVALID_ARGUMENTS', 'action must be create, supersede, revoke or correct.')
    if action in ('create', 'supersede'):
        identifier(id_)
    data, before, _ = snapshot(root, project)
    if data['errors']:
        raise Refusal('VALIDATION_FAILED', 'Repair existing project errors before a new write.', errors=data['errors'])
    records = {record['id']: record for record in data['projects'][0]['decisions']}
    after = dict(before)
    expected = request.get('expected', {})
    if not isinstance(expected, dict):
        raise Refusal('INVALID_ARGUMENTS', 'expected must map decision ids to revisions.')
    target = id_ + '.md'
    if action in ('create', 'supersede') and target in before:
        raise Refusal('ALREADY_EXISTS', 'This decision id already exists; read it before changing it.')
    if action == 'revoke':
        if id_ not in records or records[id_]['status'] != 'valid':
            raise Refusal('INVALID_STATE', 'Only an existing valid decision can be revoked.')
        after[target] = status_field(before[target], 'revoked')
    else:
        content = request.get('content')
        if not isinstance(content, str) or not content.strip():
            raise Refusal('INVALID_ARGUMENTS', 'content must be the complete Decision Markdown.')
        after[target] = content
    if action == 'supersede':
        if not expected:
            raise Refusal('INVALID_ARGUMENTS', 'Supply expected revisions for every decision being replaced.')
        for old in expected:
            decision_id(old)
            if old not in records or records[old]['status'] != 'valid':
                raise Refusal('INVALID_STATE', 'Only valid decisions can be superseded.')
            after[old + '.md'] = status_field(before[old + '.md'], 'superseded')
    required = set(expected) if action == 'supersede' else ({id_} if action in ('correct', 'revoke') else set())
    if set(expected) != required or any(records.get(key, {}).get('revision') != expected[key] for key in required):
        raise Refusal('REVISION_CONFLICT', 'Expected revisions do not match; read the affected decisions again.')
    if action in ('correct', 'revoke') and id_ not in records:
        raise Refusal('NOT_FOUND', 'Read an existing decision before changing it.')
    result = checked_content(project, after)
    updated = next((r for r in result['projects'][0]['decisions'] if r['id'] == id_), None)
    if not updated:
        raise Refusal('VALIDATION_FAILED', 'The target decision was not produced.')
    if action in ('create', 'supersede'):
        if updated['status'] != 'valid' or set(updated['supersedes']) != required or updated['superseded_by']:
            raise Refusal('INVALID_STATE', 'New decisions must be valid with exactly the specified supersedes links.')
    if action == 'correct':
        old = records[id_]
        if any(old[key] != updated[key] for key in ('status', 'supersedes', 'superseded_by', 'decided_by', 'decided_at')):
            raise Refusal('INVALID_STATE', 'Correction preserves status, history and original decision attribution; use supersede/revoke for lifecycle changes.')
    return before, after, result['warnings']


def refresh_index(root, project):
    path = project_path(root, project)
    # Pending marker is normally respected by readers. Build from a clean snapshot,
    # and publish only after every decision file is at the accepted revision.
    files = read_files(root, project)
    with tempfile.TemporaryDirectory(prefix='cairn-index-') as tmp:
        staged = Path(tmp) / 'projects' / project
        (staged / 'decisions').mkdir(parents=True)
        for name, text in files.items():
            (staged / 'decisions' / name).write_bytes(text.encode('utf-8'))
        content, skipped, _ = indexer.render_project(validator, staged)
    if skipped:
        raise Refusal('VALIDATION_FAILED', 'Cannot publish an index containing invalid decisions.')
    atomic_text(root, path / 'decisions-index.md', content)


def resume(root, project, state, journal, receipt_path):
    before, after = journal['before'], journal['after']
    for files in (before, after):
        if not isinstance(files, dict):
            raise Refusal('INVALID_JOURNAL', 'Journal requires manual inspection.')
        for name, content in files.items():
            if not isinstance(name, str) or not name.endswith('.md') or not isinstance(content, str):
                raise Refusal('INVALID_JOURNAL', 'Journal requires manual inspection.')
            decision_id(name[:-3])
    feedback = journal.get('feedback')
    feedback_path = safe(root, root / 'protocol/benchmark/feedback.md')
    if feedback:
        actual = feedback_path.read_bytes().decode('utf-8') if feedback_path.exists() else ''
        if actual not in (feedback['before'], feedback['after']):
            raise Refusal('RECOVERY_CONFLICT', 'Correction feedback changed; inspect before recovering.')
    current = read_files(root, project)
    if set(current) - set(after) or any(current.get(name) not in (before.get(name), text) for name, text in after.items()):
        raise Refusal('RECOVERY_CONFLICT', 'Files changed outside this transaction; preserve them and inspect before recovering.')
    checked_content(project, after)
    directory = safe(root, project_path(root, project) / 'decisions')
    directory.mkdir(exist_ok=True)
    changed = [name for name in after if before.get(name) != after[name]]
    for name in changed:
        # Refuse external edits rather than overwriting them on a retry.
        live = read_files(root, project)
        if live != current:
            raise Refusal('RECOVERY_CONFLICT', 'Project changed during commit; no further files were written.')
        if current.get(name) != after[name]:
            atomic_text(root, directory / name, after[name])
            current[name] = after[name]
    if read_files(root, project) != after:
        raise Refusal('RECOVERY_CONFLICT', 'Project changed during commit; inspect before recovering.')
    if feedback:
        feedback_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_text(root, feedback_path, feedback['after'])
    journal['phase'] = 'index_pending'
    save_json(root, receipt_path, journal)
    refresh_index(root, project)
    if read_files(root, project) != after:
        raise Refusal('RECOVERY_CONFLICT', 'Project changed during index refresh; inspect before recovering.')
    result = dict(schema=1, ok=True, code='WRITTEN', request_id=journal['request_id'],
                  project=project, action=journal['action'], index='current',
                  records=[{'id': name[:-3], 'file': 'projects/%s/decisions/%s' % (project, name),
                            'revision': digest(after[name])} for name in changed], warnings=journal['warnings'])
    journal.update(phase='complete', result=result)
    save_json(root, receipt_path, journal)
    pending_path(root, project).unlink()
    return result


def write(root, request):
    if not isinstance(request, dict):
        raise Refusal('INVALID_ARGUMENTS', 'Supply one JSON object on stdin.')
    project = identifier(request.get('project'))
    request_id = identifier(request.get('request_id'))
    if request.get('confirmed') is not True or not isinstance(request.get('source'), str) or not request['source'].strip():
        raise Refusal('CONFIRMATION_REQUIRED', 'The Agent must establish explicit user intent and supply its source; no write made.')
    request_hash = fingerprint(request)
    with project_lock(root, project) as state:
        receipts = safe(root, state / 'transactions')
        receipts.mkdir(exist_ok=True)
        receipt_path = safe(root, receipts / (request_id + '.json'))
        pending = pending_path(root, project)
        if pending.exists():
            active = json.loads(pending.read_text(encoding='utf-8'))
            if active['request_id'] != request_id:
                raise Refusal('RECOVERY_REQUIRED', 'Recover the earlier request before starting another.', request_id=active['request_id'])
        if receipt_path.exists():
            journal = json.loads(receipt_path.read_text(encoding='utf-8'))
            if journal['request_hash'] != request_hash:
                raise Refusal('REQUEST_CONFLICT', 'The request id was already used for different content.')
            if journal['phase'] == 'complete':
                if pending.exists():
                    pending.unlink()
                return journal['result']
            if pending.exists():
                return resume(root, project, state, journal, receipt_path)
            if journal['phase'] != 'prepared':
                raise Refusal('INVALID_JOURNAL', 'A started write is missing its pending marker; inspect before recovering.')
            # No marker means the previous attempt never started changing records.
            # Revalidate the request and refresh its feedback snapshot under the lock.
        # Feedback is shared across projects. Do not let a new transaction invalidate
        # the before/after snapshot needed by an interrupted correction elsewhere.
        for other in (root / 'projects').iterdir():
            if other.name != project and reader.safe_path(other, root) and other.is_dir():
                marker = safe(root, other / '.cairn' / 'pending.json')
                if marker.exists():
                    raise Refusal('RECOVERY_REQUIRED', 'Another project has a pending write; recover it before starting a new transaction.')
        before, after, warnings = plan(root, request)
        journal = dict(request_id=request_id, request_hash=request_hash, action=request['action'],
                       source=request['source'], before=before, after=after, warnings=warnings, phase='prepared')
        if request['action'] == 'correct':
            path = safe(root, root / 'protocol/benchmark/feedback.md')
            prior = path.read_bytes().decode('utf-8') if path.exists() else ''
            name = request['id'] + '.md'
            entry = '\n## Correction %s/%s\n\nSource: %s\n\nOriginal record:\n\n%s\n\nCorrected record (correct behavior):\n\n%s\n' % (project, request_id, request['source'], before[name], after[name])
            journal['feedback'] = {'before': prior, 'after': prior + entry}
        save_json(root, receipt_path, journal)
        save_json(root, pending, {'request_id': request_id})
        return resume(root, project, state, journal, receipt_path)


def recover(root, project, request_id):
    identifier(request_id)
    with project_lock(root, project) as state:
        pending = pending_path(root, project)
        if not pending.exists() or json.loads(pending.read_text(encoding='utf-8'))['request_id'] != request_id:
            raise Refusal('NOT_FOUND', 'No pending write has this request id.')
        path = safe(root, state / 'transactions' / (request_id + '.json'))
        journal = json.loads(path.read_text(encoding='utf-8'))
        if journal['phase'] == 'complete':
            pending.unlink()
            return journal['result']
        return resume(root, project, state, journal, path)


def browse(root, args):
    data, files, stamp = snapshot(root, args.project)
    records = data['projects'][0]['decisions']
    common = dict(schema=1, ok=True, project=args.project, snapshot=stamp,
                  complete=not data['errors'], errors=data['errors'], warnings=data['warnings'])
    if args.command == 'get':
        record = next((r for r in records if r['id'] == args.id), None)
        if record is None:
            raise Refusal('NOT_FOUND', 'No readable decision has this exact id; inspect list and diagnostics.', errors=data['errors'])
        record = dict(record)
        if args.revision and args.revision != record['revision']:
            raise Refusal('REVISION_CONFLICT', 'Decision changed; read it again from the start.')
        if args.offset and not args.revision:
            raise Refusal('INVALID_ARGUMENTS', 'Continue a section with --revision from the first read.')
        record['successors'] = [{'id': r['id'], 'file': r['file'], 'status': r['status']} for r in records if record['id'] in r['supersedes']]
        record.pop('content')
        if args.section:
            content = record['sections'][args.section]
            end = args.offset + args.limit
            common['slice'] = dict(section=args.section, text=content[args.offset:end], offset=args.offset,
                                   total_chars=len(content), truncated=end < len(content),
                                   next_offset=end if end < len(content) else None)
            # A section read never silently removes its applicability constraints.
            record['sections'] = {k: v for k, v in record['sections'].items() if k in ('decision', 'scope', 'excluded', 'overturn')}
        if args.metadata:
            record['scope'] = record['sections']['scope']
            record.pop('sections')
        common['decision'] = record
        return common
    if args.snapshot and args.snapshot != stamp:
        raise Refusal('REVISION_CONFLICT', 'The listing changed; restart at page 1.')
    if args.page > 1 and not args.snapshot:
        raise Refusal('INVALID_ARGUMENTS', 'Continue a page with the snapshot returned by page 1.')
    records = [r for r in records if r['status'] == args.status and (not args.since or r['decided_at'] >= args.since)]
    start = (args.page - 1) * args.page_size
    items = []
    for r in records[start:start + args.page_size]:
        item = {key: r[key] for key in ('id', 'project', 'title', 'status', 'file', 'revision', 'decided_at')}
        item.update(summary=r['sections']['decision'][:140], scope=r['sections']['scope'][:240],
                    summary_truncated=len(r['sections']['decision']) > 140, scope_truncated=len(r['sections']['scope']) > 240)
        items.append(item)
    common.update(items=items, total=len(records), page=args.page,
                  next_page=args.page + 1 if start + args.page_size < len(records) else None)
    common['next'] = dict(project=args.project, status=args.status, since=args.since, page=common['next_page'], page_size=args.page_size, snapshot=stamp) if common['next_page'] else None
    index_path = safe(root, project_path(root, args.project) / 'decisions-index.md')
    expected, _, _ = indexer.render_project(validator, project_path(root, args.project))
    common['index'] = 'current' if index_path.is_file() and index_path.read_text(encoding='utf-8') == expected else 'stale'
    return common


def brief_thread(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise Refusal('INVALID_ARGUMENTS', 'Use a nonblank thread identifier of at most 200 characters.')
    return value


def brief_parameters(focus, limit):
    if not isinstance(focus, list) or not 1 <= len(focus) <= 16:
        raise Refusal('INVALID_ARGUMENTS', 'Provide 1..16 focus terms.')
    if type(limit) is not int or not 1 <= limit <= 50:
        raise Refusal('INVALID_ARGUMENTS', 'Brief limit must be an integer in 1..50.')
    unique = {}
    for term in focus:
        if not isinstance(term, str) or not 1 <= len(term.strip()) <= 200:
            raise Refusal('INVALID_ARGUMENTS', 'Each focus term must have 1..200 characters after trimming.')
        term = term.strip()
        unique.setdefault(term.casefold(), term)
    return list(unique.values()), limit


def repository_key(root):
    return digest(os.path.normcase(str(root)))


def build_brief(root, project, thread, focus, limit):
    try:
        data, _, stamp = snapshot(root, project, fallback_title=False)
    except FileNotFoundError:
        raise Refusal('REVISION_CONFLICT', 'Project changed while reading; retry the read.')
    # The reader can detect a transient change even if the final file bytes match.
    if any(e['message'] in ('project changed while reading; retry',
                            'decision changed while reading; retry',
                            'decision write is pending recovery; no records exported',
                            'decision write is pending recovery; retry after recovery') for e in data['errors']):
        raise Refusal('REVISION_CONFLICT', 'Project changed while reading; retry the read.')
    candidates = []
    folded_focus = [(term, term.casefold()) for term in focus]
    for record in data['projects'][0]['decisions']:
        if record['status'] != 'valid':
            continue
        sections = record['sections']
        fields = {key: text.casefold() for key, text in (
            ('id', record['id']), ('title', record['title']),
            ('decision', sections['decision']), ('scope', sections['scope']),
        )}
        matched_terms = []
        hits = set()
        for term, folded in folded_focus:
            term_fields = [field for field, value in fields.items() if folded in value]
            if term_fields:
                matched_terms.append(term)
                hits.update(term_fields)
        if not matched_terms:
            continue
        matched_fields = [field for field in fields if field in hits]
        candidates.append(((-len(matched_terms), -len(matched_fields), record['id']),
                           record, matched_terms, matched_fields))
    candidates.sort(key=lambda candidate: candidate[0])
    items = []
    for _, record, matched_terms, matched_fields in candidates[:limit]:
        item = {key: record[key] for key in ('id', 'project', 'file', 'revision', 'status')}
        sections = record['sections']
        excerpts = dict(title=record['title'], headline=sections['decision'],
                        scope=sections['scope'], excluded=sections['excluded'], overturn=sections['overturn'])
        for key, text in excerpts.items():
            length = 160 if key in ('title', 'headline') else 240
            item[key] = text[:length]
            item[key + '_truncated'] = len(text) > length
        item['relevance'] = dict(matched_terms=matched_terms, matched_fields=matched_fields)
        items.append(item)
    return dict(schema=1, ok=True, kind=BRIEF_KIND, brief_version=BRIEF_VERSION, source_of_truth=False,
                project=project, thread=thread, focus=focus, limit=limit, repository_key=repository_key(root),
                snapshot=stamp, complete=not data['errors'], errors=data['errors'], warnings=data['warnings'],
                selection=dict(method='literal-focus-v1', matched=len(candidates), returned=len(items),
                               truncated=len(candidates) > len(items), semantic_coverage='unknown'),
                items=items)


def json_object(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError('duplicate JSON member')
    return result


def reject_json_constant(value):
    raise ValueError('non-JSON number')


def check_brief(root, project, thread):
    try:
        previous = json.load(sys.stdin, object_pairs_hook=json_object, parse_constant=reject_json_constant)
    except (ValueError, RecursionError):
        raise Refusal('INVALID_ARGUMENTS', 'Provide one complete brief JSON object on stdin.')
    if (not isinstance(previous, dict)
            or type(previous.get('schema')) is not int or previous['schema'] != 1
            or type(previous.get('brief_version')) is not int or previous['brief_version'] != BRIEF_VERSION
            or previous.get('kind') != BRIEF_KIND or previous.get('ok') is not True
            or previous.get('source_of_truth') is not False):
        raise Refusal('INVALID_ARGUMENTS', 'Unsupported or unsuccessful brief.')
    if (previous.get('project') != project or previous.get('thread') != thread
            or previous.get('repository_key') != repository_key(root)):
        raise Refusal('INVALID_ARGUMENTS', 'Brief does not belong to this repository, project and thread.')
    focus, limit = brief_parameters(previous.get('focus'), previous.get('limit'))
    if (previous['focus'] != focus or not isinstance(previous.get('snapshot'), str)
            or not SHA256.fullmatch(previous['snapshot'])
            or type(previous.get('complete')) is not bool
            or not isinstance(previous.get('selection'), dict)
            or not all(isinstance(previous.get(key), list) for key in ('items', 'errors', 'warnings'))):
        raise Refusal('INVALID_ARGUMENTS', 'Brief is missing required fields or has invalid parameters.')
    current = build_brief(root, project, thread, focus, limit)
    freshness, action = 'stale', 'rebuild'
    if current['snapshot'] != previous['snapshot']:
        reason = 'source_changed'
    else:
        # Compare JSON types, including booleans vs integers, independent of key order.
        try:
            matches = json.dumps(current, sort_keys=True) == json.dumps(previous, sort_keys=True)
        except (ValueError, RecursionError):
            matches = False
        if matches:
            freshness, reason = 'fresh', 'unchanged'
            truncated_constraints = any(
                item[flag]
                for item in current['items']
                for flag in ('headline_truncated', 'scope_truncated', 'excluded_truncated', 'overturn_truncated')
            )
            action = 'read_source' if (
                not current['complete'] or not current['items']
                or current['selection']['truncated'] or truncated_constraints
            ) else 'use_brief'
        else:
            reason = 'projection_changed'
    return dict(schema=1, ok=True, project=project, thread=thread, freshness=freshness, reason=reason,
                next_action=action, complete=current['complete'], errors=current['errors'],
                warnings=current['warnings'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', help='explicit private Cairn repository; otherwise use configured repository')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('projects')
    for name in ('list', 'get', 'recover', 'status', 'reindex', 'brief', 'brief-check'):
        command = commands.add_parser(name)
        command.add_argument('--project', required=True)
        if name in ('brief', 'brief-check'):
            command.add_argument('--thread', required=True, help='opaque host thread identifier')
            if name == 'brief':
                command.add_argument('--focus', action='append', required=True, help='literal term; repeat to add more')
                command.add_argument('--limit', type=int, default=5)
        elif name == 'recover':
            command.add_argument('--request-id', required=True)
        elif name == 'get':
            command.add_argument('--id', required=True)
            command.add_argument('--section', choices=[key for key, _ in reader.SECTION_KEYS])
            command.add_argument('--offset', type=int, default=0)
            command.add_argument('--limit', type=int, default=2000)
            command.add_argument('--metadata', action='store_true')
            command.add_argument('--revision', help='revision returned by an earlier get')
        elif name == 'list':
            command.add_argument('--status', choices=sorted(validator.ALLOWED_STATUS), default='valid')
            command.add_argument('--since')
            command.add_argument('--page', type=int, default=1)
            command.add_argument('--page-size', type=int, default=20)
            command.add_argument('--snapshot')
    commands.add_parser('write', help='read a confirmed decision change as JSON from stdin')
    args = parser.parse_args(argv)
    try:
        if not args.repository:
            try:
                config = json.loads(validator.config_path().read_text(encoding='utf-8'))
                if not all(isinstance(config.get(k), str) and config[k].strip() for k in ('repository', 'identity', 'default_project')):
                    raise ValueError()
                args.repository = config['repository']
            except (OSError, ValueError, AttributeError):
                raise Refusal('NOT_CONFIGURED', 'Connect Cairn with the installer, or specify --repository explicitly.')
        root = Path(os.path.expanduser(args.repository)).resolve()
        if not (root / 'projects').is_dir():
            raise Refusal('NOT_CONFIGURED', 'No Cairn projects directory exists at this repository.')
        if args.command == 'projects':
            directory = safe(root, root / 'projects')
            result = dict(schema=1, ok=True, projects=[p.name for p in sorted(directory.iterdir()) if ID.fullmatch(p.name) and reader.safe_path(p, root) and p.is_dir()])
        elif args.command == 'write':
            result = write(root, json.load(sys.stdin))
        elif args.command == 'recover':
            result = recover(root, args.project, args.request_id)
        elif args.command in ('brief', 'brief-check'):
            project, thread = identifier(args.project), brief_thread(args.thread)
            if args.command == 'brief':
                focus, limit = brief_parameters(args.focus, args.limit)
                result = build_brief(root, project, thread, focus, limit)
            else:
                result = check_brief(root, project, thread)
        elif args.command == 'status':
            path = pending_path(root, args.project)
            if path.exists():
                pending = json.loads(path.read_text(encoding='utf-8'))
                request_id = identifier(pending['request_id'])
                journal_path = safe(root, path.parent / 'transactions' / (request_id + '.json'))
                journal = json.loads(journal_path.read_text(encoding='utf-8'))
                result = dict(schema=1, ok=True, state='recovery_required', project=args.project,
                              request_id=request_id, phase=journal['phase'],
                              next_action='recover --project %s --request-id %s' % (args.project, request_id))
            else:
                data, _, stamp = snapshot(root, args.project)
                index_path = safe(root, project_path(root, args.project) / 'decisions-index.md')
                expected, _, _ = indexer.render_project(validator, project_path(root, args.project))
                result = dict(schema=1, ok=True, state='error' if data['errors'] else 'ready',
                              project=args.project, snapshot=stamp, errors=data['errors'], warnings=data['warnings'],
                              index='current' if index_path.is_file() and index_path.read_text(encoding='utf-8') == expected else 'stale',
                              capabilities=['list', 'get', 'write', 'recover', 'reindex', 'brief', 'brief-check'])
        elif args.command == 'reindex':
            with project_lock(root, args.project):
                data, files, stamp = snapshot(root, args.project)
                if data['errors']:
                    raise Refusal('VALIDATION_FAILED', 'Repair project errors before publishing an index.', errors=data['errors'])
                refresh_index(root, args.project)
                if read_files(root, args.project) != files:
                    raise Refusal('REVISION_CONFLICT', 'Project changed during index refresh; retry.')
                result = dict(schema=1, ok=True, project=args.project, index='current', snapshot=stamp)
        else:
            if args.command == 'list':
                if args.page < 1 or not 1 <= args.page_size <= 200:
                    raise Refusal('INVALID_ARGUMENTS', 'page must be positive; page-size must be 1..200.')
                if args.since:
                    validator.parse_date(args.since)
            else:
                decision_id(args.id)
                if args.offset < 0 or args.limit < 1 or (args.metadata and args.section):
                    raise Refusal('INVALID_ARGUMENTS', 'Use nonnegative offset, positive limit, and either metadata or section.')
            result = browse(root, args)
    except Refusal as exc:
        result = exc.result
    except (OSError, ValueError, KeyError, TypeError, UnicodeError) as exc:
        result = dict(schema=1, ok=False, code='IO_OR_INPUT_ERROR',
                      message='Cannot complete operation (%s). Inspect input or pending recovery before retrying.' % type(exc).__name__)
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
