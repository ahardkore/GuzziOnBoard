"""Synthetic HTML and network tests; no BikeStudio live retrieval in sandbox."""
import email.message
from types import SimpleNamespace
import pytest
from guzzionboard import bikestudio as bs
from guzzionboard.server import Api
from guzzionboard.workstation import Workstation

INDEX = '''<html><body><section><h2>Honda</h2><ul>
<li><a href="/ecu/m/honda-beat-110?lang=en" title="BeAT eSP, BeAT Street">BeAT <b>110</b> (8)</a></li>
<li><a href="https://bikestudio.io/ecu/m/yamaha-nmax-new?lang=en">NMAX NEW (13)</a></li>
<li><a href="https://evil.test/ecu/m/honda-bad?lang=en">Not a source</a></li>
<li><a href="/ecu/m/honda-beat-110?lang=en">Duplicate</a></li>
</ul><script><a href="/ecu/m/honda-evil">Fake</a></script></section></body></html>'''
MODEL = '''<html><table><thead><tr><th>ECU part number</th><th>Years</th><th>cc</th><th>Market</th></tr></thead><tbody>
<tr><td><a href="/ecu/30400-k81a-n11?lang=en">30400-K81A-N11</a></td><td>2018–2019</td><td>108</td><td>Indonesia</td></tr>
<tr><td><a href="https://bikestudio.io/ecu/30400-k81a-n12?lang=en"><b>30400-K81A-N12</b></a></td><td>–</td><td>108</td><td>—</td></tr>
</tbody></table><table><tr><td><a href="/ecu/extra">Other</a></td><td>1</td><td>2</td></tr></table></html>'''


class Response:
    def __init__(self, body, mime='text/html', status=200):
        self.body, self.status = body, status
        self.headers = email.message.Message(); self.headers['Content-Type'] = mime
    def read(self, n): return self.body[:n]
    def __enter__(self): return self
    def __exit__(self, *args): pass


def test_index_keeps_only_source_model_links_and_text():
    found = bs.parse_index(INDEX)
    assert [m['slug'] for m in found] == ['honda-beat-110', 'yamaha-nmax-new']
    assert found[0]['label'] == 'BeAT 110 (8)' and found[0]['aliases'] == 'BeAT eSP, BeAT Street'
    with pytest.raises(bs.BikeStudioError): bs.parse_index('<p>No matches</p>')


def test_table_headers_urls_and_missing_values():
    rows = bs.parse_model(MODEL)
    assert len(rows) == 2
    assert rows[0] == {'part':'30400-K81A-N11','part_slug':'30400-k81a-n11', 'years':'2018–2019','cc':'108','market':'Indonesia'}
    assert rows[1]['years'] == '' and rows[1]['market'] == ''
    unrelated = '<table><tr><td><a href=\"/ecu/other\">OTHER</a></td><td>2018</td><td>108</td><td>Asia</td></tr></table>'
    assert bs.parse_model(MODEL + unrelated) == rows
    bad_row = '<tr><td><a href="https://evil.test/ecu/other">BADDATA</a></td><td>2018</td><td>108</td><td>Asia</td></tr>'
    with pytest.raises(bs.BikeStudioError, match='rows were not recognized'):
        bs.parse_model(MODEL.replace('</tbody>', bad_row + '</tbody>'))
    with pytest.raises(bs.BikeStudioError, match='rows were not recognized'):
        bs.parse_model(MODEL.replace('<td>Indonesia</td>', ''))
    with pytest.raises(bs.BikeStudioError): bs.parse_model(MODEL.replace('ECU part number','Changed column'))
    assert not bs._path('https://bikestudio.io.evil.test/ecu/x')
    assert not bs._path('//bikestudio.io/ecu/x')
    assert not bs._path('https://user@bikestudio.io/ecu/x')
    assert not bs._path('/ecu/x?lang=en&other=1')


def test_fetch_restricts_address_and_bounds_response(monkeypatch):
    called = []
    class Opener:
        def open(self, req, timeout):
            called.append((req.full_url, timeout, dict(req.header_items())))
            return Response(INDEX.encode())
    monkeypatch.setattr(bs.urllib.request, 'build_opener', lambda *_: Opener())
    result = bs.fetch('index')
    assert len(result['models']) == 2 and called[0][0] == 'https://bikestudio.io/ecu?lang=en'
    for slug in ('../../secret', 'honda-a?x=1', 'https://evil.test', 'honda-', 'yamaha-a/b', 'a'*121):
        with pytest.raises(ValueError): bs.fetch('model', slug)
    assert len(called) == 1
    class Huge(Opener):
        def open(self, req, timeout): return Response(b'x' * (bs.MAX_BYTES + 1))
    monkeypatch.setattr(bs.urllib.request, 'build_opener', lambda *_: Huge())
    with pytest.raises(bs.BikeStudioError, match='size limit'): bs.fetch('index')
    class NotHtml(Opener):
        def open(self, req, timeout): return Response(b'hello','application/json')
    monkeypatch.setattr(bs.urllib.request, 'build_opener', lambda *_: NotHtml())
    with pytest.raises(bs.BikeStudioError, match='response type'): bs.fetch('index')
    assert bs._NoRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.test') is None


def test_model_fetch_and_api_require_explicit_action(monkeypatch):
    calls=[]
    class Opener:
        def open(self, req, timeout): calls.append(req.full_url); return Response(MODEL.encode())
    monkeypatch.setattr(bs.urllib.request,'build_opener',lambda *_: Opener())
    api = Api(Workstation(record=False))
    assert api.post_tools_bikestudio({'kind':'model','slug':'honda-beat-110'})[0] == 400
    assert not calls
    status, data = api.post_tools_bikestudio({'kind':'model','slug':'honda-beat-110','confirm_external':True})
    assert status == 200 and len(data['rows']) == 2
    assert calls == ['https://bikestudio.io/ecu/m/honda-beat-110?lang=en']
    assert data['synthetic_tested'] is True
    assert api.ws.service is None
    assert api._bikestudio_lock.acquire(blocking=False)
    try: assert api.post_tools_bikestudio({'kind':'index','confirm_external':True})[0] == 409
    finally: api._bikestudio_lock.release()
