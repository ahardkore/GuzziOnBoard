/* Offline workshop worksheets. No external documents, templates or code are
 * bundled. Ideas informed by motorcycle-service-db and manual-rag-assistant;
 * this is a separate, literal-search implementation, not RAG or AI. */
'use strict';

const workshop = { templates: [], templateFile: '', intervalSource: null, manual: null, manualLoad: 0, templateLoad: 0 };
const byId = (id) => document.getElementById(id);

function serviceInteger(text, label, max, minimum = 0) {
  if (!/^\d+$/.test(String(text))) throw new Error(`${label} must be a whole number.`);
  const n = Number(text);
  if (!Number.isSafeInteger(n) || n < minimum || n > max) throw new Error(`${label} is outside the allowed range.`);
  return n;
}

function serviceDate(text, label) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(text)) throw new Error(`${label} needs a valid date.`);
  const [year, month, day] = text.split('-').map(Number);
  if (year < 1 || year > 9999 || month < 1 || month > 12 || day < 1 || day > 31) throw new Error(`${label} needs a valid date.`);
  const date = new Date(0);
  date.setUTCHours(0, 0, 0, 0);
  date.setUTCFullYear(year, month - 1, day);
  if (date.getUTCFullYear() !== year || date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day) {
    throw new Error(`${label} needs a valid date.`);
  }
  return date;
}

function addServiceMonths(date, months) {
  const total = date.getUTCFullYear() * 12 + date.getUTCMonth() + months;
  const year = Math.floor(total / 12), month = total % 12;
  if (year > 9999) throw new Error('Calculated date is outside the supported calendar.');
  const last = new Date(0);
  last.setUTCHours(0, 0, 0, 0);
  last.setUTCFullYear(year, month + 1, 0);
  const result = new Date(0);
  result.setUTCHours(0, 0, 0, 0);
  result.setUTCFullYear(year, month, Math.min(date.getUTCDate(), last.getUTCDate()));
  return result;
}

function calculateServiceDue(values) {
  const distance = [values.lastKm, values.currentKm, values.intervalKm].map((v) => String(v).trim());
  const dates = [values.lastDate, values.asOfDate, values.intervalMonths].map((v) => String(v).trim());
  const useDistance = distance.some(Boolean);
  // The as-of date can be filled in advance without requiring a date interval.
  const useDate = Boolean(dates[0] || dates[2]);
  if (!useDistance && !useDate) throw new Error('Complete a distance group, a date group, or both.');
  const result = {};
  if (useDistance) {
    if (distance.some((v) => !v)) throw new Error('Distance needs the last service, current odometer and interval.');
    const last = serviceInteger(distance[0], 'Last service', 10000000);
    const current = serviceInteger(distance[1], 'Current odometer', 10000000);
    const interval = serviceInteger(distance[2], 'Distance interval', 10000000, 1);
    if (current < last) throw new Error('Current odometer is below the last service; check for an odometer change.');
    const next = last + interval;
    result.distance = { next, remaining: next - current, due: current >= next };
  }
  if (useDate) {
    if (dates.some((v) => !v)) throw new Error('Date calculation needs the last service, as-of date and interval.');
    const last = serviceDate(dates[0], 'Last service date');
    const asOf = serviceDate(dates[1], 'As-of date');
    const months = serviceInteger(dates[2], 'Month interval', 1200, 1);
    if (asOf < last) throw new Error('As-of date is before the recorded service date.');
    const next = addServiceMonths(last, months);
    result.date = { next: next.toISOString().slice(0, 10), remainingDays: Math.round((next - asOf) / 86400000), due: asOf >= next };
  }
  return result;
}

function serviceInputs() {
  return { lastKm: byId('serviceLastKm').value, currentKm: byId('serviceCurrentKm').value,
    intervalKm: byId('serviceIntervalKm').value, lastDate: byId('serviceLastDate').value,
    asOfDate: byId('serviceAsOfDate').value, intervalMonths: byId('serviceIntervalMonths').value };
}

byId('serviceDueBtn').onclick = () => {
  const out = byId('serviceDueOut');
  try {
    const result = calculateServiceDue(serviceInputs());
    const rows = [];
    if (result.distance) rows.push(`<li>Distance threshold: <b>${result.distance.next} km</b> — ${result.distance.due ? `due or overdue by ${Math.abs(result.distance.remaining)} km` : `${result.distance.remaining} km remaining`}.</li>`);
    if (result.date) rows.push(`<li>Date threshold: <b>${result.date.next}</b> — ${result.date.due ? `due or overdue by ${Math.abs(result.date.remainingDays)} day(s)` : `${result.date.remainingDays} day(s) remaining`}.</li>`);
    const source = workshop.intervalSource ? `Intervals copied from ${workshop.intervalSource}; fitment not verified.` : 'Intervals entered manually; source not verified.';
    out.innerHTML = `<div class="gate-card warn"><h4>Review against the exact manual</h4><ul>${rows.join('')}</ul><p class="small">${esc(source)} Based only on the entered service history and repeating intervals; initial services and severe-use requirements are not calculated.</p></div>`;
  } catch (error) { out.innerHTML = `<div class="gate-card bad"><h4>Not calculated</h4><p>${esc(error.message)}</p></div>`; }
};
['serviceLastKm', 'serviceCurrentKm', 'serviceIntervalKm', 'serviceLastDate', 'serviceAsOfDate', 'serviceIntervalMonths'].forEach((id) => {
  byId(id).addEventListener('input', () => {
    byId('serviceDueOut').textContent = '';
    if (id === 'serviceIntervalKm' || id === 'serviceIntervalMonths') workshop.intervalSource = null;
  });
});

