"""M2.B2: replace_frozen_refs — frozen ref token → markdown footnote."""

import fnm_re_rs


def test_basic_note_ref():
    result = fnm_re_rs.replace_frozen_refs_json(
        "Some text {{NOTE_REF:fn-1}}.", "standard"
    )
    assert "[^fn-1]" in result
    assert "{{NOTE_REF" not in result


def test_endnote_normalized():
    result = fnm_re_rs.replace_frozen_refs_json(
        "Ref {{NOTE_REF:en-3}} here.", "standard"
    )
    assert "[^en-3]" in result


def test_fn_ref():
    result = fnm_re_rs.replace_frozen_refs_json(
        "{{FN_REF:fn-2}} end", "standard"
    )
    assert "[^fn-2]" in result


def test_en_ref_normalization():
    result = fnm_re_rs.replace_frozen_refs_json(
        "{{EN_REF:4}}", "standard"
    )
    assert "[^en-4]" in result


def test_whitespace_before_ref():
    result = fnm_re_rs.replace_frozen_refs_json(
        "text {{NOTE_REF:fn-1}}", "standard"
    )
    assert "[^fn-1]" in result


def test_no_mapping():
    result = fnm_re_rs.replace_frozen_refs_json(
        "plain text without refs", "standard"
    )
    assert result == "plain text without refs"


def test_legacy_mode():
    result = fnm_re_rs.replace_frozen_refs_json(
        "{{NOTE_REF:fn-1}} legacy", "legacy"
    )
    assert "[^fn-1]" in result


def test_multiple_refs():
    result = fnm_re_rs.replace_frozen_refs_json(
        "a {{NOTE_REF:fn-1}} b {{NOTE_REF:fn-2}} c {{NOTE_REF:en-3}}", "standard"
    )
    assert "[^fn-1]" in result
    assert "[^fn-2]" in result
    assert "[^en-3]" in result
