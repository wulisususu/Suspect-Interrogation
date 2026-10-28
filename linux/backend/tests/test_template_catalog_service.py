import json

import pytest
from sqlalchemy import select

from app.database.models import Case, CaseQuestion, Fact, QuestionRound
from app.database.session import init_database, make_engine, make_session_factory
from app.domain.errors import DomainError
from app.repositories import cases as case_repo


def database(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'catalog.db'}")
    init_database(engine)
    return make_session_factory(engine)()


def test_catalog_is_persistent_and_matches_six_frontend_contracts(tmp_path):
    from app.services.template_catalog_service import TemplateCatalogService

    with database(tmp_path) as db:
        service = TemplateCatalogService(db)
        catalog = service.catalog()
        assert len(catalog) == 6
        theft = next(x for x in catalog if x['id'] == 'theft-ebike')
        assert theft['title'] == '盗窃（电动车）'
        assert len(theft['elements']) == 6
        assert len(theft['presetQuestions']) == 6
        assert theft['learnedCount'] == 0
        assert theft['backendKey'] == 'THEFT_EBIKE_V1'
        assert all(x['backendKey'] for x in catalog)
        db.commit()
        assert service.catalog() == catalog


def test_selection_copies_snapshot_and_body_element_keys(tmp_path):
    from app.database.catalog_models import CaseTemplateSnapshot
    from app.services.template_catalog_service import TemplateCatalogService, get_case_elements

    with database(tmp_path) as db:
        case = case_repo.create(db, {})
        service = TemplateCatalogService(db)
        result = service.select(case.id, template_id='theft-ebike')
        questions = list(db.scalars(select(CaseQuestion).where(CaseQuestion.case_id == case.id, CaseQuestion.active.is_(True))))
        body = [q for q in questions if q.section_type == 'BODY']
        assert len(body) == 6
        assert all(q.element_key for q in body)
        assert all(q.element_key is None for q in questions if q.section_type != 'BODY')
        assert result['templateKey'] == 'THEFT_EBIKE_V1'
        assert len(get_case_elements(db, case.id)) == 6
        facts = {x.fact_key: x for x in db.scalars(select(Fact).where(Fact.case_id == case.id))}
        assert facts[body[0].element_key].status == 'pending'
        snapshot = db.get(CaseTemplateSnapshot, case.id).snapshot_json
        service.save_version('theft-ebike', structure={'elements': [{'key': 'changed', 'label': '新要素'}], 'questions': [{'key': 'new-q', 'text': '新问题？', 'elementKey': 'changed'}]})
        assert db.get(CaseTemplateSnapshot, case.id).snapshot_json == snapshot
        assert len([q for q in service.select(case.id, template_id='theft-ebike')['questions'] if q['sectionType'] == 'BODY']) == 6


def test_blank_preserves_fixed_sections_and_has_no_core_elements(tmp_path):
    from app.services.template_catalog_service import TemplateCatalogService, get_case_elements

    with database(tmp_path) as db:
        case = case_repo.create(db, {})
        service = TemplateCatalogService(db)
        result = service.select(case.id, blank=True)
        assert result['blank'] is True
        assert result['templateKey'] == 'BLANK_V1'
        assert get_case_elements(db, case.id) == []
        assert {q['sectionType'] for q in result['questions']} == {'OPENING', 'CLOSING'}
        assert len(result['questions']) == 9


def test_selection_refuses_to_discard_answers_or_draft_rounds(tmp_path):
    from app.services.template_catalog_service import TemplateCatalogService

    with database(tmp_path) as db:
        case = case_repo.create(db, {})
        service = TemplateCatalogService(db)
        selected = service.select(case.id, template_id='theft-ebike')
        question = db.get(CaseQuestion, next(q['id'] for q in selected['questions'] if q['sectionType'] == 'BODY'))
        question.formal_answer_text = '蓝色电动车'
        db.flush()
        with pytest.raises(DomainError) as error:
            service.select(case.id, template_id='traffic-simple')
        assert error.value.code == 'TEMPLATE_SELECTION_HAS_WORK'
        question.formal_answer_text = ''
        db.add(QuestionRound(id='round', case_id=case.id, case_question_id=question.id, round_no=1, actual_question_text=question.text, answer_text='草稿回答', answer_fragment_ids_json='[]', status='CLOSED'))
        db.flush()
        with pytest.raises(DomainError) as error:
            service.select(case.id, blank=True)
        assert error.value.code == 'TEMPLATE_SELECTION_HAS_WORK'


