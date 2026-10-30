/* Offline ECU-number research. External catalog links are user-initiated;
 * no imported or bundled record is used to select an ECU or authorize a build. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const sources = {
    mgz: 'MotoBinFiles product listing, 38770-MGZ-A03 (consulted 2026-10-29): https://motobinfiles.com/product/38770-mgz-a03-cbr500r-cb500f-2013-2015-xdf/',
    cf: 'MotoBinFiles product listing, F01RB0D7BS / XC0105AED4 (consulted 2026-10-29): https://motobinfiles.com/product/f01rb0d7bs-xc0105aed4-xdf/',
    ninja7: 'Kawasaki CAN research, source-reported Ninja 7 Hybrid example: https://github.com/mgithens1/kawasaki-can-hack/tree/26820ddf88d682c7071b0825252c7fa0b82c709a',
    zx636: 'Woolich Racing, ZX6R (636) 2024–2026 grouped ECU listing: https://www.woolichracing.com/products/kawasaki/zx6r-636/2026/2026-kawasaki-zx6r-636-ecu-flashing.aspx',
    ninja650: 'Woolich Racing, Ninja 650 / EX650 2023–2026 grouped ECU listing: https://www.woolichracing.com/products/kawasaki/ninja-650-ex650/2026/2026-kawasaki-ninja-650-ex650-ecu-flashing.aspx',
    ninja650parts: 'SRS Motorsports parts viewer, 2026 EX650RTFNN fuel injection; diagram lists both parts without distinguishing applications: https://www.srsmotorsports.com/Parts/Parts-Viewer/kawasaki/motorcycles/2026/ninja-650-ex650rtfnn/fuel-injection/c8be47ab-2e32-492a-8d75-a6012da9b6f1',
    ninja650abs: 'Tri County Cycle parts viewer, 2026 EX650PTFAN fuel injection: https://www.tricountycycle.com/Parts/Parts-Finder/kawasaki/motorcycles/2026/ninja-650-ex650ptfan/fuel-injection/ccbd210d-4ff6-483a-a78f-31f4fc69adbb',
    z650: 'Woolich Racing, Z650 feature list 2023–2026; product title 2023–2025: https://www.woolichracing.com/products/kawasaki/z650/kawasaki-z650-ecu-flashing.aspx',
    buell: 'EcmSpy supported ECM types (consulted 2026-10-29): https://www.ecmspy.com/supported.shtml',
  };
  // A few attributed factual examples, not a copy of either vendor's catalog.
  const kawasakiRows = [
    ...['1912','1915','1916','1917','1918','1919','1920','1923','1925','1926','2343']
      .map(part => ({ part: '21175-' + part, reference: '', vehicle: 'Kawasaki Ninja ZX-6R (636), 2024–2026 grouped listing', source: sources.zx636 })),
    ...[['1782',''],['1783',''],['1784',''],['1805',''],['1910','TMQ2KQE0'],['1910','TMQ2KQE1'],['1910','TMQ2KQEA'],['1950',''],['1951',''],['1952','TMQ2KQL0']]
      .map(([part, reference]) => ({ part: '21175-' + part, reference, vehicle: 'Kawasaki Ninja 650 / EX650, 2023–2026 grouped listing', source: sources.ninja650 })),
    ...['1951', '1952'].map(part => ({ part: '21175-' + part, reference: '', vehicle: 'Kawasaki Ninja 650 EX650RTFNN, 2026 parts-diagram candidate (application unspecified)', source: sources.ninja650parts })),
    { part: '21175-1952', reference: '', vehicle: 'Kawasaki Ninja 650 ABS EX650PTFAN, 2026 parts-diagram candidate', source: sources.ninja650abs },
    ...[['1782','TMQ3KQE2'],['1805','TMQ1KQL1'],['1910','TMQ2KQE1'],['1910','TMQ2KQE3'],['1911','TMQ2KQJ0'],['1929','TMQ2KQEA'],['1951','TMQ2KQU0'],['1952','TMQ2KQL1']]
      .map(([part, reference]) => ({ part: '21175-' + part, reference, vehicle: 'Kawasaki Z650, 2023–2026 feature list (product title 2023–2025)', source: sources.z650 })),
  ].map(record => ({ hardware: '', software: '', ...record }));
  const bundled = [
    ...kawasakiRows,
    { part: '49245-2655', hardware: '', software: '2102D11220244156', vehicle: 'Kawasaki Ninja 7 Hybrid, 2024+ (source-reported current ECU example)', source: sources.ninja7 },
    { part: '49245-230500000', hardware: '26105-0001', software: '2102D11220244156', vehicle: 'Kawasaki Ninja 7 Hybrid (source-reported broadcast identifiers; ECU part differs from KWP)', source: sources.ninja7 },
    { part: '38770-MGZ-A03', hardware: 'MGZA401', software: '0101250501', vehicle: 'Honda CBR500R / CB500F, 2013–2015 (vendor listing)', source: sources.mgz },
    { part: '', hardware: 'F01RB0D7BS', software: 'XC0105AED4', vehicle: 'CF Moto CForce 500, 2020 (vendor known reads)', source: sources.cf },
    { part: 'BUECB', hardware: '', software: '', vehicle: 'Buell XB9, 2003 (EcmSpy OEM equipment listing)', source: sources.buell },
    { part: 'BUEIB', hardware: '', software: '', vehicle: 'Buell XB, 2005–2007 (EcmSpy OEM equipment listing)', source: sources.buell },
    { part: 'B2RIB', hardware: '', software: '', vehicle: 'Buell XB, 2005–2007 (Factory Race ECM; EcmSpy listing)', source: sources.buell },
    { part: 'BUEIC', hardware: '', software: '', vehicle: 'Buell XB, 2005–2007 (Japan only; EcmSpy listing)', source: sources.buell },
  ];
  const fields = [['part', 'Part / ECM type', 'ecuPart'], ['hardware', 'Hardware', 'ecuHardware'], ['software', 'Software', 'ecuSoftware'], ['reference', 'Source reference code', 'ecuReference']];
  let local = [], generation = 0;
  const normalize = text => text.toUpperCase().replace(/[ ._/-]/g, '');
  const validId = text => !text || (/^[A-Za-z0-9 ._/-]{1,80}$/.test(text) && /[A-Za-z0-9]/.test(text));
  const clearResults = () => { $('ecuLookupOut').replaceChildren(); $('ecuLookupExternal').replaceChildren(); };
  const addText = (parent, tag, text) => { const node = document.createElement(tag); node.textContent = text; parent.append(node); return node; };

  function parseRecords(text) {
    const data = JSON.parse(text);
    if (!data || !Array.isArray(data.records) || !data.records.length || data.records.length > 1000) throw new Error('Expected 1–1000 records.');
    return data.records.map((record, index) => {
      if (!record || typeof record !== 'object' || Array.isArray(record)) throw new Error(`Invalid record ${index + 1}.`);
      const result = {};
      for (const key of ['part', 'hardware', 'software', 'reference', 'vehicle', 'source']) {
        const value = record[key] === undefined ? '' : record[key];
        if (typeof value !== 'string' || value.length > (key === 'source' ? 500 : key === 'vehicle' ? 300 : 80)) throw new Error(`Invalid ${key} in record ${index + 1}.`);
        result[key] = value.trim();
      }
      if (!result.vehicle || !result.source || !fields.some(([key]) => result[key]) || fields.some(([key]) => !validId(result[key]))) throw new Error(`Record ${index + 1} needs a vehicle, source and valid identifier.`);
      return result;
    });
  }

  $('ecuLookupBtn').addEventListener('click', () => {
    clearResults();
    const input = Object.fromEntries(fields.map(([key, , id]) => [key, $(id).value.trim()]));
    const out = $('ecuLookupOut');
    if (!Object.values(input).some(Boolean) || Object.values(input).some(value => !validId(value))) {
      addText(out, 'p', 'Enter at least one identifier using letters, numbers, spaces, hyphens, dots, underscores or slashes.'); return;
    }
    const hits = [...bundled, ...local].filter(record => fields.some(([key]) => input[key] && record[key] && normalize(input[key]) === normalize(record[key])));
    addText(out, 'p', `${hits.length} local candidate(s). Matching does not identify the installed ECU or authorize a build.`);
    hits.slice(0, 100).forEach(record => {
      const card = document.createElement('div'); card.className = 'gate-card warn';
      addText(card, 'h4', record.vehicle);
      const list = document.createElement('ul');
      fields.forEach(([key, title]) => {
        let state = 'not supplied';
        if (input[key]) state = !record[key] ? 'not stated by source' : normalize(input[key]) === normalize(record[key]) ? 'exact normalized match' : 'DIFFERENT — review';
        addText(list, 'li', `${title}: ${record[key] || 'not stated'} (${state})`);
      });
      card.append(list); addText(card, 'p', `Source: ${record.source}`); out.append(card);
    });
    if (hits.length > 100) addText(out, 'p', 'Showing the first 100 candidates; refine the identifiers.');
    const external = $('ecuLookupExternal');
    addText(external, 'p', 'Optional external MotoBinFiles catalog search (identifier is sent only when opened):');
    const list = document.createElement('ul');
    fields.filter(([key]) => input[key]).forEach(([key, title]) => {
      const li = document.createElement('li'); const link = document.createElement('a');
      link.textContent = `Search ${title}: ${input[key]}`;
      link.href = `https://motobinfiles.com/?s=${encodeURIComponent(input[key])}&post_type=product`;
      link.target = '_blank'; link.rel = 'noopener noreferrer'; li.append(link); list.append(li);
    });
    external.append(list);
  });
  fields.forEach(([, , id]) => $(id).addEventListener('input', clearResults));
  $('ecuLookupClear').addEventListener('click', () => { fields.forEach(([, , id]) => { $(id).value = ''; }); clearResults(); });
  $('ecuLookupFileClear').addEventListener('click', () => {
    generation++; local = []; $('ecuLookupFile').value = ''; $('ecuLookupFileStatus').textContent = 'No local list loaded.'; clearResults();
  });
  $('ecuLookupFile').addEventListener('change', async event => {
    const myGeneration = ++generation; const file = event.target.files[0]; local = []; clearResults();
    if (!file) { $('ecuLookupFileStatus').textContent = 'No local list loaded.'; return; }
    try {
      if (file.size > 512 * 1024) throw new Error('File exceeds 512 KiB.');
      const records = parseRecords(await file.text());
      if (myGeneration !== generation) return;
      local = records; $('ecuLookupFileStatus').textContent = `${local.length} local record(s) loaded from ${file.name}; not verified.`;
    } catch (error) {
      if (myGeneration !== generation) return;
      $('ecuLookupFileStatus').textContent = `Not loaded: ${error.message}`;
    }
  });
})();
