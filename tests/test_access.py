"""Exercise the unified CLI against isolated repositories, never user data."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from test_read import decision

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / 'template/scripts/cairn.py'

class AccessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        shutil.copytree(ROOT / 'template/scripts', self.root / 'scripts')
        self.directory = self.root / 'projects/demo/decisions'
        self.directory.mkdir(parents=True)
        (self.directory / 'one.md').write_text(decision('demo', 'one'), encoding='utf-8')

    def call(self, *args, payload=None):
        result = subprocess.run([sys.executable, str(CLI), '--repository', str(self.root), *args],
                                input=json.dumps(payload) if payload is not None else None,
                                capture_output=True, text=True)
        self.assertTrue(result.stdout.strip(), result.stderr)
        return result.returncode, json.loads(result.stdout)

    def get(self, id='one'):
        code, result = self.call('get', '--project', 'demo', '--id', id)
        self.assertEqual(code, 0, result)
        return result['decision']

    def request(self, action='create', **kwargs):
        return dict(request_id='request-1', project='demo', action=action,
                    confirmed=True, source='user: explicitly confirmed in test', **kwargs)

    def test_list_get_scope_and_revision(self):
        code, result = self.call('list', '--project', 'demo', '--page-size', '1')
        self.assertEqual(code, 0, result)
        self.assertEqual(result['items'][0]['id'], 'one')
        self.assertEqual(result['items'][0]['scope'], 'All.')
        self.assertEqual(result['total'], 1)
        record = self.get()
        self.assertEqual(len(record['revision']), 64)
        self.assertEqual(record['file'], 'projects/demo/decisions/one.md')

    def test_create_and_retry_do_not_duplicate(self):
        payload = self.request(id='two', content=decision('demo', 'two'))
        code, first = self.call('write', payload=payload)
        self.assertEqual(code, 0, first)
        code, retry = self.call('write', payload=payload)
        self.assertEqual(code, 0, retry)
        self.assertEqual(first, retry)
        self.assertEqual(len(list(self.directory.glob('*.md'))), 2)
        payload['content'] += '\nChanged'
        code, result = self.call('write', payload=payload)
        self.assertNotEqual(code, 0)
        self.assertEqual(result['code'], 'REQUEST_CONFLICT')

    def test_supersede_keeps_history_and_refreshes_index(self):
        payload = self.request('supersede', id='two', content=decision('demo', 'two', extra='supersedes: one\n'),
                               expected={'one': self.get()['revision']})
        code, result = self.call('write', payload=payload)
        self.assertEqual(code, 0, result)
        self.assertEqual(self.get()['status'], 'superseded')
        self.assertEqual(self.get('two')['supersedes'], ['one'])
        text = (self.directory.parent / 'decisions-index.md').read_text()
        self.assertIn('two:', text)
        self.assertNotIn('one:', text)

    def test_stale_write_and_unclear_intent_change_nothing(self):
        before = (self.directory / 'one.md').read_bytes()
        payload = self.request('revoke', id='one', expected={'one': '0' * 64})
        code, result = self.call('write', payload=payload)
        self.assertEqual(result['code'], 'REVISION_CONFLICT')
        payload['expected'] = {'one': self.get()['revision']}
        payload['confirmed'] = False
        code, result = self.call('write', payload=payload)
        self.assertEqual(result['code'], 'CONFIRMATION_REQUIRED')
        self.assertEqual((self.directory / 'one.md').read_bytes(), before)

    def test_index_omits_invalid_history_like_reader(self):
        (self.directory / 'broken.md').write_text(decision('demo', 'broken', extra='supersedes: absent\n'))
        subprocess.run([sys.executable, str(self.root / 'scripts/index.py'), str(self.root)], check=True, capture_output=True)
        text = (self.directory.parent / 'decisions-index.md').read_text()
        self.assertNotIn('broken:', text)
        _, result = self.call('list', '--project', 'demo')
        self.assertFalse(result['complete'])
        self.assertTrue(result['errors'])


class RecoveryTests(unittest.TestCase):
    setUp = AccessTests.setUp
    call = AccessTests.call
    get = AccessTests.get
    request = AccessTests.request
    def module(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('access_under_test', CLI)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def interrupt(self, payload, fail_name):
        from unittest import mock
        module = self.module()
        atomic = module.atomic_text
        def interrupted(root, path, text):
            if path.name == fail_name:
                raise OSError('simulated process interruption')
            return atomic(root, path, text)
        with mock.patch.object(module, 'atomic_text', side_effect=interrupted):
            with self.assertRaises(OSError):
                module.write(self.root, payload)

    def test_partial_replacement_is_hidden_and_recoverable(self):
        payload = self.request('supersede', id='two', content=decision('demo', 'two', extra='supersedes: one\n'),
                               expected={'one': self.get()['revision']})
        self.interrupt(payload, 'two.md')
        _, status = self.call('status', '--project', 'demo')
        self.assertEqual(status['state'], 'recovery_required')
        _, blocked = self.call('list', '--project', 'demo')
        self.assertEqual(blocked['code'], 'RECOVERY_REQUIRED')
        legacy = subprocess.run([sys.executable, str(self.root / 'scripts/read.py'), str(self.root)], capture_output=True, text=True)
        legacy = json.loads(legacy.stdout)
        self.assertFalse(legacy['projects'][0]['decisions'])
        self.assertTrue(legacy['errors'])
        code, result = self.call('recover', '--project', 'demo', '--request-id', 'request-1')
        self.assertEqual(code, 0, result)
        self.assertEqual(self.get()['status'], 'superseded')
        self.assertEqual(self.get('two')['status'], 'valid')
        _, retry = self.call('write', payload=payload)
        self.assertEqual(retry, result)

    def test_index_failure_retry_refreshes_without_duplicate(self):
        payload = self.request(id='two', content=decision('demo', 'two'))
        self.interrupt(payload, 'decisions-index.md')
        _, status = self.call('status', '--project', 'demo')
        self.assertEqual(status['phase'], 'index_pending')
        _, result = self.call('write', payload=payload)
        self.assertTrue(result['ok'])
        self.assertEqual(len(list(self.directory.glob('*.md'))), 2)

    def test_recovery_never_overwrites_manual_edits(self):
        payload = self.request('supersede', id='two', content=decision('demo', 'two', extra='supersedes: one\n'),
                               expected={'one': self.get()['revision']})
        self.interrupt(payload, 'two.md')
        path = self.directory / 'one.md'
        path.write_text(path.read_text() + '\nManual correction\n')
        before = path.read_bytes()
        _, result = self.call('recover', '--project', 'demo', '--request-id', 'request-1')
        self.assertEqual(result['code'], 'RECOVERY_CONFLICT')
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse((self.directory / 'two.md').exists())

    def test_correction_records_feedback_once_and_preserves_lifecycle(self):
        payload = self.request('correct', id='one', content=decision('demo', 'one', body='# Fixed\n\n## Decision\nDo it.\n'),
                               expected={'one': self.get()['revision']})
        _, first = self.call('write', payload=payload)
        self.assertTrue(first['ok'], first)
        _, again = self.call('write', payload=payload)
        feedback = (self.root / 'protocol/benchmark/feedback.md').read_text()
        self.assertEqual(feedback.count('## Correction demo/request-1'), 1)
        self.assertIn('Original record', feedback)
        self.assertEqual(self.get()['status'], 'valid')

    def test_page_requires_same_project_snapshot(self):
        (self.directory / 'two.md').write_text(decision('demo', 'two'))
        _, page1 = self.call('list', '--project', 'demo', '--page-size', '1')
        _, page2 = self.call('list', '--project', 'demo', '--page-size', '1', '--page', '2', '--snapshot', page1['snapshot'])
        self.assertEqual(page2['items'][0]['id'], 'two')
        (self.directory / 'one.md').write_text(decision('demo', 'one') + '\nChanged')
        _, result = self.call('list', '--project', 'demo', '--page-size', '1', '--page', '2', '--snapshot', page1['snapshot'])
        self.assertEqual(result['code'], 'REVISION_CONFLICT')

    def test_section_retains_scope_and_has_continuation(self):
        _, result = self.call('get', '--project', 'demo', '--id', 'one', '--section', 'rationale', '--limit', '3')
        self.assertEqual(result['slice']['text'], 'Bec')
        self.assertEqual(result['slice']['next_offset'], 3)
        self.assertEqual(result['decision']['sections']['scope'], 'All.')

    def test_linked_targets_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            external = Path(temp) / 'secret.md'
            external.write_text('secret')
            target = self.directory / 'linked.md'
            try:
                target.symlink_to(external)
            except OSError:
                self.skipTest('symlinks unavailable')
            _, result = self.call('write', payload=self.request(id='linked', content=decision('demo', 'linked')))
            self.assertEqual(result['code'], 'UNSAFE_PATH')
            self.assertEqual(external.read_text(), 'secret')

    def test_invalid_proposal_leaves_original_and_no_pending(self):
        _, result = self.call('write', payload=self.request(id='bad', content=decision('other', 'bad')))
        self.assertEqual(result['code'], 'VALIDATION_FAILED')
        self.assertFalse((self.directory.parent / '.cairn/pending.json').exists())
        self.assertEqual([p.name for p in self.directory.glob('*.md')], ['one.md'])

    def test_crlf_revision_can_be_used_for_write(self):
        path = self.directory / 'one.md'
        path.write_bytes(decision('demo', 'one').replace('\n', '\r\n').encode())
        _, result = self.call('write', payload=self.request('revoke', id='one', expected={'one': self.get()['revision']}))
        self.assertTrue(result['ok'], result)
        self.assertEqual(self.get()['status'], 'revoked')

    def test_project_lock_prevents_concurrent_writers(self):
        module = self.module()
        with module.project_lock(self.root, 'demo'):
            _, result = self.call('write', payload=self.request(id='two', content=decision('demo', 'two')))
        self.assertEqual(result['code'], 'BUSY')
        self.assertFalse((self.directory / 'two.md').exists())

    def test_old_path_exposes_successor_without_rewriting_body(self):
        original = (self.directory / 'one.md').read_text().split('---', 2)[2]
        _, result = self.call('write', payload=self.request('supersede', id='two',
            content=decision('demo', 'two', extra='supersedes: one\n'), expected={'one': self.get()['revision']}))
        self.assertTrue(result['ok'], result)
        record = self.get()
        self.assertEqual(record['successors'][0]['id'], 'two')
        self.assertEqual((self.directory / 'one.md').read_text().split('---', 2)[2], original)

    def test_legacy_id_from_list_round_trips_to_get(self):
        (self.directory / 'Old_name.md').write_text(decision('demo', 'Old_name'))
        _, result = self.call('list', '--project', 'demo')
        self.assertIn('Old_name', [item['id'] for item in result['items']])
        self.assertEqual(self.get('Old_name')['id'], 'Old_name')

    def test_section_continuation_rejects_changed_revision(self):
        revision = self.get()['revision']
        (self.directory / 'one.md').write_text(decision('demo', 'one') + '\nChanged')
        _, result = self.call('get', '--project', 'demo', '--id', 'one', '--section', 'rationale',
                              '--offset', '3', '--revision', revision)
        self.assertEqual(result['code'], 'REVISION_CONFLICT')

    def test_replacement_with_missing_or_extra_history_is_refused(self):
        before = (self.directory / 'one.md').read_bytes()
        _, result = self.call('write', payload=self.request('supersede', id='two',
            content=decision('demo', 'two'), expected={'one': self.get()['revision']}))
        self.assertEqual(result['code'], 'INVALID_STATE')
        self.assertEqual((self.directory / 'one.md').read_bytes(), before)

    def test_project_reader_detects_changes_during_legacy_read(self):
        from unittest import mock
        module = self.module().reader
        original = module.read_decision
        def changed(*args, **kwargs):
            result = original(*args, **kwargs)
            (self.directory / 'two.md').write_text(decision('demo', 'two'))
            return result
        with mock.patch.object(module, 'read_decision', side_effect=changed):
            result, _ = module.read_repository(module.load_validate(), self.root, ['demo'])
        self.assertEqual(result['projects'][0]['decisions'], [])
        self.assertTrue(result['errors'])

    def test_index_command_does_not_publish_pending_state(self):
        payload = self.request(id='two', content=decision('demo', 'two'))
        self.interrupt(payload, 'two.md')
        result = subprocess.run([sys.executable, str(self.root / 'scripts/index.py'), str(self.root)], capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.directory.parent / 'decisions-index.md').exists())

    def test_handled_output_matches_envelope_schema(self):
        import schema_check
        schema = json.loads((ROOT / 'docs/schema/access-output.schema.json').read_text())
        for args in [('list', '--project', 'demo'), ('get', '--project', 'demo', '--id', 'missing'), ('status', '--project', 'demo')]:
            _, result = self.call(*args)
            self.assertEqual(schema_check.check(result, schema, schema), [])

    def test_bad_encoding_is_isolated_from_healthy_records(self):
        (self.directory / 'bad.md').write_bytes(b'\xff')
        _, listing = self.call('list', '--project', 'demo')
        self.assertTrue(listing['ok'], listing)
        self.assertFalse(listing['complete'])
        self.assertEqual([r['id'] for r in listing['items']], ['one'])
        self.assertEqual(listing['errors'][0]['path'], 'projects/demo/decisions/bad.md')
        self.assertEqual(self.get()['id'], 'one')
        _, status = self.call('status', '--project', 'demo')
        self.assertEqual(status['state'], 'error')

    def test_pending_correction_blocks_new_cross_project_write(self):
        other = self.root / 'projects/other/decisions'
        other.mkdir(parents=True)
        (other / 'one.md').write_text(decision('other', 'one'))
        _, other_record = self.call('get', '--project', 'other', '--id', 'one')
        payload = self.request('correct', id='one', content=decision('demo', 'one', body='# Fixed A\n\n## Decision\nDo it.\n'),
                               expected={'one': self.get()['revision']})
        self.interrupt(payload, 'decisions-index.md')
        second = dict(request_id='request-b', project='other', action='correct', id='one', confirmed=True,
                      source='user confirmed B correction', content=decision('other', 'one', body='# Fixed B\n\n## Decision\nDo it.\n'),
                      expected={'one': other_record['decision']['revision']})
        _, blocked = self.call('write', payload=second)
        self.assertEqual(blocked['code'], 'RECOVERY_REQUIRED', blocked)
        _, recovered = self.call('recover', '--project', 'demo', '--request-id', 'request-1')
        self.assertTrue(recovered['ok'], recovered)
        _, completed = self.call('write', payload=second)
        self.assertTrue(completed['ok'], completed)
        feedback = (self.root / 'protocol/benchmark/feedback.md').read_text()
        self.assertEqual(feedback.count('## Correction'), 2)

    def test_prepared_receipt_without_marker_replans_after_other_recovery(self):
        other = self.root / 'projects/other/decisions'
        other.mkdir(parents=True)
        (other / 'one.md').write_text(decision('other', 'one'))
        _, other_record = self.call('get', '--project', 'other', '--id', 'one')
        first = self.request('correct', id='one', content=decision('demo', 'one', body='# Fixed A\n\n## Decision\nDo it.\n'),
                             expected={'one': self.get()['revision']})
        self.interrupt(first, 'pending.json')
        second = dict(request_id='request-b', project='other', action='correct', id='one', confirmed=True,
                      source='user confirmed B correction', content=decision('other', 'one', body='# Fixed B\n\n## Decision\nDo it.\n'),
                      expected={'one': other_record['decision']['revision']})
        self.interrupt(second, 'one.md')
        _, blocked = self.call('write', payload=first)
        self.assertEqual(blocked['code'], 'RECOVERY_REQUIRED', blocked)
        self.assertFalse((self.directory.parent / '.cairn/pending.json').exists())
        _, recovered = self.call('recover', '--project', 'other', '--request-id', 'request-b')
        self.assertTrue(recovered['ok'], recovered)
        _, retried = self.call('write', payload=first)
        self.assertTrue(retried['ok'], retried)
        feedback = (self.root / 'protocol/benchmark/feedback.md').read_text()
        self.assertEqual(feedback.count('## Correction'), 2)

    def test_correction_recovery_preserves_crlf_feedback_bytes(self):
        path = self.directory / 'one.md'
        path.write_bytes(decision('demo', 'one').replace('\n', '\r\n').encode())
        feedback = self.root / 'protocol/benchmark/feedback.md'
        feedback.parent.mkdir(parents=True)
        feedback.write_bytes(b'# Feedback\r\nExisting evidence.\r\n')
        payload = self.request('correct', id='one', content=decision('demo', 'one', body='# Fixed\n\n## Decision\nDo it.\n'),
                               expected={'one': self.get()['revision']})
        self.interrupt(payload, 'decisions-index.md')
        before = feedback.read_bytes()
        _, result = self.call('recover', '--project', 'demo', '--request-id', 'request-1')
        self.assertTrue(result['ok'], result)
        self.assertEqual(feedback.read_bytes(), before)
        self.assertTrue(before.startswith(b'# Feedback\r\nExisting evidence.\r\n'))

if __name__ == '__main__':
    unittest.main()
