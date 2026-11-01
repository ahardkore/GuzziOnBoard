"""Opt-in, bounded access to BikeStudio's public ECU model pages.

This is a listing reference, not a diagnostic or flash protocol. It fetches
only one public index or one selected model page per request; no crawling,
account access, database export or persistence is performed. Data is external
and untrusted. HTML parsing is best-effort and has only synthetic tests.
"""
from __future__ import annotations

import re
import urllib.error
import urllib.request
from html.parser import HTMLParser
from urllib.parse import urlsplit

BASE = 'https://bikestudio.io'
MAX_BYTES = 2 * 1024 * 1024
MAX_INDEX = 1000
MAX_ROWS = 500
SLUG = re.compile(r'^(?:honda|yamaha)-[a-z0-9]+(?:-[a-z0-9]+)*$')
PART_SLUG = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')


class BikeStudioError(Exception):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _clean(parts, limit=240):
    return ' '.join(''.join(parts).split())[:limit]


def _path(href):
    """Only canonical BikeStudio links, never other origins or credentials."""
    if not isinstance(href, str) or len(href) > 500:
        return ''
    try:
        parsed = urlsplit(href)
        if parsed.scheme or parsed.netloc:
            if parsed.scheme != 'https' or parsed.netloc != 'bikestudio.io':
                return ''
        if parsed.fragment or (parsed.query and parsed.query != 'lang=en'):
            return ''
        return parsed.path
    except ValueError:
        return ''


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.anchor = None
        self.models = {}
        self.in_row = False
        self.cell = None
        self.cells = []
        self.row_part = ''
        self.header_seen = False
        self.table_depth = 0
        self.table_selected = False
        self.table_done = False
        self.rows = []
        self.unrecognized_rows = False
        self.overflow = False
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ('script', 'style', 'template'):
            self.hidden += 1
            return
        if self.hidden:
            return
        if tag == 'table':
            self.table_depth += 1
            if self.table_depth == 1:
                self.table_selected = False
        elif tag == 'tr' and self.table_depth == 1 and not self.table_done:
            self.in_row, self.cells, self.row_part = True, [], ''
        elif tag in ('td', 'th') and self.in_row:
            self.cell = []
        elif tag == 'a':
            self.anchor = {'href': _path(attrs.get('href', '')), 'title': str(attrs.get('title') or '')[:500], 'text': []}

    def handle_data(self, data):
        if self.hidden:
            return
        if self.cell is not None:
            self.cell.append(data)
        if self.anchor is not None:
            self.anchor['text'].append(data)

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'template'):
            if self.hidden:
                self.hidden -= 1
            return
        if self.hidden:
            return
        if tag == 'table':
            if self.table_depth == 1 and self.table_selected:
                self.table_done = True
            self.table_depth = max(0, self.table_depth - 1)
            return
        if tag == 'a' and self.anchor is not None:
            a = self.anchor
            self.anchor = None
            path = a['href']
            text = _clean(a['text'])
            if path.startswith('/ecu/m/'):
                slug = path[len('/ecu/m/'):]
                if SLUG.fullmatch(slug) and text and slug not in self.models:
                    if len(self.models) >= MAX_INDEX:
                        self.overflow = True
                    else:
                        self.models[slug] = {'slug': slug, 'label': text, 'aliases': _clean([a['title']], 500)}
            elif self.in_row and self.cell is not None and len(self.cells) == 0 and path.startswith('/ecu/'):
                slug = path[len('/ecu/'):]
                if PART_SLUG.fullmatch(slug):
                    self.row_part = slug
        elif tag in ('td', 'th') and self.in_row and self.cell is not None:
            self.cells.append(_clean(self.cell))
            self.cell = None
        elif tag == 'tr' and self.in_row:
            self.in_row = False
            self.cell = None
            if len(self.cells) >= 4 and [v.casefold() for v in self.cells[:4]] == ['ecu part number', 'years', 'cc', 'market']:
                self.header_seen = True
                self.table_selected = True
            elif (self.table_selected and len(self.cells) == 4 and self.row_part
                  and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 /._-]{0,99}', self.cells[0])):
                if len(self.rows) >= MAX_ROWS:
                    self.overflow = True
                else:
                    part, years, cc, market = self.cells
                    self.rows.append({'part': part, 'part_slug': self.row_part,
                                      'years': '' if years in ('–', '—', '-') else years,
                                      'cc': '' if cc in ('–', '—', '-') else cc,
                                      'market': '' if market in ('–', '—', '-') else market})
            elif self.table_selected and len(self.cells) > 1:
                # Do not present a silently incomplete source table if a row's
                # shape or link changes. A single-cell footer may be ignored.
                self.unrecognized_rows = True


def parse_index(html):
    page = _Page()
    page.feed(html)
    if page.overflow:
        raise BikeStudioError('Model index exceeds the record limit.')
    if not page.models:
        raise BikeStudioError('No model links found; BikeStudio may have changed its page.')
    return list(page.models.values())


def parse_model(html):
    page = _Page()
    page.feed(html)
    if page.overflow:
        raise BikeStudioError('Model table exceeds the record limit.')
    if page.unrecognized_rows:
        raise BikeStudioError('Some ECU table rows were not recognized; open the source page to review them.')
    if not page.header_seen or not page.rows:
        raise BikeStudioError('No recognizable ECU part table found; BikeStudio may have changed its page.')
    return page.rows


def fetch(kind, slug=''):
    """Fetch exactly one allowed HTTPS page. Input cannot choose a host or URL."""
    if kind == 'index':
        if slug:
            raise ValueError('The index request must not specify a model.')
        path = '/ecu?lang=en'
    elif kind == 'model':
        if not isinstance(slug, str) or len(slug) > 120 or not SLUG.fullmatch(slug):
            raise ValueError('Select a valid Honda or Yamaha source model.')
        path = '/ecu/m/' + slug + '?lang=en'
    else:
        raise ValueError('Choose the public model index or a model page.')
    url = BASE + path
    request = urllib.request.Request(url, headers={'Accept': 'text/html', 'Accept-Encoding': 'identity',
                                                   'User-Agent': 'GuzziOnBoard/0.4 (user-requested ECU reference)'})
    try:
        opener = urllib.request.build_opener(_NoRedirect())
        with opener.open(request, timeout=12) as response:
            if response.status != 200 or response.headers.get_content_type() != 'text/html':
                raise BikeStudioError('BikeStudio returned an unexpected response type or status.')
            content = response.read(MAX_BYTES + 1)
            if len(content) > MAX_BYTES:
                raise BikeStudioError('BikeStudio page exceeds the size limit.')
        html = content.decode('utf-8-sig')
    except BikeStudioError:
        raise
    except (OSError, UnicodeDecodeError, urllib.error.URLError) as exc:
        raise BikeStudioError('Could not retrieve the public page. Check your internet connection or open the source link directly.') from exc
    result = {'source_url': url, 'synthetic_tested': True}
    if kind == 'index':
        result['models'] = parse_index(html)
    else:
        result['slug'], result['rows'] = slug, parse_model(html)
    return result
