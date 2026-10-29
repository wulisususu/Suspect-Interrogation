import json

import pytest

from app.database.models import AuditLog
from app.database.session import init_database, make_engine, make_session_factory


def database(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'vault.db'}")
    init_database(engine)
    return make_session_factory(engine)()


def note(uid, title, body, *, category='问话要点', kind='faq', status='verified',
         keywords=(), source=None, corrections=None):
    lines = ['---', f'uid: {uid}', f'title: {title}', f'category: {category}', f'kind: {kind}',
             f'status: {status}']
    if keywords:
        lines.append('keywords:')
        lines.extend(f'  - {item}' for item in keywords)
    if source:
        lines.append(f'source: {source}')
    if corrections:
        lines.append('corrections:')
        for item in corrections:
            lines.append(f'  - wrong: {item[0]}')
            lines.append(f'    right: {item[1]}')
    lines.append('---')
    lines.append(body)
    return '\n'.join(lines)


def write(root, relative, text):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    return path


def seed_vault(root):
    write(root, 'dict/faq/time.md', note(
        'faq-time', '案发时间核对要点', '# 时间\n\n## 建议问法\n\n- 这件事是哪一天、大概几点发生的？\n- 当时是白天还是天黑以后？',
        keywords=['案发时间', '时间'], source='raw/规范.md'))
    write(root, 'dict/faq/station.md', note(
        'faq-station', '辖区派出所称谓', '# 派出所\n\n紫琅湖派出所。',
        keywords=['派出所'], source='raw/规范.md', corrections=[('死老虎派出所', '紫琅湖派出所')]))
    write(root, 'wiki/station.md', note(
        'wiki-station', '紫琅湖派出所', '# 紫琅湖派出所\n\n参见 [[案发时间核对要点]]。', kind='wiki'))
    write(root, 'raw/规范.md', '原始资料，不导入')


def test_import_creates_entries_versions_links_and_corrections(tmp_path):
    from app.services.knowledge_service import KnowledgeService

    vault = tmp_path / 'vault'
    seed_vault(vault)
    with database(tmp_path) as db:
        service = KnowledgeService(db)
        report = service.import_vault(vault, dry_run=False, actor_id='038291')
        db.commit()

        assert len(report['added']) == 3
        assert report['rejected'] == []
        titles = {item['title'] for item in service.entries()}
        assert titles == {'案发时间核对要点', '辖区派出所称谓', '紫琅湖派出所'}

        time_entry = next(item for item in service.entries() if item['vaultUid'] == 'faq-time')
        assert time_entry['origin'] == 'vault'
        assert time_entry['status'] == 'verified'
        assert time_entry['sourceRef'] == 'raw/规范.md'
        assert time_entry['keywords'] == ['案发时间', '时间']
        assert [item['version'] for item in service.versions(time_entry['id'])] == [1]
        assert service.versions(time_entry['id'])[0]['action'] == 'IMPORT_CREATE'

        station_entry = service.entries()
        assert any(item['kind'] == 'wiki' for item in station_entry)
        links = service.links(next(item['id'] for item in station_entry if item['vaultUid'] == 'wiki-station'))
        assert links['outgoing'][0]['targetTitle'] == '案发时间核对要点'
        assert links['outgoing'][0]['resolved'] is True

        corrections = service.term_corrections()
        assert [(item['wrong'], item['right']) for item in corrections] == [('死老虎派出所', '紫琅湖派出所')]

        actions = {row.action for row in db.query(AuditLog).all()}
        assert 'KNOWLEDGE_IMPORT' in actions
        assert 'KNOWLEDGE_IMPORT_CREATE' in actions


def test_second_import_is_idempotent_and_dry_run_writes_nothing(tmp_path):
    from app.services.knowledge_service import KnowledgeService

    vault = tmp_path / 'vault'
    seed_vault(vault)
    with database(tmp_path) as db:
        service = KnowledgeService(db)
        service.import_vault(vault, dry_run=True)
        assert service.entries() == []
        assert service.sync_runs() == []

        service.import_vault(vault, dry_run=False)
        db.commit()
        before = {item['id']: item['version'] for item in service.entries()}

        report = service.import_vault(vault, dry_run=False)
        db.commit()
        assert len(report['unchanged']) == 3
        assert report['added'] == [] and report['updated'] == []
        after = {item['id']: item['version'] for item in service.entries()}
        assert before == after
        assert service.term_corrections()[0]['active'] is True

        dry = service.import_vault(vault, dry_run=True)
        assert len(dry['unchanged']) == 3


def test_changed_file_updates_version_and_deleted_file_disables(tmp_path):
    from app.services.knowledge_service import KnowledgeService

    vault = tmp_path / 'vault'
    seed_vault(vault)
    with database(tmp_path) as db:
        service = KnowledgeService(db)
        service.import_vault(vault, dry_run=False)
        db.commit()
        entry = next(item for item in service.entries() if item['vaultUid'] == 'faq-time')

        write(vault, 'dict/faq/time.md', note(
            'faq-time', '案发时间核对要点', '# 时间\n\n## 建议问法\n\n- 具体是哪一天？',
            keywords=['案发时间'], source='raw/规范.md'))
        report = service.import_vault(vault, dry_run=False)
        db.commit()
        assert [item['uid'] for item in report['updated']] == ['faq-time']
        updated = service.detail(entry['id'])
        assert updated['version'] == 2
        assert '具体是哪一天' in updated['content']
        assert [item['action'] for item in service.versions(entry['id'])] == ['IMPORT_UPDATE', 'IMPORT_CREATE']

        (vault / 'dict/faq/station.md').unlink()
        report = service.import_vault(vault, dry_run=False)
        db.commit()
        assert [item['uid'] for item in report['disabled']] == ['faq-station']
        disabled = next(item for item in service.entries(active=False) if item['vaultUid'] == 'faq-station')
        assert disabled['active'] is False
        # 停用后不再出现在 guidance 中
        assert all(item['vaultUid'] != 'faq-station' for item in service.entries(guidance=True))
        # 纠错项随条目停用
        assert all(item['wrong'] != '死老虎派出所' for item in service.term_corrections(active=True))


