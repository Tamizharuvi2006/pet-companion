from app.services.streaming_turn_service import take_tts_chunks


def test_first_phrase_uses_requested_whole_word_target() -> None:
    words = "one two three four five six seven eight nine ten "
    for target in (4, 6, 8):
        chunks, remainder = take_tts_chunks(
            words,
            allow_short_first_chunk=True,
            first_chunk_max_words=target,
        )
        assert len(chunks) == 1
        assert len(chunks[0].split()) == target
        assert len(remainder.split()) == 10 - target


def test_first_phrase_waits_for_a_complete_word_boundary() -> None:
    chunks, remainder = take_tts_chunks(
        "one two three four five six",
        allow_short_first_chunk=True,
        first_chunk_max_words=6,
    )
    assert chunks == []
    assert remainder == "one two three four five six"


def test_first_phrase_prefers_a_natural_sentence_boundary() -> None:
    chunks, remainder = take_tts_chunks(
        "Hello there! I am Bella today ",
        allow_short_first_chunk=True,
        first_chunk_max_words=6,
    )
    assert chunks == ["Hello there!"]
    assert remainder.strip() == "I am Bella today"


def test_first_phrase_target_can_be_benchmarked_at_four_six_and_eight_words() -> None:
    text = "one two three four five six seven eight nine ten "
    observed = {}
    for target in (4, 6, 8):
        chunks, _ = take_tts_chunks(
            text,
            allow_short_first_chunk=True,
            first_chunk_max_words=target,
        )
        observed[target] = len(chunks[0].split())
    assert observed == {4: 4, 6: 6, 8: 8}
