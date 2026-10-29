from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_screenshot_gate_covers_current_navigation_and_both_recording_surfaces():
    script = (ROOT / 'scripts/ci/capture-kiosk-screenshots.mjs').read_text(encoding='utf-8')
    for selector in ('.kiosk-home', '.admin-panel', '.case-ledger', '.identity-modal',
                     '.draft-rail', '.record-preview', '.record-review-panel', '.review-qa-units article'):
        assert selector in script, f'missing current-screen coverage: {selector}'
    for obsolete in ('.case-list-page', '.body-question .editable-question textarea', '.live-dialogue-panel'):
        assert obsolete not in script, f'screenshot gate still waits on removed UI: {obsolete}'
    assert '问答录入' in script and '定稿校验' in script
    assert "'admin-panel', 1920, 1080" in script
    assert "'interrogation', 1920, 1080" in script
    assert "'interrogation', 1920, 900" in script
    assert "'review-fragments', 1920, 1080" in script
    assert "'review-pending-qa', 1920, 900" in script


def test_fixture_checks_preserve_raw_evidence_and_unresolved_qa_actions():
    script = (ROOT / 'scripts/ci/capture-kiosk-screenshots.mjs').read_text(encoding='utf-8')
    for text in ('你什么时候到现场？', '你什么时候到现场的？', '晚上八点左右。',
                 '你把钥匙放到哪里去了？', '我放在门口鞋柜里了。', '新增为现场问答', '忽略此组问答'):
        assert text in script
    assert 'questionVisible && answerVisible && draftAnswerVisible' in script
    assert 'rawVisible && pendingCard' in script
