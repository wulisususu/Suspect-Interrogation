"""知识条目引用链：依据文件 / 条款 / 文件版本 / 效力区间 / 取代关系，以及过期条目不进办案提示。"""

from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.database.session import init_database, make_engine, make_session_factory
from app.hardware_gateway.mock import MockHardwareGateway
from app.main import create_app
from app.services.knowledge_service import KnowledgeService

TODAY = date.today()
LAST_YEAR = (TODAY - timedelta(days=365)).isoformat()
YESTERDAY = (TODAY - timedelta(days=1)).isoformat()
NEXT_MONTH = (TODAY + timedelta(days=30)).isoformat()

LAW_BODY = '''# 盗窃数额认定

盗窃数额按被盗财物的市场价格认定。

## 建议问法

- 被盗的车是什么时候、花多少钱买的？
'''


def law_note(uid, title, *, extra=()):
    lines = ['---', f'uid: {uid}', f'title: {title}', 'category: 法规条文', 'kind: faq', 'status: verified',
             'keywords:', '  - 盗窃数额', 'source: raw/盗窃司法解释.pdf#第四条', *extra, '---', LAW_BODY]
    return '\n'.join(lines)


def write(root, relative, text):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def database(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'citations.db'}")
    init_database(engine)
    return make_session_factory(engine)()


def payload(response):
    body = response.json()
    assert body['ok'] is True, body
    return body['data']


def client(tmp_path):
    app = create_app(database_url=f"sqlite:///{tmp_path / 'citations-api.db'}",
                     hardware_gateway=MockHardwareGateway(simulated=True))
    return TestClient(app)


def test_vault_import_reads_citation_frontmatter_and_resolves_supersession(tmp_path):
    vault = tmp_path / 'vault'
    write(vault, 'raw/盗窃司法解释.pdf', '原件')
    write(vault, 'dict/faq/theft-2013.md', law_note('law-theft-2013', '盗窃数额认定（2013）', extra=(
        'source_document: 最高人民法院、最高人民检察院关于办理盗窃刑事案件适用法律若干问题的解释',
        'source_locator: 第四条第一款',
        'source_version: 法释〔2013〕8号',
        'effective_from: 2013-04-04',
        f'effective_until: {YESTERDAY}',
        'superseded_by: law-theft-new',
    )))
    write(vault, 'dict/faq/theft-new.md', law_note('law-theft-new', '盗窃数额认定（现行）', extra=(
        'source_document: 盗窃刑事案件司法解释',
        'source_locator: 第四条',
        'source_version: 修订版',
        f'effective_from: {YESTERDAY}',
    )))
    write(vault, 'dict/faq/broken.md', law_note('law-broken', '日期写错的条目', extra=(
        'effective_from: 2024/01/01',
        'superseded_by: law-missing',
    )).replace('raw/盗窃司法解释.pdf#第四条', 'raw/不存在.pdf'))

    with database(tmp_path) as db:
        service = KnowledgeService(db)
        report = service.import_vault(vault, dry_run=False)
        db.commit()
        assert len(report['added']) == 3 and report['rejected'] == []

        by_uid = {item['vaultUid']: item for item in service.entries()}
        old, new, broken = by_uid['law-theft-2013'], by_uid['law-theft-new'], by_uid['law-broken']
        assert old['sourceRef'] == 'raw/盗窃司法解释.pdf#第四条'
        assert old['sourceDocument'].startswith('最高人民法院')
        assert (old['sourceLocator'], old['sourceVersion']) == ('第四条第一款', '法释〔2013〕8号')
        assert (old['effectiveFrom'], old['effectiveUntil']) == ('2013-04-04', YESTERDAY)
        assert old['superseded'] is True
        assert (old['supersededById'], old['supersededByTitle']) == (new['id'], '盗窃数额认定（现行）')
        assert old['validity'] == 'superseded'
        assert new['validity'] == 'current' and new['superseded'] is False

        # 坏日期、找不到的原件、找不到的新版都只告警，不猜
        assert broken['effectiveFrom'] is None and broken['supersededById'] is None
        warnings = '\n'.join(report['warnings'])
        assert 'effective_from=2024/01/01' in warnings
        assert '原件不存在：raw/不存在.pdf' in warnings
        assert 'superseded_by=law-missing' in warnings
        assert not any('theft-new.md' in item for item in report['warnings'])

        # 引用链写进版本快照，可回溯每一版依据
        snapshot = service.versions(new['id'])[0]['data']
        assert (snapshot['sourceLocator'], snapshot['sourceVersion']) == ('第四条', '修订版')

        # 去掉取代关系后重导：标记与指向一起清掉
        write(vault, 'dict/faq/theft-2013.md', law_note('law-theft-2013', '盗窃数额认定（2013）'))
        service.import_vault(vault, dry_run=False)
        db.commit()
        old = service.detail(old['id'])
        assert (old['superseded'], old['supersededById'], old['sourceDocument']) == (False, None, None)
        assert old['validity'] == 'current'


