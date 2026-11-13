"""Exercise a thread's disposable candidate brief through the local CLI."""

import copy
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import schema_check
from test_access import CLI, ROOT
import test_access
from test_read import decision

BRIEF_SCHEMA = json.loads((ROOT / 'docs/schema/brief-output.schema.json').read_text(encoding='utf-8'))
THREAD = 'thread/../42'
UNSET = object()


def body(title='Current choice', conclusion='Keep pricing stable.', scope='Public plans.',
         excluded='Trial accounts.', overturn='A change in costs.'):
    return ('# %s\n\n## Decision\n%s\n\n## Rationale\nPrivate rationale.\n\n## Scope\n%s\n\n'
            '## Explicitly excluded\n%s\n\n## Overturn signal\n%s\n') % (
                title, conclusion, scope, excluded, overturn)


class BriefTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.repo = Path(temp.name).resolve()
        self.folder = self.repo / 'projects/demo/decisions'
        self.folder.mkdir(parents=True)

    def add(self, id_, project='demo', **kwargs):
        folder = self.repo / 'projects' / project / 'decisions'
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (id_ + '.md')
        path.write_text(decision(project, id_, **kwargs), encoding='utf-8')
        return path

    def run_cli(self, *args, value=UNSET, raw=None, repo=None, expect=0):
        if value is not UNSET:
            raw = json.dumps(value)
        result = subprocess.run(
            [sys.executable, str(CLI), '--repository', str(repo or self.repo), *args],
            capture_output=True, text=True, input=raw, encoding='utf-8',
        )
        self.assertEqual(result.returncode, expect, result.stdout + result.stderr)
        self.assertNotIn('Traceback', result.stderr)
        return json.loads(result.stdout) if result.stdout else None

    def brief(self, *args, focus=('pricing',), thread=THREAD, project='demo', **kwargs):
        terms = [arg for term in focus for arg in ('--focus', term)]
        return self.run_cli('brief', '--project', project, '--thread', thread, *terms, *args, **kwargs)

    def check(self, value=UNSET, thread=THREAD, project='demo', **kwargs):
        return self.run_cli('brief-check', '--project', project, '--thread', thread, value=value, **kwargs)

    def assert_freshness(self, result, freshness, reason, action):
        self.assertEqual(
            {k: result[k] for k in ('schema', 'ok', 'project', 'thread', 'freshness', 'reason', 'next_action')},
            dict(schema=1, ok=True, project='demo', thread=THREAD, freshness=freshness, reason=reason,
                 next_action=action),
        )
        self.assertNotIn('items', result)

    def test_literal_focus_sorting_and_language(self):
        self.add('price-id', body=body(title='PRICING', conclusion='Free credits.', scope='First-year pricing.'))
        self.add('a-newer', body=body(title='Pricing credits', conclusion='Trial.', scope='All.'), at='2026-11-01')
        self.add('b-older', body=body(title='Pricing credits', conclusion='Trial.', scope='All.'), at='2026-01-01')
        self.add('c-zh', body='# 方案\n\n## 结论\n保留积分额度。\n\n## 为什么\n原因。\n\n'
                            '## 适用范围\n积分额度适用新订阅。\n\n## 明确不做\n不含试用。\n\n## 推翻条件\n待验证。\n')
        self.add('d-many-fields', body=body(title='Pricing', conclusion='Pricing.', scope='Pricing.'))
        self.add('e-just-reason', body=body(conclusion='No.', scope='No.', excluded='Pricing', overturn='Credits')
                 .replace('Private rationale.', 'Pricing and credits'))
        self.add('f-different-phrase', body=body(conclusion='积分与额度分开。', scope='仅积分。'))
        self.add('pricing-other', project='other', body=body(title='Pricing credits', scope='积分额度'))
        self.add('g-older-status', status='superseded', body=body(title='Pricing credits', scope='积分额度'))
        self.add('h-revoked', status='revoked', body=body(title='Pricing credits', scope='积分额度'))
        self.add('Straße', body=body(conclusion='No.', scope='No.'))
        result = self.brief(focus=(' PRICING ', ' Credits ', 'pricing', ' 积分额度 ', 'STRASSE', 'Straße'))
        self.assertEqual(result['focus'], ['PRICING', 'Credits', '积分额度', 'STRASSE'])
        self.assertEqual(result['thread'], THREAD)
        self.assertEqual(result['project'], 'demo')
        self.assertEqual([item['id'] for item in result['items']],
                         ['price-id', 'a-newer', 'b-older', 'd-many-fields', 'c-zh'])
        self.assertEqual(result['items'][0]['relevance'],
                         dict(matched_terms=['PRICING', 'Credits'], matched_fields=['title', 'decision', 'scope']))
        self.assertEqual(result['items'][4]['relevance'],
                         dict(matched_terms=['积分额度'], matched_fields=['decision', 'scope']))
        self.assertEqual(result['selection'], dict(method='literal-focus-v1', matched=6, returned=5,
                                                  truncated=True, semantic_coverage='unknown'))
        self.assertTrue(result['complete'])
        self.assertEqual(self.brief(focus=('strasse',))['items'][0]['relevance'],
                         dict(matched_terms=['strasse'], matched_fields=['id']))
        self.assertEqual(schema_check.check(result, BRIEF_SCHEMA, BRIEF_SCHEMA), [])
        self.assert_freshness(self.check(result), 'fresh', 'unchanged', 'read_source')

    def test_bounded_fields_unicode_and_missing_values(self):
        self.add('pricing-long', body=body(
            title='📗' * 161, conclusion='🍓' * 160 + 'pricing', scope='🍉' * 241,
            excluded='🌿' * 241, overturn='🫐' * 241))
        self.add('pricing-missing', body='## Scope\nPricing.\n')
        result = self.brief()
        long, empty = result['items']
        self.assertEqual(long['headline'], '🍓' * 160)
        self.assertEqual(long['title'], '📗' * 160)
        self.assertEqual(long['scope'], '🍉' * 240)
        self.assertEqual(long['excluded'], '🌿' * 240)
        self.assertEqual(long['overturn'], '🫐' * 240)
        self.assertEqual(long['relevance']['matched_fields'], ['id', 'decision'])
        for key in ('title', 'headline', 'scope', 'excluded', 'overturn'):
            self.assertIs(long[key + '_truncated'], True)
            self.assertIs(empty[key + '_truncated'], False)
        for key in ('title', 'headline', 'excluded', 'overturn'):
            self.assertEqual(empty[key], '')
        self.assertEqual(empty['relevance']['matched_fields'], ['id', 'scope'])
        self.assertNotIn('Private rationale.', json.dumps(result))
        self.assertNotIn('decided_at', long)
        self.assertNotIn('content', long)
        self.assertEqual(schema_check.check(result, BRIEF_SCHEMA, BRIEF_SCHEMA), [])
        # The legacy read and the unified exact get still use the legacy title fallback.
        result = self.run_cli('get', '--project', 'demo', '--id', 'pricing-missing')
        self.assertEqual(result['decision']['title'], 'pricing-missing')

    def test_check_requires_source_for_truncated_decision_or_applicability(self):
        self.add('pricing-complete', body=body())
        complete = self.brief()
        self.assert_freshness(self.check(complete), 'fresh', 'unchanged', 'use_brief')

        self.add('pricing-title-only', body=body(title='界' * 161))
        title_only = self.brief()
        self.assertTrue(any(item['title_truncated'] for item in title_only['items']))
        self.assert_freshness(self.check(title_only), 'fresh', 'unchanged', 'use_brief')

        fields = (
            ('conclusion', 'headline', 161), ('scope', 'scope', 241),
            ('excluded', 'excluded', 241), ('overturn', 'overturn', 241),
        )
        for argument, field, length in fields:
            with self.subTest(field=field):
                candidate = self.add('pricing-truncated', body=body(**{argument: '界' * length}))
                try:
                    result = self.brief()
                    self.assertTrue(result['complete'])
                    self.assertFalse(result['selection']['truncated'])
                    item = next(item for item in result['items'] if item['id'] == 'pricing-truncated')
                    self.assertIs(item[field + '_truncated'], True)
                    self.assert_freshness(self.check(result), 'fresh', 'unchanged', 'read_source')
                finally:
                    candidate.unlink()

    def test_diagnostics_are_independent_of_matches_and_limit(self):
        empty = self.brief()
        self.assertTrue(empty['complete'])
        self.assertEqual(empty['items'], [])
        self.assertEqual(empty['errors'], [])
        self.assert_freshness(self.check(empty), 'fresh', 'unchanged', 'read_source')

        self.add('pricing-valid', body=body())
        self.add('pricing-invalid', status='unknown', body=body())
        self.add('pricing-bad-utf8', body=body()).write_bytes(b'\xff')
        self.add('warn', body=body(conclusion='Other.'), at='2026-10-11T23:30:00-05:00')
        result = self.brief('--limit', '1')
        self.assertEqual([i['id'] for i in result['items']], ['pricing-valid'])
        self.assertFalse(result['complete'])
        self.assertFalse(result['selection']['truncated'])
        self.assertEqual(result['selection']['matched'], 1)
        self.assertEqual(len(result['errors']), 2)
        self.assertTrue(any('calendar date' in w['message'] for w in result['warnings']))
        self.assertEqual(schema_check.check(result, BRIEF_SCHEMA, BRIEF_SCHEMA), [])
        self.assertNotIn(str(self.repo), json.dumps(result))
        unmatched = self.brief(focus=('no match',))
        self.assertEqual(unmatched['items'], [])
        self.assertEqual(unmatched['errors'], result['errors'])
        self.assertEqual(unmatched['warnings'], result['warnings'])
        check = self.check(result)
        self.assert_freshness(check, 'fresh', 'unchanged', 'read_source')
        self.assertEqual(check['errors'], result['errors'])

    def test_project_thread_repository_binding_and_determinism(self):
        self.add('live', body=body())
        result = self.brief()
        self.assertEqual(result, self.brief())
        self.assertEqual(result['snapshot'], self.run_cli('list', '--project', 'demo')['snapshot'])
        self.assertEqual(result['items'][0]['revision'],
                         self.run_cli('get', '--project', 'demo', '--id', 'live')['decision']['revision'])
        self.assertEqual(self.brief(repo=self.repo / 'projects' / '..'), result)
        self.assertNotIn(str(self.repo), json.dumps(result))
        with tempfile.TemporaryDirectory() as alternate:
            repo = Path(alternate)
            destination = repo / 'projects/demo/decisions/live.md'
            destination.parent.mkdir(parents=True)
            destination.write_bytes((self.folder / 'live.md').read_bytes())
            other = self.brief(repo=repo)
            self.assertEqual(result['snapshot'], other['snapshot'])
            self.assertNotEqual(result['repository_key'], other['repository_key'])
            self.assertEqual(self.check(result, repo=repo, expect=1)['code'], 'INVALID_ARGUMENTS')
        self.add('other', project='other', body=body())
        self.assert_freshness(self.check(result), 'fresh', 'unchanged', 'use_brief')
        self.assertEqual(self.check(result, project='other', expect=1)['code'], 'INVALID_ARGUMENTS')
        self.assertEqual(self.check(result, thread='thread-43', expect=1)['code'], 'INVALID_ARGUMENTS')
        self.assertEqual(self.brief(project='../demo', expect=1)['code'], 'INVALID_ARGUMENTS')
        self.assertEqual(self.brief(project='unknown', expect=1)['code'], 'PROJECT_NOT_FOUND')
        self.run_cli('brief', '--thread', THREAD, '--focus', 'pricing', expect=2)
        self.run_cli('brief', '--project', 'demo', '--focus', 'pricing', expect=2)
        self.run_cli('brief-check', '--thread', THREAD, expect=2)

    def test_unmatched_add_edit_and_delete_invalidate(self):
        self.add('visible', body=body())
        first = self.brief()
        hidden = self.add('hidden', body=body(conclusion='Track signups.'))
        self.assert_freshness(self.check(first), 'stale', 'source_changed', 'rebuild')
        second = self.brief()
        self.assertEqual(second['items'], first['items'])
        hidden.write_text(hidden.read_text(encoding='utf-8').replace('Private rationale.', 'Updated evidence.'),
                          encoding='utf-8')
        self.assert_freshness(self.check(second), 'stale', 'source_changed', 'rebuild')
        third = self.brief()
        self.assertEqual(third['items'], first['items'])
        hidden.unlink()
        self.assert_freshness(self.check(third), 'stale', 'source_changed', 'rebuild')
        self.assertEqual(self.brief(), first)

    def test_writer_create_correct_supersede_and_revoke_invalidate(self):
        previous = self.brief()
        self.assert_freshness(self.check(previous), 'fresh', 'unchanged', 'read_source')
        changes = [
            ('create', 'original', body(conclusion='Use monthly pricing.'), None),
            ('correct', 'original', body(conclusion='Use quarterly pricing.'), 'original'),
            ('supersede', 'updated', body(conclusion='Use annual pricing.'), 'original'),
            ('revoke', 'updated', None, 'updated'),
        ]
        for action, id_, text, predecessor in changes:
            with self.subTest(action=action):
                request = dict(request_id=action, project='demo', action=action, id=id_, confirmed=True,
                               source='User explicitly confirmed in this isolated CLI exercise.')
                if predecessor:
                    revision = self.run_cli('get', '--project', 'demo', '--id', predecessor)['decision']['revision']
                    request['expected'] = {predecessor: revision}
                if text is not None:
                    request['content'] = decision('demo', id_, body=text,
                                                  extra='supersedes: original\n' if action == 'supersede' else '')
                self.assertEqual(self.run_cli('write', value=request)['code'], 'WRITTEN')
                self.assert_freshness(self.check(previous), 'stale', 'source_changed', 'rebuild')
                previous = self.brief()
                self.assertEqual([item['id'] for item in previous['items']], [id_] if text else [])
                self.assert_freshness(self.check(previous), 'fresh', 'unchanged', 'use_brief' if text else 'read_source')

    def test_pending_refuses_build_and_check(self):
        previous = self.brief()
        pending = self.folder.parent / '.cairn/pending.json'
        pending.parent.mkdir()
        pending.write_text('{}', encoding='utf-8')
        self.assertEqual(self.brief(expect=1)['code'], 'RECOVERY_REQUIRED')
        self.assertEqual(self.check(previous, expect=1)['code'], 'RECOVERY_REQUIRED')

    def test_concurrent_changes_refuse_build_and_check(self):
        self.add('original', body=body())
        old = self.brief()
        module = test_access.RecoveryTests.module(self)
        original = module.reader.read_repository
        for command in ('brief', 'brief-check'):
            with self.subTest(command=command):
                argv = ['--repository', str(self.repo), command, '--project', 'demo', '--thread', THREAD]
                if command == 'brief':
                    argv.extend(['--focus', 'pricing'])

                def changed(*args, **kwargs):
                    result = original(*args, **kwargs)
                    self.add('changed-' + command, body=body())
                    return result

                stdout = io.StringIO()
                with mock.patch.object(module.reader, 'read_repository', side_effect=changed), \
                     mock.patch.object(module.sys, 'stdin', io.TextIOWrapper(io.BytesIO(json.dumps(old).encode()))), \
                     mock.patch.object(module.sys, 'stdout', stdout):
                    self.assertEqual(module.main(argv), 1)
                self.assertEqual(json.loads(stdout.getvalue())['code'], 'REVISION_CONFLICT')

    def test_record_deleted_during_read_refuses_projection(self):
        path = self.add('original', body=body())
        old = self.brief()
        module = test_access.RecoveryTests.module(self)
        original = module.reader.read_decision

        def removed(*args, **kwargs):
            path.unlink()
            return original(*args, **kwargs)

        with mock.patch.object(module.reader, 'read_decision', side_effect=removed):
            with self.assertRaises(module.Refusal) as exc:
                module.build_brief(self.repo, 'demo', THREAD, old['focus'], old['limit'])
        self.assertEqual(exc.exception.result['code'], 'REVISION_CONFLICT')

    def test_manipulated_projection_cannot_pass_freshness(self):
        self.add('original', body=body())
        old = self.brief()
        mutations = (
            lambda brief: brief['items'][0].update(headline='Injected text.'),
            lambda brief: brief['items'][0].update(title_truncated=0),
            lambda brief: brief['selection'].update(matched=True),
            lambda brief: brief['items'][0].update(rationale='Unknown payload.'),
            lambda brief: brief.update(warnings=[{'level': 'warning', 'path': 'made-up', 'message': 'injected'}]),
            lambda brief: brief.update(items=[]),
            lambda brief: brief.update(limit=1, focus=['unrelated']),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                modified = copy.deepcopy(old)
                mutate(modified)
                self.assert_freshness(self.check(modified), 'stale', 'projection_changed', 'rebuild')

    def test_invalid_cli_values_and_invalid_brief_documents(self):
        previous = self.brief()
        for kwargs in ({'focus': ('  ',)}, {'focus': ('x' * 201,)}, {'focus': ('x',) * 17},
                       {'thread': ''}, {'thread': '  '}, {'thread': 'a' * 201}):
            with self.subTest(kwargs=kwargs):
                self.assertEqual(self.brief(expect=1, **kwargs)['code'], 'INVALID_ARGUMENTS')
        self.brief(focus=tuple(str(i) for i in range(16)), thread='界' * 200)
        self.brief('--limit', '50', focus=('界' * 200,))
        self.run_cli('brief', '--project', 'demo', '--thread', THREAD, expect=2)
        for limit in ('0', '51', '-1'):
            self.assertEqual(self.brief('--limit', limit, expect=1)['code'], 'INVALID_ARGUMENTS')
        self.brief('--limit', 'true', expect=2)

        for updates in (
            dict(schema=True), dict(schema=1.0), dict(ok=1), dict(brief_version=2), dict(brief_version=True),
            dict(kind='unknown'), dict(source_of_truth=0), dict(project=[]), dict(thread={}), dict(repository_key=None),
            dict(focus='pricing'), dict(focus=[]), dict(focus=[{}]), dict(focus=[True]), dict(focus=['  ']),
            dict(focus=['x' * 201]), dict(focus=['x'] * 17), dict(focus=['x', 'X']), dict(focus=[' x ']),
            dict(limit=True), dict(limit=5.0), dict(limit=0), dict(limit=51), dict(limit='5'),
            dict(snapshot=True), dict(complete=1), dict(errors={}), dict(items={}), dict(selection=[]),
        ):
            with self.subTest(updates=updates):
                self.assertEqual(self.check(dict(previous, **updates), expect=1)['code'], 'INVALID_ARGUMENTS')
        for missing in ('snapshot', 'focus', 'items', 'errors'):
            modified = previous.copy()
            del modified[missing]
            self.assertEqual(self.check(modified, expect=1)['code'], 'INVALID_ARGUMENTS')
        for invalid in ('', '{', 'null', '[]', 'true', '{"schema":NaN}', '[' * 1500 + ']' * 1500,
                        json.dumps(previous)[:-1] + ', "schema":1}'):
            with self.subTest(raw=invalid[:45]):
                self.assertEqual(self.check(raw=invalid, expect=1)['code'], 'INVALID_ARGUMENTS')

    def test_cli_status_advertises_capabilities(self):
        caps = self.run_cli('status', '--project', 'demo')['capabilities']
        self.assertEqual(set(caps), {'list', 'get', 'write', 'recover', 'reindex', 'brief', 'brief-check'})

    def test_installed_cli_build_and_check_do_not_change_repository_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            repo = base / 'repository'
            env = dict(os.environ, CAIRN_CONFIG=str(base / 'config.json'))
            setup = [sys.executable, str(ROOT / 'install.py')]
            subprocess.run(setup + ['install', '--repository', str(repo), '--project', 'demo',
                                    '--identity', 'Pat', '--skills-dir', str(base / 'skills'), '--json'],
                           env=env, check=True, capture_output=True)
            decisions = repo / 'projects/demo/decisions'
            (decisions / 'plans.md').write_text(decision('demo', 'plans', body=body()), encoding='utf-8')
            cli = repo / 'scripts/cairn.py'
            command = [sys.executable, str(cli)]

            def run(*args, value=None):
                result = subprocess.run(command + list(args), input=json.dumps(value) if value else None,
                                        env=env, capture_output=True, encoding='utf-8', check=True)
                return json.loads(result.stdout)

            def files():
                return {p.relative_to(repo): p.read_bytes() for p in repo.rglob('*') if p.is_file()}

            def smoke():
                before = files()
                first = run('brief', '--project', 'demo', '--thread', THREAD, '--focus', 'pricing')
                self.assertEqual(schema_check.check(first, BRIEF_SCHEMA, BRIEF_SCHEMA), [])
                self.assertEqual([i['id'] for i in first['items']], ['plans'])
                self.assert_freshness(run('brief-check', '--project', 'demo', '--thread', THREAD, value=first),
                                      'fresh', 'unchanged', 'use_brief')
                self.assertEqual(files(), before)

            smoke()
            cli.unlink()
            subprocess.run(setup + ['upgrade', '--repository', str(repo), '--json'],
                           env=env, check=True, capture_output=True)
            self.assertIn('brief-check', run('status', '--project', 'demo')['capabilities'])
            smoke()
