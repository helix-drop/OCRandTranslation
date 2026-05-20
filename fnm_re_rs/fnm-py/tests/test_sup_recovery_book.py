"""M2.B4: sup_recovery — recover_book / has_explicit_sup."""

import json

import fnm_re_rs


def test_has_explicit_sup_html():
    assert fnm_re_rs.has_explicit_sup_json("<sup>1</sup>", "1")
    assert fnm_re_rs.has_explicit_sup_json("<sup> 42 </sup>", "42")
    assert fnm_re_rs.has_explicit_sup_json("text <sup>10</sup> more", "10")


def test_has_explicit_sup_bracket():
    assert fnm_re_rs.has_explicit_sup_json("[^1]", "1")
    assert fnm_re_rs.has_explicit_sup_json("ref [^23]", "23")


def test_has_explicit_sup_none():
    assert not fnm_re_rs.has_explicit_sup_json("plain text", "1")
    assert not fnm_re_rs.has_explicit_sup_json("", "1")
    assert not fnm_re_rs.has_explicit_sup_json("text123", "12")


def test_recover_book_empty():
    result = json.loads(fnm_re_rs.recover_book_json(json.dumps([]), ""))
    assert isinstance(result, dict)
    assert len(result) == 0


def test_recover_book_with_fblocks():
    pages = [
        {
            "bookPage": 1,
            "markdown": "Some text.",
            "fnBlocks": [{"marker": "1"}, {"marker": "2"}],
        }
    ]
    result = json.loads(fnm_re_rs.recover_book_json(json.dumps(pages), ""))
    assert isinstance(result, dict)