def test_api_round_trips_citation_and_validates_it(tmp_path):
    with client(tmp_path) as http:
        category = payload(http.get('/api/v1/knowledge/categories'))[0]
        citation = {
            'sourceRef': 'raw/治安管理处罚法.pdf', 'sourceDocument': '中华人民共和国治安管理处罚法',
            'sourceLocator': '第四十九条', 'sourceVersion': '2012 修正', 'effectiveFrom': '2013-01-01',
        }
        created = payload(http.post('/api/v1/knowledge/entries', json={
            'title': '盗窃处罚', 'categoryId': category['id'], 'content': '正文', 'status': 'verified', **citation,
        }))
        fetched = payload(http.get(f"/api/v1/knowledge/entries/{created['id']}"))
        for key, value in citation.items():
            assert fetched[key] == value
        assert (fetched['effectiveUntil'], fetched['superseded'], fetched['validity']) == (None, False, 'current')

        successor = payload(http.post('/api/v1/knowledge/entries', json={
            'title': '盗窃处罚（新版）', 'categoryId': category['id'], 'content': '正文', 'status': 'verified',
            'sourceDocument': '中华人民共和国治安管理处罚法', 'sourceVersion': '2025 修订', 'effectiveFrom': YESTERDAY,
        }))
        updated = payload(http.patch(f"/api/v1/knowledge/entries/{created['id']}", json={
            'effectiveUntil': YESTERDAY, 'supersededById': successor['id'], 'sourceLocator': '第四十九条第一款',
        }))
        assert updated['version'] == 2
        assert (updated['superseded'], updated['supersededById'], updated['supersededByTitle']) == (
            True, successor['id'], '盗窃处罚（新版）')
        assert updated['validity'] == 'superseded'
        versions = payload(http.get(f"/api/v1/knowledge/entries/{created['id']}/versions"))
        assert [item['data']['sourceLocator'] for item in versions] == ['第四十九条第一款', '第四十九条']

        # 清空文字字段 / 撤销取代
        cleared = payload(http.patch(f"/api/v1/knowledge/entries/{created['id']}", json={
            'sourceVersion': '', 'superseded': False, 'effectiveUntil': None,
        }))
        assert (cleared['sourceVersion'], cleared['superseded'], cleared['supersededById']) == (None, False, None)
        assert cleared['validity'] == 'current'

        bad_window = http.patch(f"/api/v1/knowledge/entries/{created['id']}", json={'effectiveUntil': '2012-12-31'})
        assert bad_window.status_code == 400
        self_superseded = http.patch(f"/api/v1/knowledge/entries/{created['id']}", json={'supersededById': created['id']})
        assert self_superseded.status_code == 400
        unknown_successor = http.patch(f"/api/v1/knowledge/entries/{created['id']}", json={'supersededById': 'nope'})
        assert unknown_successor.status_code == 400
        assert http.patch(f"/api/v1/knowledge/entries/{created['id']}", json={'effectiveFrom': '2013-13-01'}).status_code == 422
        assert payload(http.get(f"/api/v1/knowledge/entries/{created['id']}"))['version'] == 3


def test_expired_superseded_and_future_entries_are_excluded_from_guidance(tmp_path):
    with client(tmp_path) as http:
        category = payload(http.get('/api/v1/knowledge/categories'))[0]

        def create(title, **citation):
            return payload(http.post('/api/v1/knowledge/entries', json={
                'title': title, 'categoryId': category['id'], 'content': LAW_BODY, 'keywords': ['盗窃数额'],
                'status': 'verified', **citation,
            }))

        current = create('现行盗窃数额', effectiveFrom=LAST_YEAR)
        expired = create('已失效盗窃数额', effectiveFrom='2013-04-04', effectiveUntil=TODAY.isoformat())
        future = create('未生效盗窃数额', effectiveFrom=NEXT_MONTH)
        replaced = create('被取代盗窃数额', supersededById=current['id'])

        admin = {item['id']: item['validity'] for item in payload(http.get('/api/v1/knowledge/entries'))}
        assert admin == {current['id']: 'current', expired['id']: 'expired',
                         future['id']: 'not_yet_effective', replaced['id']: 'superseded'}

        matched = payload(http.get('/api/v1/knowledge/guidance/match', params={'q': '盗窃数额怎么认定'}))
        assert [item['id'] for item in matched] == [current['id']]
        listed = payload(http.get('/api/v1/knowledge/guidance'))
        assert [item['id'] for item in listed] == [current['id']]
        drafts = payload(http.post('/api/v1/knowledge/draft-questions', json={'q': '盗窃数额怎么认定'}))
        assert {item['entryId'] for item in drafts} == {current['id']}
        assert drafts[0]['sourceDocument'] is None and 'sourceLocator' in drafts[0]


def test_validity_follows_the_service_clock(tmp_path):
    with database(tmp_path) as db:
        service = KnowledgeService(db, today=date(2026, 1, 1))
        category = service.categories()[0]['id']
        entry = service.create_entry(title='跨年生效的条目', category_id=category, content='盗窃数额', keywords=['盗窃数额'],
                                     status='verified', citation={'effectiveFrom': '2026-01-01', 'effectiveUntil': '2027-01-01'})
        assert entry['validity'] == 'current'
        assert [item['id'] for item in service.guidance_for(text='盗窃数额')] == [entry['id']]
        assert KnowledgeService(db, today=date(2025, 12, 31)).guidance_for(text='盗窃数额') == []
        # 失效日期当天起不再适用
        late = KnowledgeService(db, today=date(2027, 1, 1))
        assert late.guidance_for(text='盗窃数额') == []
        assert late.detail(entry['id'])['validity'] == 'expired'
