from hub_service.services.session_runner import _merge_messages


def test_merge_messages_preserves_message_order() -> None:
    merged = _merge_messages([
        '<messages><message id="1"><text>a</text></message></messages>',
        '<messages><message id="2"><text>b</text></message></messages>',
    ])
    assert merged.index('id="1"') < merged.index('id="2"')