// Support a bounded, reviewed subset of the public template shape; no network
// access, automatic fitment matching, embedded HTML, or external link execution.
function parseServiceTemplates(text) {
  const data = JSON.parse(text);
  if (!data || !Array.isArray(data.motorcycles) || !data.motorcycles.length || data.motorcycles.length > 100) throw new Error('Expected 1–100 motorcycles in a template JSON.');
  const maxText = (v, max) => typeof v === 'string' && v.length <= max;
  return data.motorcycles.map((model) => {
    if (!model || !maxText(model.name, 200) || !model.name.trim() || !maxText(model.description, 2000)
      || !Array.isArray(model.tasks) || model.tasks.length > 500) throw new Error('A template model has invalid name, description or tasks.');
    const tasks = model.tasks.map((task) => {
      if (!task || !maxText(task.name, 200) || !task.name.trim() || !maxText(task.description, 2000)
        || (task.notes !== undefined && !maxText(task.notes, 10000))) throw new Error('A template task is invalid.');
      const item = { name: task.name, description: task.description, notes: task.notes || '' };
      for (const key of ['km', 'months', 'intervalKm', 'intervalMonths']) {
        if (task[key] !== undefined) {
          if (!Number.isSafeInteger(task[key]) || task[key] < 0 || task[key] > 10000000) throw new Error(`Invalid ${key} in a template task.`);
          item[key] = task[key];
        }
      }
      return item;
    });
    return { name: model.name, description: model.description, tasks };
  });
}

function selectedTemplateTask() {
  const model = workshop.templates[Number(byId('serviceTemplateModel').value)];
  return model?.tasks[Number(byId('serviceTemplateTask').value)] || null;
}
function renderServiceTemplate() {
  const modelValue = byId('serviceTemplateModel').value;
  const model = modelValue === '' ? null : workshop.templates[Number(modelValue)];
  const taskValue = byId('serviceTemplateTask').value;
  const task = taskValue === '' ? null : selectedTemplateTask();
  byId('serviceUseIntervals').disabled = !task || task.intervalMonths > 1200 || !(task.intervalKm > 0 || task.intervalMonths > 0);
  if (!model) { byId('serviceTemplateOut').textContent = 'Choose a model and task; verify fitment in its original source.'; return; }
  let detail = `${model.name} — ${model.description}`;
  if (task) {
    const present = (key, suffix) => task[key] !== undefined ? `${task[key]} ${suffix}` : 'not specified';
    detail += `\n${task.name}: ${task.description}\nInitial: ${present('km', 'km')}, ${present('months', 'months')}; repeat: ${present('intervalKm', 'km')}, ${present('intervalMonths', 'months')}.`;
    if (task.intervalMonths > 1200) detail += '\nRepeat interval exceeds the worksheet limit; copying is disabled. Verify the original source.';
    if (task.notes) detail += `\nNotes: ${task.notes}`;
  }
  byId('serviceTemplateOut').textContent = detail;
}

byId('serviceTemplateFile').onchange = async (event) => {
  const token = ++workshop.templateLoad;
  workshop.templates = [];
  byId('serviceTemplateModel').innerHTML = '<option value="">— choose a model —</option>';
  byId('serviceTemplateTask').innerHTML = '<option value="">— choose a task —</option>';
  byId('serviceTemplateModel').disabled = true; byId('serviceTemplateTask').disabled = true;
  byId('serviceUseIntervals').disabled = true; byId('serviceTemplateOut').textContent = '';
  const file = event.target.files?.[0];
  if (!file) return;
  try {
    if (file.size > 2 * 1024 * 1024) throw new Error('Template exceeds 2 MiB.');
    const text = await file.text();
    const templates = parseServiceTemplates(text);
    if (token !== workshop.templateLoad) return;
    workshop.templates = templates; workshop.templateFile = file.name;
    byId('serviceTemplateModel').innerHTML = '<option value="">— choose a model —</option>'
      + templates.map((model, index) => `<option value="${index}">${esc(model.name)}</option>`).join('');
    byId('serviceTemplateModel').disabled = false;
    byId('serviceTemplateOut').textContent = `${file.name}: ${templates.length} model(s) loaded for review. Verify fitment and license.`;
  } catch (error) { if (token === workshop.templateLoad) byId('serviceTemplateOut').textContent = `Could not load template: ${error.message}`; }
};
byId('serviceTemplateModel').onchange = () => {
  const value = byId('serviceTemplateModel').value;
  const model = value === '' ? null : workshop.templates[Number(value)];
  byId('serviceTemplateTask').innerHTML = '<option value="">— choose a task —</option>'
    + (model?.tasks || []).map((task, index) => `<option value="${index}">${esc(task.name)} — ${esc(task.description)}</option>`).join('');
  byId('serviceTemplateTask').disabled = !model;
  renderServiceTemplate();
};
byId('serviceTemplateTask').onchange = renderServiceTemplate;
byId('serviceUseIntervals').onclick = () => {
  const task = selectedTemplateTask();
  if (!task || task.intervalMonths > 1200 || !(task.intervalKm > 0 || task.intervalMonths > 0)) return;
  byId('serviceIntervalKm').value = task.intervalKm > 0 ? task.intervalKm : '';
  byId('serviceIntervalMonths').value = task.intervalMonths > 0 ? task.intervalMonths : '';
  const model = workshop.templates[Number(byId('serviceTemplateModel').value)];
  workshop.intervalSource = `${workshop.templateFile} / ${model.name} / ${task.name}`;
  byId('serviceDueOut').textContent = '';
  toast('Recurring intervals copied. Confirm the exact model and service history.', 'warn');
};

