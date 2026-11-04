/* Curated BikeStudio reference facts. No requests or capability gates change. */
(() => {
  'use strict';
  const $b = id => document.getElementById(id);
  const make = $b('makeSelect'), model = $b('modelSelect'), year = $b('yearSelect');
  const garage = $b('bikeStudioGarage'), query = $b('bikeStudioQuery');
  const searchYear = $b('bikeStudioYear'), searchMarket = $b('bikeStudioMarket'), results = $b('bikeStudioResults');
  let groups = [];
  const norm = value => String(value || '').toUpperCase().replace(/[^A-Z0-9]/g, '');
  const add = (parent, tag, text) => { const node = document.createElement(tag); node.textContent = text; parent.append(node); return node; };
  const hondaReadParts = new Set(['38770MGZA03', '38770MGZC02', '38770MGZC03', '38770MGZD02',
    '38770MELD21', '38770MELF21', '38770MELA21', '38770MELA22', '38770MELL22',
    '38770MFL622', '38770MFL644', '38770MFL671', '38770MFL773', '38770MFL741', '38770MFL761', '38770MFLA21', '38770MFLD21',
    '38770MGPD01', '38770MGPF01', '38770MGPA01', '38770MGPL01', '38770MGPD62', '38770MGPF63', '38770MGPA92',
    '38770MJEG52', '38770MJED41', '38770MJEG12', '38770MGMD11', '38770MFJD04', '38770MFJF03', '38770MJWAQ1',
    '38770KYJ922', '38770KPPN02', '38770KPPT03',
    '38770K26911', '38770K26931', '38770K26B13', '38770K26C31',
    '38770MKFD43', '38770MNFD01', '38770MNFF01', '38770MFND01', '38770MFNF01', '38770K0FA01', '38770KYKD12']);
  function addReadLead(parent, part) {
    if (!hondaReadParts.has(norm(part))) return;
    add(parent, 'span', ' · Desktop: separate Honda PGM-FI ECU-only experimental image read requires its own confirmation and an exact live ECM ID. Synthetic-tested only, not hardware-verified; this listing does not enable a read or write.');
  }
  const sourceModel = group => `https://bikestudio.io/ecu/m/${group.slug}?lang=en`;
  const sourcePart = part => `https://bikestudio.io/ecu/${part.toLowerCase().replace(/[^a-z0-9]+/g, '-')}?lang=en`;
  const link = (parent, url, text) => {
    const a = add(parent, 'a', text); a.href = url; a.target = '_blank'; a.rel = 'noopener noreferrer'; return a;
  };
  function yearStatus(value, chosen) {
    if (!value) return 'unknown';
    const match = /^(\d{4})(?:[–-](\d{4}))?$/.exec(value);
    if (!match) return 'invalid';
    const start = Number(match[1]), end = Number(match[2] || match[1]);
    if (start < 1900 || end > 2100 || start > end) return 'invalid';
    return !chosen || (chosen >= start && chosen <= end) ? 'match' : 'outside';
  }
  function info(item, chosen) {
    const status = yearStatus(item.years, chosen);
    return `${item.part} · source years: ${item.years || 'not stated'}${status === 'invalid' ? ' (invalid source range; review)' : status === 'unknown' ? ' (year unknown)' : ''} · market: ${item.market || 'not stated'} · source cc: ${item.cc || 'not stated'}`;
  }
  function marketMatches(item, filter) {
    const wanted = filter.trim().toLocaleLowerCase(), actual = (item.market || '').trim().toLocaleLowerCase();
    return !wanted || !actual || actual === wanted;
  }
  function candidates(group, chosen, market = '') {
    return group.entries.filter(item => yearStatus(item.years, chosen) !== 'outside' && marketMatches(item, market));
  }
  function renderGarage() {
    garage.replaceChildren();
    if (!model.value || !year.value) { add(garage, 'p', 'Select a brand, year and model to see any curated BikeStudio reference candidates.'); return; }
    const relevant = groups.filter(g => g.make === make.value && g.garage_models.includes(model.value));
    if (!relevant.length) { const p = add(garage, 'p', 'No curated BikeStudio model match here. '); link(p, 'https://bikestudio.io/ecu?lang=en', 'Open the full source database'); return; }
    add(garage, 'p', 'BikeStudio part candidates, not ECU identification or proof of protocol support. Source years/cc may contain errors; compare the ECU label and market.');
    for (const g of relevant) {
      const hits = candidates(g, Number(year.value));
      const p = add(garage, 'p', `${g.make} ${g.model}: ${hits.length} candidate(s), including unknown/invalid years. `);
      link(p, sourceModel(g), 'Source model page');
      const list = document.createElement('ul');
      for (const item of hits) { const li = add(list, 'li', info(item, Number(year.value)) + ' · '); link(li, sourcePart(item.part), 'source part'); addReadLead(li, item.part); }
      if (hits.length) garage.append(list);
    }
  }
  function selectBike(group, name, y) {
    // Garage selection runs brand -> year -> model: the model list only
    // offers models catalogued for the chosen year, so set the year first.
    if (state.connected || ![...make.options].some(o => o.value === group.make)) return;
    make.value = group.make; make.dispatchEvent(new Event('change', {bubbles:true}));
    if (![...year.options].some(o => o.value === String(y))) return;
    year.value = String(y); year.dispatchEvent(new Event('change', {bubbles:true}));
    if (![...model.options].some(o => o.value === name)) return;
    model.value = name; model.dispatchEvent(new Event('change', {bubbles:true}));
    renderGarage();
  }
  function renderSearch() {
    results.replaceChildren();
    const needle = norm(query.value);
    const y = searchYear.value ? Number(searchYear.value) : null;
    if (needle.length < 2) { add(results, 'p', 'Enter at least two letters or digits to search the partial index.'); return; }
    if (y !== null && (!Number.isInteger(y) || y < 1900 || y > 2100)) { add(results, 'p', 'Enter a year from 1900 to 2100, or leave it blank.'); return; }
    let total = 0;
    for (const group of groups) {
      const groupText = norm([group.make, group.model, ...group.aliases].join(' '));
      const modelMatch = groupText.includes(needle) || norm(group.model).includes(needle) || group.aliases.some(a => norm(a).includes(needle));
      const hits = candidates(group, y, searchMarket.value).filter(item => modelMatch || norm(item.part).includes(needle));
      if (!hits.length) continue;
      total += hits.length;
      const box = document.createElement('div'); box.className = 'gate-card warn';
      add(box, 'h4', `${group.make} ${group.model}`);
      const src = add(box, 'p', `Also listed as: ${group.aliases.join(', ') || 'none'}. `); link(src, sourceModel(group), 'BikeStudio model page');
      const list = document.createElement('ul');
      for (const item of hits) { const li = add(list, 'li', info(item, y) + ' · '); link(li, sourcePart(item.part), 'source part'); addReadLead(li, item.part); }
      box.append(list);
      // User must choose a specific existing garage model and year; no ECU
      // part is assigned and the normal selection and capability gates remain.
      if (y && !state.connected && [...make.options].some(o => o.value === group.make)) {
        for (const name of group.garage_models) {
          if (!state.catalog?.vehicles?.some(v => v.make === group.make && v.model === name && v.year_from <= y && (!v.year_to || y <= v.year_to))) continue;
          const btn = add(box, 'button', `Choose ${group.make} ${name} ${y} in Garage`); btn.type = 'button'; btn.className = 'btn small';
          btn.onclick = () => selectBike(group, name, y);
        }
      }
      results.append(box);
    }
    if (!total) add(results, 'p', 'No candidate in the curated subset. Try the full BikeStudio database; a missing result does not rule out fitment.');
    else { const note = document.createElement('p'); note.textContent = `${total} source-listed candidate(s). Unknown and invalid years remain visible. No automatic ECU selection or capability change.`; results.prepend(note); }
  }
  // Optional public source lookup: one index or one model page per explicit
  // click. Never upload local vehicle details, identifiers or ECU images.
  const onlineLoad = $b('bikeStudioOnlineLoad'), onlineRead = $b('bikeStudioOnlineRead');
  const onlineFilter = $b('bikeStudioOnlineFilter'), onlineModel = $b('bikeStudioOnlineModel');
  const onlineOut = $b('bikeStudioOnlineOut');
  let publicModels = [], publicRows = [], publicSlug = '', onlineBusy = false;
  function listModels() {
    const previous = onlineModel.value, needle = norm(onlineFilter.value);
    onlineModel.replaceChildren(new Option('— choose a source model —', ''));
    for (const item of publicModels) {
      const name = `${item.slug.startsWith('honda-') ? 'Honda' : 'Yamaha'} ${item.label}`;
      if (!needle || norm(name + ' ' + item.aliases).includes(needle)) onlineModel.add(new Option(name, item.slug));
    }
    if ([...onlineModel.options].some(option => option.value === previous)) onlineModel.value = previous;
    onlineModel.disabled = onlineBusy || publicModels.length === 0;
    onlineRead.disabled = onlineBusy || !onlineModel.value;
    if (onlineModel.value !== publicSlug) { publicRows = []; publicSlug = ''; }
  }
  function renderOnlineRows() {
    if (!publicSlug || !publicRows.length) return;
    onlineOut.replaceChildren();
    const chosen = searchYear.value ? Number(searchYear.value) : null;
    if (chosen !== null && (!Number.isInteger(chosen) || chosen < 1900 || chosen > 2100)) {
      add(onlineOut, 'p', 'Enter a year from 1900 to 2100 above, or leave it blank.'); return;
    }
    const hits = publicRows.filter(item => yearStatus(item.years, chosen) !== 'outside' && marketMatches(item, searchMarket.value));
    const p = add(onlineOut, 'p', `${hits.length} source-listed part(s) for the selected model; unknown or invalid years remain visible. Data is not proof of ECU identity, fitment or protocol. `);
    link(p, `https://bikestudio.io/ecu/m/${publicSlug}?lang=en`, 'Open source page');
    const list = document.createElement('ul');
    for (const item of hits) {
      const li = add(list, 'li', info(item, chosen) + ' · ');
      if (/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(item.part_slug)) link(li, `https://bikestudio.io/ecu/${item.part_slug}?lang=en`, 'source part');
      addReadLead(li, item.part);
    }
    onlineOut.append(list);
  }
  function busyOnline(value) {
    onlineBusy = value; onlineLoad.disabled = value; onlineFilter.disabled = value;
    listModels();
  }
  onlineFilter.addEventListener('input', () => { listModels(); if (!publicSlug) onlineOut.textContent = 'Choose a source model to load its part table.'; });
  onlineModel.addEventListener('change', () => { publicRows = []; publicSlug = ''; listModels(); onlineOut.textContent = 'Model selected; load its public part table explicitly.'; });
  for (const el of [searchYear, searchMarket]) el.addEventListener('input', renderOnlineRows);
  onlineLoad.onclick = async () => {
    if (isHostedDemo()) { onlineOut.textContent = 'The hosted demo cannot fetch BikeStudio; use the source link below.'; return; }
    publicModels = []; publicRows = []; publicSlug = ''; busyOnline(true);
    onlineOut.textContent = 'Requesting the public BikeStudio model index…';
    try {
      const data = await api('/api/tools/bikestudio', {method:'POST', body:{kind:'index', confirm_external:true}});
      if (!Array.isArray(data.models)) throw new Error('Invalid model index.');
      publicModels = data.models.filter(m => /^(?:honda|yamaha)-[a-z0-9]+(?:-[a-z0-9]+)*$/.test(m.slug) && typeof m.label === 'string' && typeof m.aliases === 'string');
      onlineOut.textContent = `Loaded ${publicModels.length} public model links. Filter and select a model; no part page has been requested yet.`;
    } catch (e) { onlineOut.textContent = `Could not load the index: ${e.message}`; }
    finally { busyOnline(false); }
  };
  onlineRead.onclick = async () => {
    if (isHostedDemo() || !onlineModel.value || onlineBusy) return;
    const slug = onlineModel.value; publicRows = []; publicSlug = ''; busyOnline(true);
    onlineOut.textContent = 'Requesting the selected public ECU part table…';
    try {
      const data = await api('/api/tools/bikestudio', {method:'POST', body:{kind:'model', slug, confirm_external:true}});
      if (data.slug !== slug || !Array.isArray(data.rows)) throw new Error('Invalid model reply.');
      publicRows = data.rows; publicSlug = slug; renderOnlineRows();
    } catch (e) { onlineOut.textContent = `Could not load this model: ${e.message}`; }
    finally { busyOnline(false); }
  };

  for (const el of [make,model,year]) el.addEventListener('change', renderGarage);
  document.addEventListener('gob-catalog-ready', renderGarage);
  for (const el of [query,searchYear,searchMarket]) el.addEventListener('input', renderSearch);
  fetch('bikestudio-fitment.json', {cache:'no-cache'}).then(r => { if (!r.ok) throw new Error('reference index unavailable'); return r.json(); })
    .then(data => { groups = data.groups; renderGarage(); renderSearch(); })
    .catch(() => { garage.textContent = 'Local reference index unavailable; open the BikeStudio database directly.'; results.textContent = 'Local reference index unavailable.'; });
})();