def test_disabled_template_cannot_be_selected_but_history_survives(tmp_path):
    from app.services.template_catalog_service import TemplateCatalogService

    with database(tmp_path) as db:
        service = TemplateCatalogService(db)
        case = case_repo.create(db, {})
        service.select(case.id, template_id='theft-ebike')
        service.set_active('theft-ebike', False)
        assert len(service.catalog()) == 5
        assert service.versions('theft-ebike')[0]['version'] == 1
        other = case_repo.create(db, {})
        with pytest.raises(DomainError) as error:
            service.select(other.id, template_id='theft-ebike')
        assert error.value.code == 'TEMPLATE_DISABLED'


def test_invalid_structure_is_rejected_before_creating_version(tmp_path):
    from app.services.template_catalog_service import TemplateCatalogService

    with database(tmp_path) as db:
        service = TemplateCatalogService(db)
        service.catalog()
        with pytest.raises(DomainError) as error:
            service.save_version('theft-ebike', structure={'elements': [{'key': 'time', 'label': '时间'}], 'questions': [{'key': 'q1', 'text': '何时？', 'elementKey': 'not-in-template'}]})
        assert error.value.code == 'INVALID_TEMPLATE_STRUCTURE'
        assert len(service.versions('theft-ebike')) == 1


def test_frozen_case_rejects_selection(tmp_path):
    from app.services.template_catalog_service import TemplateCatalogService

    with database(tmp_path) as db:
        case = case_repo.create(db, {})
        case.workflow_state = 'FROZEN'
        db.flush()
        with pytest.raises(DomainError) as error:
            TemplateCatalogService(db).select(case.id, template_id='theft-ebike')
        assert error.value.code == 'FORMAL_RECORD_FROZEN'


def test_unanswered_switch_keeps_single_fixed_sections_and_can_reorder(tmp_path):
    from app.services.template_catalog_service import TemplateCatalogService
    from app.services.template_workspace_service import TemplateWorkspaceService

    with database(tmp_path) as db:
        case = case_repo.create(db, {})
        catalog = TemplateCatalogService(db)
        first = catalog.select(case.id, template_id='theft-ebike')
        second = catalog.select(case.id, template_id='traffic-simple')
        assert len(second['questions']) == 14
        assert sum(q['sectionType'] == 'OPENING' for q in second['questions']) == 6
        assert not {q['id'] for q in first['questions'] if q['sectionType'] == 'BODY'} & {q['id'] for q in second['questions']}
        body_ids = [q['id'] for q in second['questions'] if q['sectionType'] == 'BODY']
        reordered = TemplateWorkspaceService(db).reorder(case.id, list(reversed(body_ids)))
        assert [q['id'] for q in reordered if q['sectionType'] == 'BODY'] == list(reversed(body_ids))


@pytest.mark.parametrize('structure', [
    {'elements': [{'key': 'test', 'label': {'bad': 'label'}}], 'questions': []},
    {'elements': [], 'questions': [{'key': 'q1', 'text': {'bad': 'text'}}]},
    {'elements': [{'key': 'contact', 'label': '模板字段'}], 'questions': []},
])
def test_structure_rejects_nontext_and_reserved_identity_fact_keys(tmp_path, structure):
    from app.services.template_catalog_service import TemplateCatalogService

    with database(tmp_path) as db:
        with pytest.raises(DomainError) as error:
            TemplateCatalogService(db).save_version('theft-ebike', structure=structure)
        assert error.value.code == 'INVALID_TEMPLATE_STRUCTURE'
