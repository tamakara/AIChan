import pytest

from hub_service.services.action_batch_parser import parse_action_batch


def test_parse_action_batch_extracts_actions_in_order() -> None:
    actions = parse_action_batch(
        batch_xml=(
            '<batch type="end">'
            '<message session_id="private_1">hello</message>'
            '<poke session_id="private_1" target_id="qq_2" />'
            '<recall session_id="private_1" message_id="11" />'
            "</batch>"
        ),
        expected_session_id="private_1",
    )

    assert [item.action_xml for item in actions] == [
        '<message session_id="private_1">hello</message>',
        '<poke session_id="private_1" target_id="qq_2" />',
        '<recall session_id="private_1" message_id="11" />',
    ]


@pytest.mark.parametrize(
    "batch_xml,error_text",
    [
        ("not xml", "valid xml"),
        ('<batch type="append"><message session_id="private_1">x</message></batch>', "batch.type"),
        ('<batch type="end"><unknown session_id="private_1" /></batch>', "unsupported tag"),
        ('<batch type="end"><message session_id="private_1"></message></batch>', "content"),
        ('<batch type="end"><poke session_id="private_1" /></batch>', "target_id"),
        ('<batch type="end"><recall session_id="private_1" /></batch>', "message_id"),
        ('<batch type="end"><message session_id="private_2">x</message></batch>', "session_id mismatch"),
    ],
)
def test_parse_action_batch_rejects_invalid_payload(batch_xml: str, error_text: str) -> None:
    with pytest.raises(ValueError, match=error_text):
        parse_action_batch(batch_xml=batch_xml, expected_session_id="private_1")
