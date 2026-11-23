"""Untrusted XDF limits; all fixtures are synthetic."""
import pytest

from guzzionboard.maps import (
    MAX_XDF_BYTES,
    Embedded,
    XdfError,
    XdfFile,
    eval_math,
    read_xdf_bytes,
)


def test_xdf_forbids_entity_declarations_and_external_dtd():
    for prefix in ('<!DOCTYPE XDFFORMAT [<!ENTITY x "hello">]>',
                   '<!DOCTYPE XDFFORMAT SYSTEM "file:///etc/passwd">'):
        with pytest.raises(XdfError, match='DTD and entity'):
            XdfFile.from_string(prefix + '<XDFFORMAT><XDFHEADER><deftitle>&x;</deftitle></XDFHEADER></XDFFORMAT>')
    assert XdfFile.from_string('<XDFFORMAT><XDFHEADER><deftitle>A &amp; B</deftitle></XDFHEADER><XDFCONSTANT><title>ok</title><EMBEDDEDDATA mmedaddress="0"/></XDFCONSTANT></XDFFORMAT>').title == 'A & B'


def test_untrusted_xdf_size_depth_and_node_limits(tmp_path):
    path=tmp_path/'huge.xdf'; path.write_bytes(b'x'*(MAX_XDF_BYTES+1))
    with pytest.raises(XdfError, match='8 MiB'): read_xdf_bytes(path)
    with pytest.raises(XdfError, match='8 MiB'): XdfFile.from_file(path)
    with pytest.raises(XdfError, match='8 MiB'): XdfFile.from_string('x'*(MAX_XDF_BYTES+1))
    with pytest.raises(XdfError, match='structure'):
        XdfFile.from_string('<x>'*65 + '</x>'*65)
    with pytest.raises(XdfError, match='structure'):
        XdfFile.from_string('<x>' + '<a/>'*100000 + '</x>')


def test_oversize_layouts_are_refused_before_allocating():
    with pytest.raises(XdfError, match='dimensions'):
        Embedded(0,rows=65536,cols=65536).positions(0)
    text='''<XDFFORMAT><XDFHEADER/><XDFTABLE><title>Bad</title>
    <XDFAXIS id="x"><indexcount>999999999</indexcount></XDFAXIS>
    <XDFAXIS id="z"><EMBEDDEDDATA mmedaddress="0"/></XDFAXIS>
    </XDFTABLE><XDFCONSTANT><title>ok</title><EMBEDDEDDATA mmedaddress="0"/></XDFCONSTANT></XDFFORMAT>'''
    xdf=XdfFile.from_string(text)
    assert not xdf.tables and 'axis exceeds' in xdf.unsupported[0]['reason']
    with pytest.raises(XdfError, match='invalid XDF integer'):
        XdfFile.from_string('<XDFFORMAT><XDFHEADER><REGION size="what"/></XDFHEADER></XDFFORMAT>')


@pytest.mark.parametrize('equation', ['X,1','X//2','X**2','1'*257])
def test_unsupported_math_never_crashes_or_uses_python_only_syntax(equation):
    with pytest.raises(XdfError): eval_math(equation,1)


def test_nonfinite_math_result_is_rejected():
    with pytest.raises(XdfError, match='non-finite'):
        eval_math('X*' + '9'*120 + '.0', 1e200)


def test_the_equation_is_not_evaluated_as_python():
    """A regression guard for the sandbox, not just for the allowlist.

    ``eval_math`` used ``eval`` behind a regex allowlist. Even with the
    allowlist in place, one regex hole would have been arbitrary code
    execution inside the server, so the evaluator now walks a parsed tree
    against a fixed arithmetic table and never calls ``eval`` at all.
    """
    import inspect

    source = inspect.getsource(__import__('guzzionboard.maps', fromlist=['eval_math']))
    assert 'eval(' not in source.replace('eval_math(', '')

    for attempt in ("__import__('os').system('true')", 'X.__class__',
                    '(lambda: 1)()', '[x for x in (1,)]', 'globals()',
                    'X if 1 else 2', 'X and 1', 'X or 1', 'not X'):
        with pytest.raises(XdfError):
            eval_math(attempt, 1)


def test_the_documented_arithmetic_still_works():
    assert eval_math('X/4096', 8192) == 2.0
    assert eval_math('(X-100)*0.1', 300) == pytest.approx(20.0)
    assert eval_math('X>>4', 256) == 16.0
    assert eval_math('0x1000/16', 0) == 256.0
    assert eval_math('-X+10', 4) == 6.0