function searchManualText(manual, query) {
  const needle = query.trim();
  if (!needle || needle.length > 200) throw new Error('Enter 1–200 characters to search.');
  // Escaped literal regex keeps match offsets in the original string even
  // when Unicode case conversion would change string length.
  const escaped = needle.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const segments = manual.text.split('\f');
  const matches = [];
  let truncated = false;
  for (let index = 0; index < segments.length; index += 1) {
    const text = segments[index], pattern = new RegExp(escaped, 'giu');
    let match;
    while ((match = pattern.exec(text)) !== null) {
      if (matches.length === 100) { truncated = true; break; }
      const start = Math.max(0, match.index - 100), end = Math.min(text.length, match.index + match[0].length + 100);
      matches.push({ segment: index + 1, excerpt: `${start ? '…' : ''}${text.slice(start, end)}${end < text.length ? '…' : ''}` });
    }
    if (truncated) break;
  }
  return { matches, truncated, segments: segments.length };
}

function clearManualText() {
  ++workshop.manualLoad; workshop.manual = null;
  byId('manualTextFile').value = ''; byId('manualTextStatus').textContent = 'No manual loaded.';
  byId('manualTextOut').textContent = ''; byId('manualTextSearch').disabled = true;
}
byId('manualTextClear').onclick = clearManualText;
byId('manualTextFile').onchange = async (event) => {
  const token = ++workshop.manualLoad;
  workshop.manual = null; byId('manualTextSearch').disabled = true; byId('manualTextOut').textContent = '';
  const file = event.target.files?.[0];
  if (!file) { byId('manualTextStatus').textContent = 'No manual loaded.'; return; }
  try {
    if (!/\.txt$/i.test(file.name)) throw new Error('Choose a UTF-8 .txt export, not a PDF.');
    if (file.size > 5 * 1024 * 1024) throw new Error('Text file exceeds 5 MiB.');
    const buffer = await file.arrayBuffer();
    const text = new TextDecoder('utf-8', { fatal: true }).decode(buffer);
    if (text.includes('\0') || text.startsWith('%PDF-')) throw new Error('Choose a text export, not a binary or PDF file.');
    let digest = 'unavailable';
    if (globalThis.crypto?.subtle) {
      const hash = await crypto.subtle.digest('SHA-256', buffer);
      digest = Array.from(new Uint8Array(hash), (byte) => byte.toString(16).padStart(2, '0')).join('');
    }
    if (token !== workshop.manualLoad) return;
    workshop.manual = { name: file.name, text, digest };
    byId('manualTextStatus').textContent = `${file.name} · SHA-256 ${digest} · loaded in this tab only`;
    byId('manualTextSearch').disabled = false;
  } catch (error) { if (token === workshop.manualLoad) byId('manualTextStatus').textContent = `Could not load manual: ${error.message}`; }
};
byId('manualTextQuery').addEventListener('input', () => { byId('manualTextOut').textContent = ''; });
byId('manualTextSearch').onclick = () => {
  const out = byId('manualTextOut');
  try {
    if (!workshop.manual) throw new Error('Load a text export first.');
    const result = searchManualText(workshop.manual, byId('manualTextQuery').value);
    const source = `${workshop.manual.name} · SHA-256 ${workshop.manual.digest}`;
    out.innerHTML = `<div class="gate-card warn"><h4>${result.matches.length} literal match(es)${result.truncated ? ' (first 100 only)' : ''}</h4><p class="small">${esc(source)}. ${result.segments > 1 ? 'Form-feed text segments are not verified PDF page numbers.' : 'No page boundaries found.'} Verify the original manual and fitment.</p>${result.matches.map((item) => `<div class="manual-excerpt"><b>${result.segments > 1 ? `Text segment ${item.segment}` : 'Page unknown'}</b><pre>${esc(item.excerpt)}</pre></div>`).join('')}</div>`;
  } catch (error) { out.innerHTML = `<div class="gate-card bad"><h4>Search unavailable</h4><p>${esc(error.message)}</p></div>`; }
};
