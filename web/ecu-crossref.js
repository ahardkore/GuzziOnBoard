/* Catalog cross-reference only: never selects a vehicle or builds an image. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const select = $('sharedEcuFamily'), out = $('sharedEcuOut');
  let catalog = null, definitions = [];
  // Explicit mappings only: no substring matching or equivalence inference.
  const xdfFamilies = { p8: ['P8'], '16m': ['16M'], '15m': ['15M'], '15rc': ['15RC'],
    '5am': ['5AM'], '59m': ['59M'], '7sm': ['7SM'], miug3: ['MIUG3'],
    honda_cb500_mgz_a03: ['CB500-MGZ-A03'], honda_cbr1000rr_2012_us: ['CBR1000RR-2012-US'] };
  function add(parent, tag, text) { const el = document.createElement(tag); el.textContent = text; parent.append(el); return el; }
  $('sharedEcuLoad').onclick = async () => {
    select.disabled = true; out.textContent = 'Loading catalog…';
    try {
      const [c, maps] = await Promise.all([api('/api/catalog'), api('/api/maps')]);
      catalog = c; definitions = maps.xdfs || [];
      select.replaceChildren(new Option('— choose a profile —', ''));
      [...c.ecus].sort((a,b) => a.display_name.localeCompare(b.display_name)).forEach(profile => select.add(new Option(profile.display_name, profile.id)));
      const familyGroup = document.createElement('optgroup'); familyGroup.label = 'XDF family labels (definition catalog only)';
      [...new Set(definitions.filter(x => x.catalogued && x.family && x.family !== 'HONDA-RESEARCH').map(x => x.family))].sort().forEach(family => familyGroup.append(new Option(`XDF family · ${family}`, `xdf:${family}`)));
      select.append(familyGroup);
      select.disabled = false; out.textContent = 'Choose a profile to see its cataloged vehicles and related XDF family labels.';
    } catch (error) { out.textContent = `Could not load catalog: ${error.message}`; }
  };
  select.addEventListener('change', () => {
    out.replaceChildren();
    const isXdfFamily = select.value.startsWith('xdf:');
    const family = isXdfFamily ? select.value.slice(4) : '';
    const profile = catalog?.ecus.find(item => item.id === select.value);
    if (!profile && !family) return;
    add(out, 'p', profile ? `${profile.display_name} · catalog profile ${profile.id}. Same profile is not evidence of identical hardware or calibration.` : `XDF family label ${family} only; no vehicle-catalog profile equivalence is assumed.`);
    const vehicles = profile ? (catalog.models || []).flatMap(model => model.variants || []).filter(v => v.ecu === profile.id) : [];
    const unique = new Map(vehicles.map(v => [`${v.make}\0${v.model}\0${v.year_from}\0${v.year_to}`, v]));
    const sorted = [...unique.values()].sort((a,b) => a.make.localeCompare(b.make) || a.model.localeCompare(b.model) || a.year_from - b.year_from);
    add(out, 'h4', `Cataloged vehicle entries (${sorted.length})`);
    const list = document.createElement('ul');
    sorted.forEach(v => add(list, 'li', `${v.make} ${v.model} · ${v.year_from}–${v.year_to ?? 'present'} · ${v.confidence || 'unknown'}${v.notes ? ' · ' + v.notes : ''}`));
    if (sorted.length) out.append(list); else add(out, 'p', 'No model/year entries for this ECU-only profile.');
    const families = profile ? (xdfFamilies[profile.id] || []) : [family];
    const matching = definitions.filter(x => families.includes(x.family) && x.catalogued);
    add(out, 'h4', `Related cataloged XDF family labels (${matching.length})`);
    const xlist = document.createElement('ul');
    matching.sort((a,b) => a.label.localeCompare(b.label)).forEach(x => {
      const fit = (x.fits || []).map(f => `${f.brand_label}: ${f.label}`).join('; ');
      add(xlist, 'li', `${x.filename} · ${x.label}${x.research_only ? ' · RESEARCH ONLY' : ''}${fit ? ' · source-listed: ' + fit : ''}${x.source_url ? ' · source: ' + x.source_url : ''}`);
    });
    if (matching.length) out.append(xlist); else add(out, 'p', 'No explicit family-label cross-reference for this profile.');
    add(out, 'p', 'Vehicle entries come from the GuzziOnBoard vehicle catalog; each XDF displays its source and source-listed fitments. Do not transfer a tune between these entries without confirming the exact software, map layout and checksum. This view does not change vehicle selection or build permissions.');
  });
})();
