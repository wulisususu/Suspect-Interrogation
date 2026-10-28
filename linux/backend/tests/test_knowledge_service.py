import pytest

from app.database.session import init_database, make_engine, make_session_factory
from app.domain.errors import DomainError


def database(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'knowledge.db'}")
    init_database(engine)
    return make_session_factory(engine)()


def test_entry_versions_disable_and_delete_remove_it_from_guidance(tmp_path):
    from app.services.knowledge_service import KnowledgeService

    with database(tmp_path) as db:
        service = KnowledgeService(db)
        categories = service.categories()
        assert {c['name'] for c in categories} == {'问话要点', '法规条文', '取证规范', '安全提示'}
        row = service.create_entry(title='凤凰路', category_id=categories[0]['id'], content='核对准确地址', keywords=['凤凰路'])
        assert [x['id'] for x in service.entries(guidance=True)] == [row['id']]
        service.update_entry(row['id'], {'content': '核对道路与门牌', 'active': False})
        assert service.entries(guidance=True) == []
        assert [v['version'] for v in service.versions(row['id'])] == [2, 1]
        service.update_entry(row['id'], {'active': True})
        assert len(service.entries(guidance=True)) == 1
        service.delete_entry(row['id'])
        assert service.entries() == []
        versions = service.versions(row['id'])
        assert versions[0]['action'] == 'DELETE'
        assert versions[-1]['data']['content'] == '核对准确地址'


def test_category_management_and_validation(tmp_path):
    from app.services.knowledge_service import KnowledgeService

    with database(tmp_path) as db:
        service = KnowledgeService(db)
        category = service.create_category('案件专名')
        service.update_category(category['id'], '专名词表')
        assert service.categories()[-1]['name'] == '专名词表'
        with pytest.raises(DomainError):
            service.create_category('专名词表')
        row = service.create_entry(title='案发地点', category_id=category['id'], content='核对门牌')
        with pytest.raises(DomainError) as error:
            service.delete_category(category['id'])
        assert error.value.code == 'KNOWLEDGE_CATEGORY_IN_USE'
        service.delete_entry(row['id'])
        service.delete_category(category['id'])
        assert category['id'] not in [x['id'] for x in service.categories()]


def test_null_active_and_empty_patch_do_not_create_versions(tmp_path):
    from app.services.knowledge_service import KnowledgeService

    with database(tmp_path) as db:
        service = KnowledgeService(db)
        category = service.categories()[0]
        row = service.create_entry(title='核对', category_id=category['id'], content='核对要点')
        for patch in [{'active': None}, {}]:
            with pytest.raises(DomainError) as error:
                service.update_entry(row['id'], patch)
            assert error.value.code == 'INVALID_KNOWLEDGE_ENTRY'
        assert len(service.versions(row['id'])) == 1
        assert service.detail(row['id'])['active'] is True
