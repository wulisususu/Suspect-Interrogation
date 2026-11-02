from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_screenshot_gate_covers_current_navigation_and_both_recording_surfaces():
    script = (ROOT / 'scripts/ci/capture-kiosk-screenshots.mjs').read_text(encoding='utf-8')
    for selector in ('.kiosk-home', '.admin-panel', '.case-ledger', '.identity-modal',
                     '.draft-rail', '.record-preview', '.review-layout', '.review-checks li'):
        assert selector in script, f'missing current-screen coverage: {selector}'
    for obsolete in ('.case-list-page', '.body-question .editable-question textarea', '.live-dialogue-panel',
                     "clickSelector(client, '.review-resolve')", '.review-qa-units article'):
        assert obsolete not in script, f'screenshot gate still waits on removed UI: {obsolete}'
    assert '问答录入' in script and '定稿校验' in script
    assert "'admin-panel', 1920, 1080" in script
    assert "'interrogation', 1920, 1080" in script
    assert "'interrogation', 1920, 900" in script
    assert "'review', 1920, 1080" in script
    assert "'review', 1920, 900" in script


def test_review_fixture_hints_leftovers_without_a_triage_dialog():
    """④ 定稿校验不再有逐条确认 / 丢弃转写的浮层；没进入笔录的转写只提示条数。"""
    script = (ROOT / 'scripts/ci/capture-kiosk-screenshots.mjs').read_text(encoding='utf-8')
    for text in ('你什么时候到现场？', '晚上八点左右。', '未进入笔录的录音转写', '4 段转写', '1 组问答'):
        assert text in script
    assert 'questionVisible && answerVisible && draftAnswerVisible' in script
    assert 'leftoverHint && noTriage' in script
