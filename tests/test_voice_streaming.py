from app.services.streaming_turn_service import take_tts_chunks


def test_normal_opening_releases_at_word_target_without_waiting_for_sentence():
    text = "I really enjoyed hearing about your project "
    assert take_tts_chunks(text, allow_short_first_chunk=True,
                           first_chunk_max_words=5, natural_boundaries=True) == (
                               ["I really enjoyed hearing about"], "your project ")


def test_normal_opening_prefers_comma_after_four_words():
    assert take_tts_chunks("Hey macha I am here, ready to chat ",
                           allow_short_first_chunk=True, first_chunk_max_words=6,
                           natural_boundaries=True) == (
                               ["Hey macha I am here,"], "ready to chat ")


def test_normal_opening_caps_at_six_and_does_not_split_partial_word():
    text = "one two three four five si"
    assert take_tts_chunks(text, allow_short_first_chunk=True,
                          first_chunk_max_words=8, natural_boundaries=True) == ([], text)
    assert take_tts_chunks(text + "x ", allow_short_first_chunk=True,
                          first_chunk_max_words=8, natural_boundaries=True) == (
                              ["one two three four five six"], "")


def test_later_chunks_stay_long_and_preserve_all_words():
    text = " ".join(f"word{i}" for i in range(40)) + " "
    chunks, rest = take_tts_chunks(text, allow_short_first_chunk=True,
                                  first_chunk_max_words=6, natural_boundaries=True)
    assert [len(chunk.split()) for chunk in chunks] == [6, 25]
    assert " ".join(chunks + [rest]).split() == text.split()


def test_first_clause_releases_before_word_target() -> None:
    for boundary in (";", " \u2014"):
        buffer = f"You did great{boundary} now"
        chunks, remainder = take_tts_chunks(
            buffer, allow_short_first_chunk=True, first_chunk_max_words=6
        )
        assert chunks == [f"You did great{boundary}"]
        assert remainder == "now"


def test_first_clause_does_not_release_at_comma_or_unconfirmed_dash() -> None:
    for buffer in ("You did great, now", "You did great \u2014", "You did great;"):
        assert take_tts_chunks(
            buffer, allow_short_first_chunk=True, first_chunk_max_words=6
        ) == ([], buffer)


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
