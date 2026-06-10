from hub_service.services.media_storage import _media_mime


def test_media_mime_prefers_video_extension_over_generic_response_mime() -> None:
    mime = _media_mime(
        name="clip.mp4",
        url="https://example.test/download",
        response_mime="application/octet-stream",
        segment_type="video",
    )

    assert mime == "video/mp4"


def test_media_mime_uses_video_segment_default_when_name_has_no_extension() -> None:
    mime = _media_mime(
        name="video-0",
        url="https://example.test/download",
        response_mime="application/octet-stream",
        segment_type="video",
    )

    assert mime == "video/mp4"
