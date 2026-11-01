from fastapi.testclient import TestClient

from app.hardware_gateway.mock import MockHardwareGateway
from app.main import create_app
from app.runtime_settings import RuntimeSettings


VAULT_NOTE = '''---
uid: faq-station
title: 辖区派出所称谓
category: 问话要点
kind: faq
status: verified
keywords:
  - 派出所
source: raw/规范.md
corrections:
  - wrong: 死老虎派出所
    right: 紫琅湖派出所
---
# 派出所

紫琅湖派出所。

## 建议问法

- 你报的是哪个派出所？
'''


def build_vault(tmp_path):
    root = tmp_path / 'vault'
    (root / 'dict' / 'faq').mkdir(parents=True)
    (root / 'dict' / 'faq' / 'station.md').write_text(VAULT_NOTE, encoding='utf-8')
    return root


def payload(response):
    body = response.json()
    assert body['ok'] is True, body
    return body['data']


def client(tmp_path):
    app = create_app(database_url=f"sqlite:///{tmp_path / 'knowledge-api.db'}",
                     hardware_gateway=MockHardwareGateway(simulated=True),
                     runtime_settings=RuntimeSettings(knowledge_vault_dir=tmp_path / 'vault'))
    return TestClient(app)


def test_import_dry_run_apply_and_query_surfaces(tmp_path):
    root = build_vault(tmp_path)
    with client(tmp_path) as http:
        dry = payload(http.post('/api/v1/knowledge/import', json={'dryRun': True}))
        assert dry['dryRun'] is True
        assert len(dry['added']) == 1
        assert payload(http.get('/api/v1/knowledge/entries')) == []

        applied = payload(http.post('/api/v1/knowledge/import', json={'dryRun': False}))
        assert applied['runId']
        entries = payload(http.get('/api/v1/knowledge/entries'))
        assert len(entries) == 1
        assert entries[0]['origin'] == 'vault'
        assert entries[0]['sourceRef'] == 'raw/规范.md'
        assert entries[0]['status'] == 'verified'

        matches = payload(http.get('/api/v1/knowledge/guidance/match', params={'q': '派出所'}))
        assert matches and matches[0]['title'] == '辖区派出所称谓'
        assert matches[0]['sourceRef'] == 'raw/规范.md'
        assert matches[0]['matchReasons']

        drafts = payload(http.post('/api/v1/knowledge/draft-questions', json={'limit': 2}))
        assert any('派出所' in item['text'] for item in drafts)

        runs = payload(http.get('/api/v1/knowledge/import/runs'))
        assert len(runs) == 1 and runs[0]['added'] == 1

        links = payload(http.get(f"/api/v1/knowledge/entries/{entries[0]['id']}/links"))
        assert links['outgoing'] == []


def test_term_corrections_crud_and_lookup(tmp_path):
    root = build_vault(tmp_path)
    with client(tmp_path) as http:
        payload(http.post('/api/v1/knowledge/import', json={'dryRun': False}))
        items = payload(http.get('/api/v1/knowledge/term-corrections'))
        assert [(item['wrong'], item['right']) for item in items] == [('死老虎派出所', '紫琅湖派出所')]

        hits = payload(http.get('/api/v1/knowledge/term-corrections/lookup',
                                params={'text': '今天去死老虎派出所报案'}))
        assert hits[0]['right'] == '紫琅湖派出所'

        created = payload(http.post('/api/v1/knowledge/term-corrections',
                                    json={'wrong': '紫廊湖', 'right': '紫琅湖'}))
        assert created['active'] is True
        patched = payload(http.patch(f"/api/v1/knowledge/term-corrections/{created['id']}",
                                     json={'active': False}))
        assert patched['active'] is False

        exported = payload(http.get('/api/v1/knowledge/term-corrections/export'))
        assert exported['hotwords'] == ['紫琅湖派出所']
        assert all(set(rule) == {'wrong', 'right', 'note', 'enabled'}
                   for rule in exported['corrections']['rules'])


def test_entry_crud_requires_known_fields_and_keeps_versions(tmp_path):
    with client(tmp_path) as http:
        category = payload(http.get('/api/v1/knowledge/categories'))[0]
        created = payload(http.post('/api/v1/knowledge/entries', json={
            'title': '手工条目', 'categoryId': category['id'], 'content': '正文', 'keywords': ['核对'],
            'status': 'verified',
        }))
        assert created['origin'] == 'manual' and created['version'] == 1

        rejected = http.post('/api/v1/knowledge/entries', json={
            'title': '多余字段', 'categoryId': category['id'], 'content': '正文', 'unexpected': 1,
        })
        assert rejected.status_code == 422

        updated = payload(http.patch(f"/api/v1/knowledge/entries/{created['id']}",
                                     json={'content': '新的正文', 'status': 'pending'}))
        assert updated['version'] == 2 and updated['status'] == 'pending'
        versions = payload(http.get(f"/api/v1/knowledge/entries/{created['id']}/versions"))
        assert [item['version'] for item in versions] == [2, 1]

        deleted = payload(http.delete(f"/api/v1/knowledge/entries/{created['id']}"))
        assert deleted['deleted'] is True
        assert payload(http.get('/api/v1/knowledge/entries')) == []


def test_import_rejects_client_chosen_root_and_symlinked_notes(tmp_path):
    root = build_vault(tmp_path)
    outside = tmp_path / 'outside'
    (outside / 'secret').mkdir(parents=True)
    (outside / 'secret' / 'leak.md').write_text(VAULT_NOTE.replace('faq-station', 'faq-leak'), encoding='utf-8')
    (root / 'dict' / 'faq' / 'leak.md').symlink_to(outside / 'secret' / 'leak.md')
    with client(tmp_path) as http:
        rejected = http.post('/api/v1/knowledge/import', json={'root': str(outside), 'dryRun': True})
        assert rejected.status_code == 400
        assert rejected.json()['code'] == 'KNOWLEDGE_IMPORT_ROOT_FIXED'

        report = payload(http.post('/api/v1/knowledge/import', json={'dryRun': True}))
        assert len(report['added']) == 1
        assert [item['path'] for item in report['rejected']] == ['dict/faq/leak.md']