def test_manual_entry_with_same_path_is_a_conflict_not_overwrite(tmp_path):
    from app.services.knowledge_service import KnowledgeService

    vault = tmp_path / 'vault'
    seed_vault(vault)
    with database(tmp_path) as db:
        service = KnowledgeService(db)
        category = service.categories()[0]
        manual = service.create_entry(title='手工维护的条目', category_id=category['id'],
                                      content='系统内编辑', keywords=['派出所'])
        row = service._entry(manual['id'])
        row.source_path = 'dict/faq/station.md'
        row.origin = 'manual'
        db.commit()

        report = service.import_vault(vault, dry_run=False)
        db.commit()
        assert [item['path'] for item in report['conflicts']] == ['dict/faq/station.md']
        assert service.detail(manual['id'])['content'] == '系统内编辑'
        assert all(item['title'] != '辖区派出所称谓' for item in service.entries())


def test_invalid_notes_are_rejected_with_reason(tmp_path):
    from app.services.knowledge_service import KnowledgeService

    vault = tmp_path / 'vault'
    write(vault, 'dict/faq/no-uid.md', '---\ntitle: 没有 uid\n---\n正文')
    write(vault, 'dict/faq/bad-uid.md', '---\nuid: Bad UID!\ntitle: 非法 uid\n---\n正文')
    write(vault, 'dict/faq/dup-a.md', note('faq-dup', '重复 A', '正文 A'))
    write(vault, 'dict/faq/dup-b.md', note('faq-dup', '重复 B', '正文 B'))
    write(vault, 'dict/faq/no-body.md', '---\nuid: faq-empty\ntitle: 空正文\n---\n')
    with database(tmp_path) as db:
        service = KnowledgeService(db)
        report = service.import_vault(vault, dry_run=False)
        assert report['added'] and len(report['rejected']) >= 4
        reasons = ' '.join(item['reason'] for item in report['rejected'])
        assert '缺少 uid' in reasons
        assert 'uid 不合法' in reasons
        assert '重复' in reasons
        assert '正文为空' in reasons


def test_full_text_search_handles_three_and_two_character_queries(tmp_path):
    from app.services.knowledge_service import KnowledgeService

    vault = tmp_path / 'vault'
    seed_vault(vault)
    with database(tmp_path) as db:
        service = KnowledgeService(db)
        service.import_vault(vault, dry_run=False)
        db.commit()
        assert [item['title'] for item in service.entries(query='紫琅湖')]
        # 2 字查询走 LIKE 兜底（trigram 需要 ≥3 字）
        assert any(item['title'] == '辖区派出所称谓' for item in service.entries(query='派出'))


def test_guidance_and_draft_questions_use_verified_entries_with_source(tmp_path):
    from app.services.knowledge_service import KnowledgeService

    vault = tmp_path / 'vault'
    seed_vault(vault)
    write(vault, 'dict/faq/pending.md', note(
        'faq-pending', '待确认的说法', '# 待确认\n\n这条还没核实。', status='pending', keywords=['派出所']))
    with database(tmp_path) as db:
        service = KnowledgeService(db)
        service.import_vault(vault, dry_run=False)
        db.commit()

        matches = service.guidance_for(text='派出所', limit=5)
        assert matches
        assert all(item['status'] == 'verified' for item in matches)
        assert any(item['sourceRef'] for item in matches if item['vaultUid'])
        assert matches[0]['matchReasons']

        drafts = service.draft_questions(text=None, limit=2)
        if drafts:
            assert all('entryVersion' in item for item in drafts)


def test_status_filter_and_export_corrections_format(tmp_path):
    from app.services.knowledge_service import KnowledgeService

    vault = tmp_path / 'vault'
    seed_vault(vault)
    with database(tmp_path) as db:
        service = KnowledgeService(db)
        service.import_vault(vault, dry_run=False)
        db.commit()
        assert all(item['status'] == 'verified' for item in service.entries(status='verified'))
        assert service.entries(status='pending') == []

        exported = service.export_corrections()
        rules = exported['corrections']['rules']
        assert rules and rules[0]['wrong'] and rules[0]['right']
        assert set(rules[0]) == {'wrong', 'right', 'note', 'enabled'}
        assert exported['hotwords'] == ['紫琅湖派出所']
        json.dumps(exported)  # 必须可序列化


def test_term_correction_conflict_requires_explicit_replace(tmp_path):
    from app.domain.errors import DomainError
    from app.services.knowledge_service import KnowledgeService

    with database(tmp_path) as db:
        service = KnowledgeService(db)
        service.upsert_term_correction(wrong='死老虎派出所', right='紫琅湖派出所')
        with pytest.raises(DomainError) as error:
            service.upsert_term_correction(wrong='死老虎派出所', right='别的所')
        assert error.value.code == 'TERM_CORRECTION_EXISTS'
        replaced = service.upsert_term_correction(wrong='死老虎派出所', right='别的所', replace=True)
        assert replaced['right'] == '别的所'
        assert service.lookup_corrections('今天去死老虎派出所报案')[0]['right'] == '别的所'
