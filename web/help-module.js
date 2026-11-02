/* GuzziOnBoard Help & Reference engine.
 *
 * Contents live in web/help-content.js (window.GOB_HELP). This file is the
 * machinery:
 *
 *   • one search index over guides, tools, protocols, the glossary, the live
 *     ECU catalog (/api/catalog), the bundled XDF library (/api/maps) and the
 *     menu commands in this page;
 *   • the Help & guides workspace (sidebar tree, category filters, article
 *     pane, permalinks and jump buttons);
 *   • the Ctrl+K global search spotlight with arrow-key navigation.
 *
 * Loaded after app.js, so `show()` can call window.renderHelpCenter().
 */
(function () {
  'use strict';

  const H = window.GOB_HELP || {};
  const TOPICS = Array.isArray(H.topics) ? H.topics : [];
  const TOOLS = Array.isArray(H.tools) ? H.tools : [];
  const PROTOCOLS = Array.isArray(H.protocols) ? H.protocols : [];
  const GLOSSARY = Array.isArray(H.glossary) ? H.glossary : [];
  const CATEGORIES = Array.isArray(H.categories) ? H.categories : [];
  const ECU_NOTES = H.ecuNotes || {};

  const KIND_LABEL = {
    guide: 'GUIDE', tool: 'TOOL', protocol: 'PROTOCOL', ecu: 'ECU',
    xdf: 'XDF', glossary: 'GLOSSARY', action: 'COMMAND', panel: 'PANEL',
  };
  const SCOPE_OF_KIND = {
    guide: 'guide', protocol: 'guide', glossary: 'guide',
    tool: 'tool', panel: 'tool', action: 'tool',
    ecu: 'ecu', xdf: 'ecu',
  };

  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

  function esc(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }
  function escRe(value) { return String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }
  function stripTags(html) {
    return String(html || '').replace(/<[^>]*>/g, ' ').replace(/&[a-z]+;/gi, ' ').replace(/\s+/g, ' ').trim();
  }
  function norm(value) {
    return String(value == null ? '' : value)
      .toLowerCase()
      .normalize('NFKD')
      .replace(/[\u0300-\u036f]/g, '')
      .replace(/[·–—]/g, ' ');
  }
  function slug(value) {
    return norm(value).replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
  }
  function toast(message, kind) {
    try {
      if (typeof window.toast === 'function') { window.toast(message, kind); return; }
    } catch (_) { /* fall through */ }
    const out = $('#helpCopyStatus');
    if (out) out.textContent = message;
  }

  const state = {
    route: null,
    lastRendered: null,
    category: 'all',
    query: '',
    index: [],
    built: false,
    catalog: null,
    catalogStatus: 'idle',
    xdfs: null,
    xdfStatus: 'idle',
    spot: { open: false, scope: 'all', query: '', cursor: 0, results: [] },
    pendingScrollTerm: null,
  };

  /* ============================================================ indexing */

  function makeEntry(fields) {
    const entry = Object.assign({
      kind: 'guide', title: '', subtitle: '', category: '', tags: [],
      bodyText: '', route: '', action: null,
    }, fields);
    entry.titleLower = norm(entry.title);
    entry.tagsLower = norm((entry.tags || []).join(' '));
    entry.summaryLower = norm(entry.subtitle);
    entry.bodyLower = norm(entry.bodyText);
    entry.haystack = [entry.titleLower, entry.tagsLower, entry.summaryLower, entry.bodyLower].join(' \u0001 ');
    entry.scope = SCOPE_OF_KIND[entry.kind] || 'guide';
    return entry;
  }

  function buildStaticIndex() {
    const entries = [];

    TOPICS.forEach((topic) => {
      entries.push(makeEntry({
        kind: 'guide',
        title: topic.title,
        subtitle: topic.summary || '',
        category: topic.category || 'howto',
        tags: topic.tags || [],
        bodyText: stripTags(topic.body || ''),
        route: 'topic/' + topic.id,
        topic,
      }));
    });

    TOOLS.forEach((tool) => {
      entries.push(makeEntry({
        kind: 'tool',
        title: tool.name,
        subtitle: tool.summary || '',
        category: tool.category || 'workshop',
        tags: (tool.tags || []).concat(tool.view || []),
        bodyText: stripTags([tool.summary, (tool.steps || []).join(' '), tool.caution].filter(Boolean).join(' ')),
        route: 'tool/' + tool.id,
        tool,
      }));
    });

    PROTOCOLS.forEach((protocol) => {
      entries.push(makeEntry({
        kind: 'protocol',
        title: protocol.name,
        subtitle: protocol.short || '',
        category: 'protocols',
        tags: (protocol.tags || []).concat(protocol.transport || []),
        bodyText: stripTags([
          protocol.transport, protocol.baud, protocol.init, protocol.addressing,
          protocol.framing, protocol.checksum, protocol.body,
          (protocol.usedBy || []).join(' '),
        ].filter(Boolean).join(' ')),
        route: 'protocol/' + protocol.id,
        protocol,
      }));
    });

    GLOSSARY.forEach((item) => {
      entries.push(makeEntry({
        kind: 'glossary',
        title: item.term,
        subtitle: 'Glossary · ' + stripTags(item.definition).slice(0, 140),
        category: 'glossary',
        tags: (item.tags || []).concat(['glossary', 'definition']),
        bodyText: stripTags(item.definition),
        route: 'glossary/' + slug(item.term),
        glossary: item,
      }));
    });

    return entries;
  }

  function buildActionIndex() {
    const entries = [];
    const seen = new Set();
    const menus = [
      ['#fileMenu', 'File menu'], ['#viewMenu', 'View menu'], ['#tuningMenu', 'Tuning menu'],
      ['#toolsMenu', 'Tools menu'], ['#helpMenu', 'Help menu'],
    ];
    menus.forEach(([selector, label]) => {
      $$(selector + ' .menu-item').forEach((el) => {
        const text = (el.textContent || '').replace(/\s+/g, ' ').trim();
        if (!text || seen.has(text + label)) return;
        seen.add(text + label);
        entries.push(makeEntry({
          kind: 'action',
          title: text,
          subtitle: label + ' command',
          category: 'tools',
          tags: ['menu', 'command', label],
          bodyText: text,
          route: 'action/' + entries.length,
          action: () => {
            el.click();
            if (el.closest('.dropdown-panel')) {
              const panel = el.closest('.dropdown-panel');
              panel.hidden = true;
              const btn = document.querySelector('[aria-controls="' + panel.id + '"]');
              if (btn) btn.setAttribute('aria-expanded', 'false');
            }
          },
        }));
      });
    });

    /* Panels that no TOOL entry names explicitly: index their heading so a
       search for the words on screen still finds the panel. */
    const known = new Set(TOOLS.map((tool) => tool.selector).filter(Boolean));
    $$('.view .panel').forEach((panel) => {
      const view = panel.closest('.view');
      if (!view) return;
      const h2 = panel.querySelector('h2');
      if (!h2) return;
      const title = (h2.textContent || '').replace(/\s+/g, ' ').trim();
      if (!title) return;
      const selector = panel.id ? '#' + panel.id : null;
      if (selector && known.has(selector)) return;
      const section = view.id;
      entries.push(makeEntry({
        kind: 'panel',
        title,
        subtitle: (section ? section.charAt(0).toUpperCase() + section.slice(1) + ' view · ' : '') + 'panel',
        category: 'tools',
        tags: [section, 'panel'],
        bodyText: (panel.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 4000),
        route: 'panel/' + entries.length,
        panel: { view: section, selector },
      }));
    });
    return entries;
  }

  function indexCatalog() {
    if (!state.catalog || !Array.isArray(state.catalog.ecus)) return [];
    return state.catalog.ecus.map((ecu) => makeEntry({
      kind: 'ecu',
      title: ecu.display_name || ecu.family || ecu.id,
      subtitle: [ecu.family, ecu.transport, ecu.confidence, ecu.years].filter(Boolean).join(' · '),
      category: 'ecus',
      tags: [ecu.id, ecu.family, ecu.transport, ecu.confidence, ecu.years]
        .concat(ecu.capabilities || []).concat(ecu.effective_capabilities || []),
      bodyText: [ecu.notes, (ecu.sources || []).join(' '), JSON.stringify(ecu.memory || {})].filter(Boolean).join(' '),
      route: 'ecu/' + ecu.id,
      ecu,
    }));
  }

  function indexXdfs() {
    if (!state.xdfs || !Array.isArray(state.xdfs)) return [];
    return state.xdfs.map((xdf) => makeEntry({
      kind: 'xdf',
      title: [xdf.brand_label, xdf.label || xdf.title].filter(Boolean).join(' · '),
      subtitle: [
        xdf.filename,
        (Number(xdf.tables) || 0) + ' tables', (Number(xdf.constants) || 0) + ' constants',
        (Number(xdf.flags) || 0) + ' flags', (Number(xdf.patches) || 0) + ' patches',
        xdf.region_size ? Math.round(xdf.region_size / 1024) + ' KiB' : '',
      ].filter(Boolean).join(' · '),
      category: 'ecus',
      tags: [xdf.brand, xdf.brand_label, xdf.family, xdf.filename, xdf.title, xdf.version]
        .concat((xdf.categories || [])).concat((xdf.fits || []).map((f) => f.label)),
      bodyText: (xdf.fits || []).map((f) => f.label).join(' ') + ' ' + (xdf.path || ''),
      route: 'xdf/' + encodeURIComponent(xdf.filename),
      xdf,
    }));
  }

  function rebuildIndex() {
    state.index = buildStaticIndex()
      .concat(buildActionIndex())
      .concat(indexCatalog())
      .concat(indexXdfs());
    state.built = true;
    const badge = $('#helpArticleCountBadge');
    if (badge) badge.textContent = state.index.filter((e) => e.kind !== 'action' && e.kind !== 'panel').length + ' topics';
    return state.index;
  }

  function ensureIndex() {
    if (!state.built) rebuildIndex();
    return state.index;
  }

  /* ============================================================== search */

  const STOP_WORDS = new Set(['the', 'a', 'an', 'to', 'of', 'and', 'or', 'in', 'on', 'for', 'is', 'it', 'how', 'do', 'i', 'my']);

  function tokenize(query) {
    const raw = norm(query).match(/[a-z0-9]+(?:[._:+-][a-z0-9]+)*/g) || [];
    const kept = raw.filter((token) => token.length > 1 || /[0-9]/.test(token));
    return kept.length ? kept : raw;
  }

  function scoreEntry(entry, tokens, phrase) {
    let score = 0;
    for (const token of tokens) {
      let hit = 0;
      if (entry.titleLower.includes(token)) {
        hit = 60 + (entry.titleLower.startsWith(token) ? 24 : 0);
      } else if (entry.tagsLower.includes(token)) {
        hit = 34;
      } else if (entry.summaryLower.includes(token)) {
        hit = 20;
      } else if (entry.bodyLower.includes(token)) {
        hit = 8;
      } else {
        return 0;
      }
      score += hit;
    }
    if (phrase.length > 2) {
      if (entry.titleLower.includes(phrase)) score += 80;
      else if (entry.tagsLower.includes(phrase)) score += 40;
      else if (entry.summaryLower.includes(phrase)) score += 26;
      else if (entry.bodyLower.includes(phrase)) score += 10;
    }
    if (entry.kind === 'guide') score += 4;
    if (entry.kind === 'action' || entry.kind === 'panel') score -= 2;
    return score;
  }

  function highlight(raw, tokens) {
    if (!tokens.length) return esc(raw);
    const ordered = tokens.slice().sort((a, b) => b.length - a.length).map(escRe);
    if (!ordered.length) return esc(raw);
    const re = new RegExp('(' + ordered.join('|') + ')', 'gi');
    const out = [];
    let last = 0;
    let match;
    while ((match = re.exec(raw)) !== null) {
      if (!match[0]) { re.lastIndex += 1; continue; }
      out.push(esc(raw.slice(last, match.index)));
      out.push('<mark>' + esc(match[0]) + '</mark>');
      last = match.index + match[0].length;
    }
    out.push(esc(raw.slice(last)));
    return out.join('');
  }

  function snippet(entry, tokens) {
    const text = entry.subtitle && entry.subtitle.length > 20 ? entry.subtitle + ' — ' + entry.bodyText : entry.bodyText;
    if (!text) return '';
    const lower = norm(text);
    let at = -1;
    for (const token of tokens) {
      const found = lower.indexOf(token);
      if (found !== -1 && (at === -1 || found < at)) at = found;
    }
    if (at === -1) at = 0;
    const start = Math.max(0, at - 60);
    const slice = text.slice(start, start + 180);
    return (start > 0 ? '…' : '') + highlight(slice, tokens) + (start + 180 < text.length ? '…' : '');
  }

  function search(query, options) {
    const opts = options || {};
    const tokens = tokenize(query);
    if (!tokens.length) return [];
    const phrase = norm(query).trim();
    const entries = ensureIndex();
    const results = [];
    for (const entry of entries) {
      if (opts.scope && opts.scope !== 'all' && entry.scope !== opts.scope) continue;
      if (opts.category && opts.category !== 'all' && entry.category !== opts.category) continue;
      const score = scoreEntry(entry, tokens, phrase);
      if (score > 0) results.push({ entry, score });
    }
    results.sort((a, b) => b.score - a.score || a.entry.title.localeCompare(b.entry.title));
    const limit = opts.limit || 40;
    return results.slice(0, limit).map((row) => ({ ...row, snippet: snippet(row.entry, tokens) }));
  }

  /* ============================================================ routing */

  function topicById(id) { return TOPICS.find((topic) => topic.id === id) || null; }
  function toolById(id) { return TOOLS.find((tool) => tool.id === id) || null; }
  function protocolById(id) { return PROTOCOLS.find((protocol) => protocol.id === id) || null; }
  function glossaryBySlug(id) { return GLOSSARY.find((item) => slug(item.term) === id) || null; }

  const DEFAULT_ROUTE = 'topic/getting-started';

  function resolveRoute(raw) {
    let value = String(raw || '').replace(/^#?\/?help\/?/, '').replace(/^#/, '').trim();
    if (!value) return { kind: 'missing', id: '' };
    value = value.replace(/\/+$/, '');
    if (value.startsWith('topic/')) return { kind: 'topic', id: value.slice(6) };
    if (value.startsWith('tool/')) return { kind: 'tool', id: decodeURIComponent(value.slice(5)) };
    if (value.startsWith('protocol/')) return { kind: 'protocol', id: value.slice(9) };
    if (value.startsWith('ecu/')) return { kind: 'ecu', id: decodeURIComponent(value.slice(4)) };
    if (value.startsWith('xdf/')) return { kind: 'xdf', id: decodeURIComponent(value.slice(4)) };
    if (value === 'glossary' || value === 'glossary/') return { kind: 'glossary', id: '' };
    if (value.startsWith('glossary/')) return { kind: 'glossary', id: decodeURIComponent(value.slice(9)) };
    // tolerated aliases: #help/topic-<id> and #help/tool-<id>
    if (value.startsWith('topic-') && topicById(value.slice(6))) return { kind: 'topic', id: value.slice(6) };
    if (value.startsWith('tool-') && toolById(value.slice(5))) return { kind: 'tool', id: value.slice(5) };
    if (topicById(value)) return { kind: 'topic', id: value };
    if (protocolById(value)) return { kind: 'protocol', id: value };
    if (toolById(value)) return { kind: 'tool', id: value };
    return { kind: 'missing', id: value };
  }

  function hashFor(route) {
    const parsed = typeof route === 'string' ? resolveRoute(route) : route;
    if (!parsed || parsed.kind === 'missing') return '#help';
    if (parsed.kind === 'topic') return '#help/' + parsed.id;
    if (parsed.kind === 'xdf') return '#help/xdf/' + encodeURIComponent(parsed.id);
    if (parsed.kind === 'tool') return '#help/tool/' + encodeURIComponent(parsed.id);
    if (!parsed.id) return '#help/' + parsed.kind;
    return '#help/' + parsed.kind + '/' + encodeURIComponent(parsed.id);
  }

  function helpIsVisible() {
    const view = $('#help');
    return Boolean(view && !view.classList.contains('hidden'));
  }

  function canonicalRoute(parsed) {
    if (!parsed || parsed.kind === 'missing') return DEFAULT_ROUTE;
    if (parsed.kind === 'topic') return 'topic/' + parsed.id;
    if (!parsed.id) return parsed.kind;
    return parsed.kind + '/' + parsed.id;
  }

  function go(rawRoute, options) {
    const opts = options || {};
    const parsed = typeof rawRoute === 'string' ? resolveRoute(rawRoute) : rawRoute;
    const route = canonicalRoute(parsed);
    state.route = route;
    if (!helpIsVisible()) {
      const nav = $('.nav[data-view="help"]');
      if (nav) nav.click();
      else if (typeof window.renderHelpCenter === 'function') renderHelpCenter();
    } else {
      renderHelpCenter();
    }
    if (!opts.fromLocation) {
      const next = hashFor(parsed);
      if (location.hash !== next) history.pushState(null, '', next);
    }
  }

  function routeFromLocation() {
    const hash = String(location.hash || '');
    if (!hash.startsWith('#help')) return null;
    let raw = hash.slice(5).replace(/^\//, '');
    let term = null;
    const termIndex = raw.indexOf('/');
    // #help/glossary/<slug>/<term> is not used; a ?term= or trailing /<term> is
    if (raw.startsWith('glossary/')) {
      const parts = raw.split('/');
      raw = parts.slice(0, 2).join('/');
      if (parts.length > 2) term = decodeURIComponent(parts[2]);
    }
    if (termIndex === -1) {
      // plain #help/<topic>
      const parsed = resolveRoute(raw);
      return { parsed, term };
    }
    return { parsed: resolveRoute(raw), term };
  }

  /* ====================================================== article render */

  function categoryLabel(id) {
    const cat = CATEGORIES.find((entry) => entry.id === id);
    return cat ? cat.label : (id ? id.charAt(0).toUpperCase() + id.slice(1) : 'Reference');
  }

  function jumpButton(spec) {
    if (!spec) return '';
    const view = spec.view || '';
    const selector = spec.selector || '';
    const openDetails = spec.openDetails || '';
    return '<button type="button" class="btn small help-jump" data-help-jump="1"'
      + ' data-jump-view="' + esc(view) + '" data-jump-selector="' + esc(selector) + '"'
      + ' data-jump-open="' + esc(openDetails) + '">' + esc(spec.label || 'Open in program') + ' →</button>';
  }

  function jumpButtons(tools) {
    const list = (tools || []).filter(Boolean);
    if (!list.length) return '';
    return '<div class="help-jump-row">' + list.map(jumpButton).join('') + '</div>';
  }

  function relatedLinks(ids) {
    const list = (ids || []).filter(Boolean);
    if (!list.length) return '';
    const items = list.map((id) => {
      const parsed = resolveRoute(id.startsWith('topic/') || id.includes('/') ? id : 'topic/' + id);
      const entry = entryForParsed(parsed);
      if (!entry) return '';
      return '<a class="help-related-link" href="' + esc(hashFor(parsed)) + '">'
        + '<span class="help-related-kind">' + (KIND_LABEL[entry.kind] || 'REF') + '</span> '
        + esc(entry.title) + '</a>';
    }).filter(Boolean);
    if (!items.length) return '';
    return '<div class="help-related"><h3>Related reading</h3><div class="help-related-list">' + items.join('') + '</div></div>';
  }

  function entryForParsed(parsed) {
    if (!parsed) return null;
    if (parsed.kind === 'topic') {
      const topic = topicById(parsed.id);
      return topic ? { kind: 'guide', title: topic.title, topic } : null;
    }
    if (parsed.kind === 'tool') {
      const tool = toolById(parsed.id);
      return tool ? { kind: 'tool', title: tool.name, tool } : null;
    }
    if (parsed.kind === 'protocol') {
      const protocol = protocolById(parsed.id);
      return protocol ? { kind: 'protocol', title: protocol.name, protocol } : null;
    }
    if (parsed.kind === 'ecu') {
      const ecu = (state.catalog && (state.catalog.ecus || []).find((item) => item.id === parsed.id)) || null;
      return ecu ? { kind: 'ecu', title: ecu.display_name || ecu.family || ecu.id, ecu } : null;
    }
    if (parsed.kind === 'xdf') {
      const xdf = (state.xdfs || []).find((item) => item.filename === parsed.id) || null;
      return xdf ? { kind: 'xdf', title: xdf.label || xdf.title || xdf.filename, xdf } : null;
    }
    if (parsed.kind === 'glossary') {
      const term = glossaryBySlug(parsed.id);
      return term ? { kind: 'glossary', title: term.term, glossary: term } : null;
    }
    return null;
  }

  function addHeadingIds(html) {
    let n = 0;
    return String(html || '').replace(/<h3(\s[^>]*)?>([\s\S]*?)<\/h3>/g, (whole, attrs, inner) => {
      n += 1;
      const id = 'help-sec-' + n;
      return '<h3 id="' + id + '"' + (attrs || '') + '>' + inner + '</h3>';
    });
  }

  function articleHeader(kind, title, summary, category) {
    return ''
      + '<div class="help-article-head">'
      + '  <div class="help-article-kicker">' + esc(KIND_LABEL[kind] || 'REFERENCE')
      + (category ? ' <span class="help-dot">·</span> ' + esc(categoryLabel(category)) : '') + '</div>'
      + '  <h2 class="help-article-title">' + esc(title) + '</h2>'
      + (summary ? '<p class="help-article-summary">' + esc(summary) + '</p>' : '')
      + '  <div class="help-article-actions">'
      + '    <button type="button" class="btn small" id="helpCopyLinkBtn" data-help-copy="1">Copy link</button>'
      + '    <button type="button" class="btn small" id="helpPrintBtn" data-help-print="1">Print / PDF</button>'
      + '    <span class="muted small" id="helpCopyStatus" aria-live="polite"></span>'
      + '  </div>'
      + '</div>';
  }

  function renderTopicArticle(topic) {
    return ''
      + articleHeader('guide', topic.title, topic.summary, topic.category)
      + jumpButtons(topic.tools)
      + '<div class="help-body">' + addHeadingIds(topic.body || '') + '</div>'
      + relatedLinks(topic.related);
  }

  function renderToolArticle(tool) {
    const steps = (tool.steps || []).filter(Boolean);
    return ''
      + articleHeader('tool', tool.name, tool.summary, tool.category)
      + jumpButtons([{ label: 'Open this in the program', view: tool.view, selector: tool.selector }])
      + (steps.length ? '<div class="help-body"><h3>How to use it</h3><ol class="help-steps">'
        + steps.map((step) => '<li>' + esc(step) + '</li>').join('') + '</ol></div>' : '')
      + (tool.caution ? '<div class="gate-card warn"><h4>Before you use it</h4><p>' + esc(tool.caution) + '</p></div>' : '')
      + (tool.tags && tool.tags.length
        ? '<p class="help-tagline">Tags: ' + tool.tags.map((tag) => '<span class="help-tag">' + esc(tag) + '</span>').join(' ') + '</p>'
        : '');
  }

  function specRow(label, value) {
    if (!value) return '';
    return '<tr><th scope="row">' + esc(label) + '</th><td>' + esc(value) + '</td></tr>';
  }

  function renderProtocolArticle(protocol) {
    return ''
      + articleHeader('protocol', protocol.name, protocol.short, 'protocols')
      + jumpButtons([{ label: 'Protocol evidence in the Garage', view: 'garage', selector: '#protocolPanel' },
        { label: 'Choose a transport', view: 'garage', selector: '#connectionPanel' }])
      + '<div class="help-body">'
      + '<h3>Specification</h3>'
      + '<table class="help-table help-spec-table"><tbody>'
      + specRow('Transport', protocol.transport)
      + specRow('Baud rate', protocol.baud)
      + specRow('Initialisation', protocol.init)
      + specRow('Addressing', protocol.addressing)
      + specRow('Framing', protocol.framing)
      + specRow('Checksum', protocol.checksum)
      + '</tbody></table>'
      + addHeadingIds(protocol.body || '')
      + ((protocol.usedBy || []).length
        ? '<h3>Profiles that use it</h3><ul>' + protocol.usedBy.map((item) => '<li>' + esc(item) + '</li>').join('') + '</ul>'
        : '')
      + ((protocol.workstation || []).length
        ? '<h3>Where it appears in the workstation</h3><ul>'
        + protocol.workstation.map((item) => '<li>' + esc(item) + '</li>').join('') + '</ul>'
        : '')
      + '</div>'
      + relatedLinks(protocol.related);
  }

  function renderEcuArticle(ecu) {
    const caps = (ecu.capabilities || []);
    const effective = (ecu.effective_capabilities || []);
    const memory = ecu.memory || {};
    const km = Object.keys(ecu.kline || {});
    const notes = ECU_NOTES[ecu.id] || '';
    return ''
      + articleHeader('ecu', ecu.display_name || ecu.family || ecu.id, (ecu.family || '') + ' · ' + (ecu.years || 'years unknown'), 'ecus')
      + jumpButtons([{ label: 'Select this ECU in the Garage', view: 'garage', selector: '#ecuOverride' }])
      + '<div class="help-body">'
      + '<h3>Catalog entry</h3>'
      + '<table class="help-table help-spec-table"><tbody>'
      + specRow('Catalog id', ecu.id)
      + specRow('Family', ecu.family)
      + specRow('Display name', ecu.display_name)
      + specRow('Years', ecu.years)
      + specRow('Transport', ecu.transport)
      + specRow('Confidence', ecu.confidence)
      + specRow('Declared capabilities', caps.length ? caps.join(', ') : 'none — physical use is refused')
      + specRow('Effective capabilities', effective.length ? effective.join(', ') : 'none')
      + specRow('Image size', typeof memory.image_size === 'number' ? memory.image_size.toLocaleString() + ' bytes' : 'not declared')
      + specRow('Memory read', memory.read_supported ? 'implemented' : 'not implemented')
      + specRow('Memory write', memory.write_supported ? 'implemented' : 'not implemented')
      + specRow('Write blocked because', memory.write_blocked_reason)
      + specRow('K-Line settings', km.length ? JSON.stringify(ecu.kline) : '')
      + specRow('CAN settings', Object.keys(ecu.can || {}).length ? JSON.stringify(ecu.can) : '')
      + '</tbody></table>'
      + (notes ? '<p>' + notes + '</p>' : '')
      + (ecu.notes ? '<h3>What the catalog says</h3><p>' + esc(ecu.notes) + '</p>' : '')
      + ((ecu.sources || []).length
        ? '<h3>Sources</h3><ul>' + ecu.sources.map((source) => '<li>' + esc(source) + '</li>').join('') + '</ul>'
        : '')
      + '</div>'
      + relatedLinks(['topic-ecus-overview', 'topic-ecu-confidence', 'topic-protocols-overview']);
  }

  function renderXdfArticle(xdf) {
    return ''
      + articleHeader('xdf', xdf.label || xdf.title || xdf.filename, xdf.path || xdf.filename, 'ecus')
      + jumpButtons([{ label: 'Render this definition in Maps', view: 'firmware', selector: '#mapsCard' }])
      + '<div class="help-body">'
      + '<h3>Definition</h3>'
      + '<table class="help-table help-spec-table"><tbody>'
      + specRow('File', xdf.filename)
      + specRow('Path', xdf.path)
      + specRow('Brand', xdf.brand_label || xdf.brand)
      + specRow('Family', xdf.family)
      + specRow('Version', xdf.version)
      + specRow('Tables', String(Number(xdf.tables) || 0))
      + specRow('Constants', String(Number(xdf.constants) || 0))
      + specRow('Flags', String(Number(xdf.flags) || 0))
      + specRow('Patches', String(Number(xdf.patches) || 0))
      + specRow('Unsupported elements', String(Number(xdf.unsupported) || 0))
      + specRow('Region size', typeof xdf.region_size === 'number' ? xdf.region_size.toLocaleString() + ' bytes' : 'not declared')
      + specRow('Catalogued', xdf.catalogued === undefined ? '' : (xdf.catalogued ? 'yes' : 'no — research only'))
      + '</tbody></table>'
      + ((xdf.fits || []).length
        ? '<h3>Published fitment</h3><ul>'
        + xdf.fits.map((fit) => '<li>' + esc((fit.brand_label ? fit.brand_label + ' — ' : '') + fit.label) + '</li>').join('')
        + '</ul>'
        : '')
      + '<p class="muted small">Definitions are third-party research. Rendering successfully does not prove the scalings match your software version; validate against a value you can observe.</p>'
      + '</div>'
      + relatedLinks(['topic-howto-xdf-editing', 'topic-checksums-xdf-math', 'topic-ecus-xdf-library']);
  }

  function renderGlossaryArticle(term) {
    const terms = GLOSSARY.slice().sort((a, b) => a.term.localeCompare(b.term));
    return ''
      + articleHeader('glossary', term ? term.term : 'Glossary of ECU, tuning and workshop terms',
        term ? '' : 'Every acronym and term used in this program, in plain language.', 'glossary')
      + (term
        ? '<div class="help-body"><div class="help-glossary-term" id="term-' + slug(term.term) + '">'
        + '<h3>' + esc(term.term) + '</h3><p>' + term.definition + '</p></div>'
        + '<p><a href="#help/glossary">&larr; All glossary terms</a></p></div>'
        : '<div class="help-body"><div class="help-glossary-list">'
        + terms.map((item) => '<div class="help-glossary-term" id="term-' + slug(item.term) + '">'
          + '<h3>' + esc(item.term) + '</h3><p>' + item.definition + '</p></div>').join('')
        + '</div></div>');
  }

  function renderToolDirectory() {
    const groups = [
      ['Workspaces', (tool) => tool.id.startsWith('view-')],
      ['ECU memory pipeline', (tool) => tool.category === 'memory'],
      ['Diagnostics & I/O', (tool) => tool.category === 'diagnostics'],
      ['Dash, logs & sessions', (tool) => tool.category === 'dash' && !tool.id.startsWith('view-')],
      ['Calibration & research', (tool) => tool.category === 'calibration'],
      ['Telemetry & hardware', (tool) => ['telemetry', 'hardware'].includes(tool.category)],
      ['Workshop utilities', (tool) => tool.category === 'workshop'],
      ['Search, dialogs & menu', (tool) => ['search', 'reference'].includes(tool.category)],
    ];
    const used = new Set();
    const sections = groups.map(([label, predicate]) => {
      const tools = TOOLS.filter((tool) => !used.has(tool.id) && predicate(tool));
      tools.forEach((tool) => used.add(tool.id));
      return [label, tools];
    });
    const leftovers = TOOLS.filter((tool) => !used.has(tool.id));
    if (leftovers.length) sections.push(['More tools', leftovers]);

    return sections.map(([label, tools]) => {
      if (!tools.length) return '';
      return '<section class="help-directory-group"><h3>' + esc(label) + ' <span class="muted small">('
        + tools.length + ')</span></h3><div class="help-directory-grid">'
        + tools.map((tool) => '<div class="help-directory-card" data-help-tool-card="' + esc(tool.id) + '">'
          + '<a class="help-directory-title" href="#help/tool/' + encodeURIComponent(tool.id) + '">' + esc(tool.name) + '</a>'
          + '<p class="small muted">' + esc(tool.summary || '') + '</p>'
          + jumpButton({ label: 'Jump', view: tool.view, selector: tool.selector })
          + '</div>').join('')
        + '</div></section>';
    }).join('');
  }

  function renderEcuCatalogBlock() {
    if (state.catalogStatus === 'loading' || state.catalogStatus === 'idle') {
      return '<p class="muted">Loading ECU catalog…</p>';
    }
    if (state.catalogStatus === 'error') {
      return '<p class="muted">The ECU catalog is not available here (static host or API offline). '
        + 'The bundled catalog has 39 ECU families; run the local workstation to browse it live.</p>';
    }
    const ecus = (state.catalog && state.catalog.ecus) || [];
    return '<p class="muted small">' + ecus.length + ' catalog entries.</p>'
      + '<div class="help-ecu-grid">' + ecus.map((ecu) => {
        const caps = (ecu.capabilities || []);
        return '<a class="help-ecu-card" href="#help/ecu/' + encodeURIComponent(ecu.id) + '">'
          + '<span class="help-ecu-name">' + esc(ecu.display_name || ecu.family || ecu.id) + '</span>'
          + '<span class="help-ecu-meta">' + esc([ecu.transport, ecu.confidence, ecu.years].filter(Boolean).join(' · ')) + '</span>'
          + '<span class="help-ecu-caps">' + (caps.length ? caps.map((cap) => '<span class="help-tag">' + esc(cap) + '</span>').join(' ') : '<span class="help-tag muted">no capabilities</span>') + '</span>'
          + '</a>';
      }).join('') + '</div>';
  }

  function renderXdfLibraryBlock() {
    if (state.xdfStatus === 'loading' || state.xdfStatus === 'idle') {
      return '<p class="muted">Loading the bundled XDF library…</p>';
    }
    if (state.xdfStatus === 'error') {
      return '<p class="muted">The XDF index is not available here. The library ships inside the application; '
        + 'run the local workstation to browse all definitions.</p>';
    }
    const xdfs = (state.xdfs || []).slice().sort((a, b) => String(a.brand_label || a.brand || '').localeCompare(String(b.brand_label || b.brand || '')) || String(a.filename).localeCompare(String(b.filename)));
    const byBrand = new Map();
    xdfs.forEach((xdf) => {
      const brand = xdf.brand_label || xdf.brand || 'Other';
      if (!byBrand.has(brand)) byBrand.set(brand, []);
      byBrand.get(brand).push(xdf);
    });
    return '<p class="muted small">' + xdfs.length + ' definitions across ' + byBrand.size + ' brands.</p>'
      + Array.from(byBrand.entries()).map(([brand, items]) => '<section class="help-xdf-brand">'
        + '<h3>' + esc(brand) + ' <span class="muted small">(' + items.length + ')</span></h3>'
        + '<div class="help-xdf-grid">' + items.map((xdf) => '<a class="help-xdf-card" href="#help/xdf/' + encodeURIComponent(xdf.filename) + '">'
          + '<span class="help-xdf-name">' + esc(xdf.label || xdf.title || xdf.filename) + '</span>'
          + '<span class="help-xdf-meta">' + esc(xdf.filename) + '</span>'
          + '<span class="help-xdf-counts">' + [
            xdf.tables + ' tables', xdf.constants + ' const',
            (xdf.flags || 0) + ' flags', (xdf.patches || 0) + ' patches',
          ].join(' · ') + '</span>'
          + '</a>').join('') + '</div></section>').join('');
  }

  function renderMissingArticle(raw) {
    return ''
      + articleHeader('guide', 'No help article for “' + raw + '”', 'The topic may have moved, or the link may be mistyped. Try the search box or the directory.', '')
      + '<div class="help-body"><p>Popular starting points:</p><ul>'
      + '<li><a href="#help/getting-started">Start here: the 10-minute tour</a></li>'
      + '<li><a href="#help/tools-directory">Every tool &amp; workspace</a></li>'
      + '<li><a href="#help/protocols-overview">Wire protocols</a></li>'
      + '<li><a href="#help/ecus-overview">ECU catalog</a></li>'
      + '<li><a href="#help/glossary">Glossary</a></li>'
      + '</ul><p><button type="button" class="btn small primary" data-help-open-spotlight="1">Search everything (Ctrl+K)</button></p></div>';
  }

  function renderRoute() {
    const pane = $('#helpArticlePane');
    if (!pane) return;
    const parsed = resolveRoute(state.route || DEFAULT_ROUTE);
    let html = '';

    if (parsed.kind === 'missing') {
      html = renderMissingArticle(parsed.id);
    } else if (parsed.kind === 'topic') {
      const topic = topicById(parsed.id);
      html = topic ? renderTopicArticle(topic) : renderMissingArticle(parsed.id);
    } else if (parsed.kind === 'tool') {
      const tool = toolById(parsed.id);
      html = tool ? renderToolArticle(tool) : renderMissingArticle(parsed.id);
    } else if (parsed.kind === 'protocol') {
      const protocol = protocolById(parsed.id);
      html = protocol ? renderProtocolArticle(protocol) : renderMissingArticle(parsed.id);
    } else if (parsed.kind === 'ecu') {
      const entry = entryForParsed(parsed);
      if (entry && entry.ecu) html = renderEcuArticle(entry.ecu);
      else {
        html = articleHeader('ecu', 'ECU ' + parsed.id, 'Catalog data is loading…', 'ecus')
          + '<div class="help-body"><p id="helpEcuPending">Fetching the catalog entry for <code>' + esc(parsed.id) + '</code>…</p></div>';
        loadCatalogData().then(() => {
          if (state.route === parsed.kind + '/' + parsed.id) renderRoute();
        });
        if (state.catalogStatus === 'error') {
          html = articleHeader('ecu', 'ECU ' + parsed.id, 'The catalog is not available here.', 'ecus')
            + '<div class="help-body"><p>The live ECU catalog comes from <code>/api/catalog</code>, which the hosted '
            + 'static demo also answers. If you are offline, run the local workstation.</p></div>';
        }
      }
    } else if (parsed.kind === 'xdf') {
      const entry = entryForParsed(parsed);
      if (entry && entry.xdf) html = renderXdfArticle(entry.xdf);
      else {
        html = articleHeader('xdf', parsed.id, 'XDF library data is loading…', 'ecus');
        loadXdfData().then(() => {
          if (state.route === parsed.kind + '/' + parsed.id) renderRoute();
        });
        if (state.xdfStatus === 'error') {
          html = articleHeader('xdf', parsed.id, 'The XDF index is not available here.', 'ecus')
            + '<div class="help-body"><p>The bundled library is indexed by <code>/api/maps</code>. Run the local '
            + 'workstation, or open <a href="#help/ecus-xdf-library">the library overview</a>.</p></div>';
        }
      }
    } else if (parsed.kind === 'glossary') {
      html = renderGlossaryArticle(glossaryBySlug(parsed.id) || null);
    }

    pane.innerHTML = html;
    state.lastRendered = state.route;

    // Dynamic blocks inside the article body
    const ecuBlock = $('#helpEcuCatalog');
    if (ecuBlock) {
      ecuBlock.innerHTML = renderEcuCatalogBlock();
      if (state.catalogStatus === 'idle') {
        loadCatalogData().then(() => renderRoute());
      }
    }
    const xdfBlock = $('#helpXdfLibrary');
    if (xdfBlock) {
      xdfBlock.innerHTML = renderXdfLibraryBlock();
      if (state.xdfStatus === 'idle') {
        loadXdfData().then(() => renderRoute());
      }
    }
    const dirBlock = $('#helpToolDirectory');
    if (dirBlock) dirBlock.innerHTML = renderToolDirectory();

    // Scroll target: a glossary term or the top of the pane
    if (state.pendingScrollTerm) {
      const target = document.getElementById('term-' + slug(state.pendingScrollTerm));
      state.pendingScrollTerm = null;
      if (target) {
        target.scrollIntoView({ block: 'center' });
        target.classList.add('help-focus-ring');
        setTimeout(() => target.classList.remove('help-focus-ring'), 2000);
      }
    }
    const main = $('#workbenchMain');
    if (main) main.scrollTop = 0;

    renderTree();
  }

  /* ======================================================== help center */

  function visibleTopics() {
    const query = state.query.trim();
    let pool = ensureIndex().filter((entry) => entry.kind !== 'action' && entry.kind !== 'panel');
    if (state.category !== 'all') pool = pool.filter((entry) => entry.category === state.category);
    if (query) {
      const hits = new Set(search(query, { category: state.category, limit: 400 }).map((row) => row.entry));
      pool = pool.filter((entry) => hits.has(entry));
    }
    return pool;
  }

  function renderTree() {
    const tree = $('#helpTopicTree');
    if (!tree) return;
    const activeRoute = state.route || DEFAULT_ROUTE;
    const groups = new Map();
    visibleTopics().forEach((entry) => {
      const key = entry.category || 'howto';
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(entry);
    });
    const order = CATEGORIES.map((cat) => cat.id);
    const keys = Array.from(groups.keys()).sort((a, b) => {
      const ia = order.indexOf(a); const ib = order.indexOf(b);
      return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
    });
    if (!keys.length) {
      tree.innerHTML = '<p class="muted small help-tree-empty">No topics match that filter.</p>';
      return;
    }
    tree.innerHTML = keys.map((key) => {
      const items = groups.get(key);
      return '<div class="help-tree-group">'
        + '<div class="help-tree-group-head"><span>' + esc(categoryLabel(key)) + '</span><span class="muted">' + items.length + '</span></div>'
        + items.map((entry) => '<button type="button" class="help-tree-item'
          + (entry.route === activeRoute ? ' active' : '') + '" data-help-route="' + esc(entry.route) + '">'
          + '<span class="help-tree-kind">' + (KIND_LABEL[entry.kind] || '') + '</span>'
          + '<span class="help-tree-title">' + esc(entry.title) + '</span>'
          + '</button>').join('')
        + '</div>';
    }).join('');
    const groupLabel = $('#helpSidebarGroupLabel');
    if (groupLabel) {
      groupLabel.textContent = state.query
        ? 'Search results'
        : (state.category === 'all' ? 'All topics' : categoryLabel(state.category));
    }
  }

  function renderSearchResultsPanel() {
    const panel = $('#helpSearchResultsPanel');
    const layout = $('#helpMainLayout');
    const stats = $('#helpSearchStats');
    if (!panel) return;
    const query = state.query.trim();
    const clearBtn = $('#helpSearchClear');
    if (clearBtn) clearBtn.classList.toggle('hidden', !query);
    if (!query) {
      panel.classList.add('hidden');
      if (layout) layout.classList.remove('hidden');
      if (stats) { stats.classList.add('hidden'); stats.textContent = ''; }
      renderTree();
      return;
    }
    const results = search(query, { category: state.category, limit: 120 });
    if (layout) layout.classList.add('hidden');
    panel.classList.remove('hidden');
    if (stats) {
      stats.classList.remove('hidden');
      stats.textContent = results.length
        ? results.length + ' result' + (results.length === 1 ? '' : 's') + ' for “' + query + '”'
        : 'No results for “' + query + '”. Try a shorter word, a brand, an ECU family or a protocol.';
    }
    panel.innerHTML = results.length
      ? results.map((row) => resultRow(row, 'help-search-result')).join('')
      : '<div class="help-empty"><p>Nothing matched. The search requires <b>every</b> word to appear somewhere in an article, '
        + 'tool, ECU or XDF entry. Try “5am”, “checksum”, “harley”, “afr” or “backup”.</p></div>';
    renderTree();
  }

  function resultRow(row, extraClass) {
    const entry = row.entry;
    return '<button type="button" class="help-result ' + (extraClass || '') + '"'
      + ' data-help-route="' + esc(entry.route) + '"'
      + ' data-help-open="' + esc(entry.route) + '">'
      + '<span class="help-result-kind kind-' + esc(entry.kind) + '">' + esc(KIND_LABEL[entry.kind] || 'REF') + '</span>'
      + '<span class="help-result-main">'
      + '<span class="help-result-title">' + highlight(entry.title, tokenize(state.query || state.spot.query || '')) + '</span>'
      + (row.snippet ? '<span class="help-result-snippet">' + row.snippet + '</span>' : '')
      + '</span>'
      + '<span class="help-result-arrow" aria-hidden="true">→</span>'
      + '</button>';
  }

  function renderHelpCenter() {
    ensureIndex();
    // Keep the pills, search box and badge in sync with state.
    $$('#helpCategoryPills [data-help-cat]').forEach((pill) => {
      const active = pill.dataset.helpCat === state.category;
      pill.classList.toggle('active', active);
      pill.setAttribute('aria-selected', active ? 'true' : 'false');
    });
    const input = $('#helpSearchInput');
    if (input && input.value !== state.query) input.value = state.query;
    const badge = $('#helpArticleCountBadge');
    if (badge && !badge.textContent.trim()) badge.textContent = '0 topics';
    renderSearchResultsPanel();
    if (!state.route) {
      const fromState = routeFromLocation();
      state.route = fromState ? canonicalRoute(fromState.parsed) : DEFAULT_ROUTE;
      if (fromState && fromState.term) state.pendingScrollTerm = fromState.term;
    }
    if (state.route !== state.lastRendered) {
      renderRoute();
    } else {
      renderTree();
    }
    loadCatalogData();
    loadXdfData();
  }

  /* ======================================================= dynamic data */

  async function fetchJson(path) {
    const response = await fetch(path, { headers: { Accept: 'application/json' } });
    if (!response.ok) throw new Error(path + ': HTTP ' + response.status);
    return response.json();
  }

  function refreshAfterData() {
    if (!helpIsVisible()) return;
    renderRoute();
    if (state.query.trim()) renderSearchResultsPanel();
  }

  function loadCatalogData() {
    if (state.catalogStatus === 'loading' || state.catalogStatus === 'ready') return Promise.resolve(state.catalog);
    state.catalogStatus = 'loading';
    return fetchJson('/api/catalog').then((data) => {
      state.catalog = data;
      state.catalogStatus = 'ready';
      rebuildIndex();
      refreshAfterData();
      return data;
    }).catch(() => {
      state.catalogStatus = 'error';
      state.catalog = null;
      refreshAfterData();
      return null;
    });
  }

  function loadXdfData() {
    if (state.xdfStatus === 'loading' || state.xdfStatus === 'ready') return Promise.resolve(state.xdfs);
    state.xdfStatus = 'loading';
    return fetchJson('/api/maps').then((data) => {
      state.xdfs = Array.isArray(data.xdfs) ? data.xdfs : [];
      state.xdfStatus = 'ready';
      rebuildIndex();
      refreshAfterData();
      return state.xdfs;
    }).catch(() => {
      state.xdfStatus = 'error';
      state.xdfs = [];
      refreshAfterData();
      return [];
    });
  }

  /* ========================================================== spotlight */

  const SUGGESTED_ROUTES = [
    'topic/getting-started',
    'topic/howto-first-connection',
    'topic/howto-backup-basemap',
    'topic/howto-xdf-editing',
    'topic/howto-afr-jetdrive-tuning',
    'topic/howto-custom-build-and-flash',
    'topic/tools-directory',
    'topic/checksums-overview',
    'topic/protocols-overview',
    'topic/ecus-overview',
    'topic/glossary',
  ];

  function defaultSpotlightResults() {
    const entries = ensureIndex();
    return SUGGESTED_ROUTES.map((route) => entries.find((entry) => entry.route === route))
      .filter(Boolean)
      .map((entry) => ({ entry, score: 0, snippet: esc(entry.subtitle) }));
  }

  function spotlightResults() {
    const query = state.spot.query.trim();
    if (!query) {
      const results = defaultSpotlightResults();
      if (state.spot.scope === 'all') return results;
      return results.filter((row) => row.entry.scope === state.spot.scope);
    }
    return search(query, { scope: state.spot.scope, limit: 30 });
  }

  function renderSpotlight() {
    const box = $('#helpSpotlightResults');
    if (!box) return;
    $$('#helpSpotlightFilters [data-spot-scope]').forEach((pill) => {
      pill.classList.toggle('active', pill.dataset.spotScope === state.spot.scope);
    });
    const results = spotlightResults();
    state.spot.results = results;
    if (!results.length) {
      box.innerHTML = state.spot.query.trim()
        ? '<div class="help-empty"><p>No matches. Try “5am”, “checksum”, “backup”, “harley”, “afr”, “protocol” or a menu command like “print”.</p></div>'
        : '<div class="help-empty"><p>Start typing to search this scope — try “5am”, “harley”, “mana” or “kwp2000”.</p></div>';
      return;
    }
    if (state.spot.cursor >= results.length) state.spot.cursor = 0;
    box.innerHTML = results.map((row, index) => {
      const entry = row.entry;
      return '<button type="button" role="option" aria-selected="' + (index === state.spot.cursor ? 'true' : 'false') + '"'
        + ' class="help-spot-result' + (index === state.spot.cursor ? ' active' : '') + '"'
        + ' data-spot-index="' + index + '" data-help-route="' + esc(entry.route) + '">'
        + '<span class="help-result-kind kind-' + esc(entry.kind) + '">' + esc(KIND_LABEL[entry.kind] || 'REF') + '</span>'
        + '<span class="help-result-main">'
        + '<span class="help-result-title">' + highlight(entry.title, tokenize(state.spot.query)) + '</span>'
        + '<span class="help-result-snippet">' + (row.snippet || esc(entry.subtitle)) + '</span>'
        + '</span>'
        + '<span class="help-spot-hint">Read ↵</span>'
        + '</button>';
    }).join('');
  }

  function openSpotlight() {
    const modal = $('#helpSpotlightModal');
    if (!modal) return;
    state.spot.open = true;
    state.spot.cursor = 0;
    modal.classList.remove('hidden');
    $$('#helpSpotlightFilters [data-spot-scope]').forEach((pill) => {
      pill.classList.toggle('active', pill.dataset.spotScope === state.spot.scope);
    });
    renderSpotlight();
    const input = $('#helpSpotlightInput');
    if (input) { input.value = state.spot.query; input.focus(); input.select(); }
    loadCatalogData();
    loadXdfData();
  }

  function closeSpotlight() {
    const modal = $('#helpSpotlightModal');
    if (!modal || modal.classList.contains('hidden')) return;
    modal.classList.add('hidden');
    state.spot.open = false;
  }

  function activateSpotlight(index) {
    const row = state.spot.results[index];
    if (!row) return;
    const entry = row.entry;
    closeSpotlight();
    if (entry.kind === 'action' && typeof entry.action === 'function') {
      entry.action();
      return;
    }
    if (entry.kind === 'panel' && entry.panel) {
      if (typeof window.guzziOpenWorkspaceTarget === 'function') {
        window.guzziOpenWorkspaceTarget({ view: entry.panel.view, selector: entry.panel.selector });
      }
      return;
    }
    // Guides open in the help center; tools/protocols/ECUs/XDFs render there too.
    openHelpRoute(entry.route);
  }

  /* ============================================================== events */

  function openHelpRoute(route, options) {
    const parsed = typeof route === 'string' ? resolveRoute(route) : route;
    const canonical = canonicalRoute(parsed);
    state.route = canonical;
    state.lastRendered = null;
    // Opening an article takes over from the result list: clear the filter so
    // the article pane is visible instead of sitting behind the results.
    if (state.query) {
      state.query = '';
      const input = $('#helpSearchInput');
      if (input) input.value = '';
    }
    go(canonical, options);
  }

  function bind() {
    document.addEventListener('click', (event) => {
      if (!event.target || typeof event.target.closest !== 'function') return;
      const target = event.target.closest('[data-help-route], [data-help-jump], [data-help-copy], [data-help-print], [data-help-open-spotlight], [data-spot-index]');
      if (!target) return;

      if (target.matches('[data-help-copy]')) {
        event.preventDefault();
        const url = location.origin + location.pathname + hashFor(resolveRoute(state.route || DEFAULT_ROUTE));
        const done = () => {
          const box = $('#helpCopyStatus');
          if (box) box.textContent = 'Link copied to the clipboard.';
          toast('Link copied to the clipboard.', 'ok');
        };
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(url).then(done).catch(() => {
            const box = $('#helpCopyStatus');
            if (box) box.textContent = url;
          });
        } else {
          const box = $('#helpCopyStatus');
          if (box) box.textContent = url;
        }
        return;
      }

      if (target.matches('[data-help-print]')) {
        event.preventDefault();
        window.print();
        return;
      }

      if (target.matches('[data-help-open-spotlight]')) {
        event.preventDefault();
        openSpotlight();
        return;
      }

      if (target.matches('[data-help-jump]')) {
        event.preventDefault();
        const view = target.dataset.jumpView;
        const selector = target.dataset.jumpSelector;
        const openDetails = target.dataset.jumpOpen;
        if (typeof window.guzziOpenWorkspaceTarget === 'function') {
          window.guzziOpenWorkspaceTarget({ view, selector, openDetails });
        } else {
          const nav = document.querySelector('.nav[data-view="' + view + '"]');
          if (nav) nav.click();
        }
        return;
      }

      if (target.matches('[data-spot-index]')) {
        event.preventDefault();
        state.spot.cursor = Number(target.dataset.spotIndex) || 0;
        activateSpotlight(state.spot.cursor);
        return;
      }

      if (target.matches('[data-help-route]')) {
        event.preventDefault();
        const route = target.dataset.helpRoute;
        if (!route) return;
        if (route.startsWith('action/') || route.startsWith('panel/')) {
          const entry = ensureIndex().find((candidate) => candidate.route === route);
          if (!entry) return;
          if (entry.kind === 'action' && typeof entry.action === 'function') {
            entry.action();
          } else if (entry.kind === 'panel' && entry.panel) {
            if (typeof window.guzziOpenWorkspaceTarget === 'function') {
              window.guzziOpenWorkspaceTarget({ view: entry.panel.view, selector: entry.panel.selector });
            }
          }
          return;
        }
        openHelpRoute(route);
      }
    });

    $$('#helpCategoryPills [data-help-cat]').forEach((pill) => {
      pill.addEventListener('click', () => {
        state.category = pill.dataset.helpCat || 'all';
        renderHelpCenter();
      });
    });

    const searchInput = $('#helpSearchInput');
    if (searchInput) {
      let timer = null;
      searchInput.addEventListener('input', () => {
        state.query = searchInput.value;
        clearTimeout(timer);
        timer = setTimeout(() => {
          renderSearchResultsPanel();
        }, 90);
      });
      searchInput.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') { state.query = ''; searchInput.value = ''; renderSearchResultsPanel(); }
      });
    }
    const clearBtn = $('#helpSearchClear');
    if (clearBtn) {
      clearBtn.addEventListener('click', () => {
        state.query = '';
        if (searchInput) { searchInput.value = ''; searchInput.focus(); }
        renderSearchResultsPanel();
      });
    }

    const openBtn = $('#helpOpenSpotlightBtn');
    if (openBtn) openBtn.addEventListener('click', openSpotlight);

    const modal = $('#helpSpotlightModal');
    if (modal) {
      modal.addEventListener('mousedown', (event) => {
        if (event.target === modal) closeSpotlight();
      });
    }
    const closeBtn = $('#helpSpotlightCloseBtn');
    if (closeBtn) closeBtn.addEventListener('click', closeSpotlight);
    const browseAll = $('#helpSpotlightBrowseAllBtn');
    if (browseAll) {
      browseAll.addEventListener('click', () => {
        closeSpotlight();
        openHelpRoute('topic/tools-search-and-links');
      });
    }

    $$('#helpSpotlightFilters [data-spot-scope]').forEach((pill) => {
      pill.addEventListener('click', () => {
        state.spot.scope = pill.dataset.spotScope || 'all';
        state.spot.cursor = 0;
        renderSpotlight();
      });
    });

    const spotInput = $('#helpSpotlightInput');
    if (spotInput) {
      spotInput.addEventListener('input', () => {
        state.spot.query = spotInput.value;
        state.spot.cursor = 0;
        renderSpotlight();
      });
      spotInput.addEventListener('keydown', (event) => {
        if (event.key === 'ArrowDown') {
          event.preventDefault();
          if (!state.spot.results.length) return;
          state.spot.cursor = (state.spot.cursor + 1) % state.spot.results.length;
          renderSpotlight();
          scrollSpotCursor();
        } else if (event.key === 'ArrowUp') {
          event.preventDefault();
          if (!state.spot.results.length) return;
          state.spot.cursor = (state.spot.cursor - 1 + state.spot.results.length) % state.spot.results.length;
          renderSpotlight();
          scrollSpotCursor();
        } else if (event.key === 'Enter') {
          event.preventDefault();
          activateSpotlight(state.spot.cursor);
        } else if (event.key === 'Escape') {
          event.preventDefault();
          closeSpotlight();
        }
      });
    }

    // menu-bar chip and Help menu entries
    const helpChip = $('#menubarHelpSearchBtn');
    if (helpChip) helpChip.addEventListener('click', openSpotlight);
    const helpMenuSpotlight = $('#helpMenuSpotlight');
    if (helpMenuSpotlight) helpMenuSpotlight.addEventListener('click', () => {
      closeMenus();
      openSpotlight();
    });
    $$('[data-help-topic]').forEach((item) => {
      item.addEventListener('click', () => {
        closeMenus();
        const topic = item.dataset.helpTopic;
        openHelpRoute(topic === 'glossary' ? 'glossary' : 'topic/' + topic);
      });
    });

    document.addEventListener('keydown', (event) => {
      const key = String(event.key || '').toLowerCase();
      const meta = event.ctrlKey || event.metaKey;
      if (meta && key === 'k') {
        event.preventDefault();
        if (state.spot.open) closeSpotlight(); else openSpotlight();
        return;
      }
      if (event.key === 'F1') {
        event.preventDefault();
        openHelpRoute(state.route || DEFAULT_ROUTE);
        return;
      }
      if (event.key === 'Escape' && state.spot.open) {
        event.preventDefault();
        closeSpotlight();
      }
    });

    window.addEventListener('hashchange', handleLocation);
    window.addEventListener('popstate', handleLocation);
    handleLocation({ initial: true });
  }

  function scrollSpotCursor() {
    const active = $('#helpSpotlightResults .help-spot-result.active');
    if (active && active.scrollIntoView) active.scrollIntoView({ block: 'nearest' });
  }

  function closeMenus() {
    $$('#appMenubar .dropdown-panel').forEach((panel) => { panel.hidden = true; });
    $$('#appMenubar [aria-haspopup="menu"]').forEach((btn) => btn.setAttribute('aria-expanded', 'false'));
  }

  function handleLocation(event) {
    const parsed = routeFromLocation();
    if (!parsed) {
      if (!event || event.initial) return;
      return;
    }
    if (parsed.term) state.pendingScrollTerm = parsed.term;
    // A hash navigation names one article: drop any list filter that would
    // otherwise keep the article pane hidden behind the results.
    if (state.query) {
      state.query = '';
      const input = $('#helpSearchInput');
      if (input) input.value = '';
    }
    state.route = canonicalRoute(parsed.parsed);
    state.lastRendered = null;
    if (helpIsVisible()) {
      renderHelpCenter();
    } else {
      const nav = $('.nav[data-view="help"]');
      if (nav) nav.click();
      else renderHelpCenter();
    }
  }

  /* ================================================================ init */

  window.renderHelpCenter = renderHelpCenter;
  window.guzziHelpOpen = (route) => openHelpRoute(route || DEFAULT_ROUTE);
  window.guzziHelpSearch = (query, options) => search(query, options).map((row) => ({
    route: row.entry.route,
    kind: row.entry.kind,
    title: row.entry.title,
    score: row.score,
  }));
  window.guzziHelpRoutes = () => ensureIndex().map((entry) => ({ route: entry.route, kind: entry.kind, title: entry.title }));
  window.guzziHelpState = state;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bind);
  } else {
    bind();
  }
}());
