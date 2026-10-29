/* GuzziOnBoard desktop host bridge.
 *
 * Loaded only when the page is being served by the desktop app (the server
 * injects the tag, and the host prefixes this file with
 * `window.__GOB_DESKTOP__`). In a browser tab none of this exists, and the UI
 * falls back to ordinary browser behaviour - which is the point: the UI is the
 * same file in both places.
 *
 * Three jobs:
 *
 * 1. Session token. The API of a running workstation refuses /api/ calls that
 *    do not carry the token this launch generated, which is what stops any
 *    other page on the machine from driving a connected motorcycle. Every
 *    request from this window carries it; navigator.sendBeacon cannot set
 *    headers, so that one call carries it in the query string instead.
 * 2. Saved files. `a.download` on a blob URL is not dependable inside a
 *    webview (and pywebview blocks downloads unless told otherwise), so
 *    downloads are handed to the host, which writes them next to the user's
 *    other exports and never overwrites an existing file.
 * 3. Printing. Webviews do not implement window.print() usefully. "Print"
 *    here builds a standalone snapshot of the current view - styles inlined,
 *    canvases frozen - and asks the host to open it in a real browser, where
 *    Ctrl+P works.
 */
'use strict';

(function () {
  const host = window.__GOB_DESKTOP__;
  if (!host || !host.token) return;          // browser tab: nothing to do

  const token = host.token;
  const sameOrigin = (url) => {
    try {
      return new URL(url, window.location.href).origin === window.location.origin;
    } catch (_) {
      return false;
    }
  };

  /* ------------------------------------------------------------- requests */

  const realFetch = window.fetch.bind(window);
  window.fetch = function (input, init) {
    const target = typeof input === 'string' ? input : (input && input.url) || '';
    if (!sameOrigin(target)) return realFetch(input, init);
    const options = Object.assign({}, init || {});
    const headers = new Headers(options.headers || (input && input.headers) || undefined);
    headers.set('X-GuzziOnBoard-Token', token);
    options.headers = headers;
    return realFetch(input, options);
  };

  // fetch is what the UI uses, but a future caller (or a downloaded demo
  // script) reaching for XMLHttpRequest must not be left unauthenticated.
  if (typeof XMLHttpRequest === 'function') {
    const realOpen = XMLHttpRequest.prototype.open;
    const realSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function (method, url, ...rest) {
      this.__gobSameOrigin = sameOrigin(url);
      return realOpen.call(this, method, url, ...rest);
    };
    XMLHttpRequest.prototype.send = function (...args) {
      if (this.__gobSameOrigin) {
        try { this.setRequestHeader('X-GuzziOnBoard-Token', token); } catch (_) { /* already sent */ }
      }
      return realSend.apply(this, args);
    };
  }

  const realBeacon = navigator.sendBeacon && navigator.sendBeacon.bind(navigator);
  if (realBeacon) {
    navigator.sendBeacon = function (url, data) {
      if (!sameOrigin(url)) return realBeacon(url, data);
      const separator = String(url).includes('?') ? '&' : '?';
      const payload = typeof data === 'string'
        ? new Blob([data], { type: 'application/json' })
        : data;
      return realBeacon(`${url}${separator}token=${encodeURIComponent(token)}`, payload);
    };
  }

  const post = async (path, body) => {
    const response = await realFetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-GuzziOnBoard-Token': token },
      body: JSON.stringify(body || {}),
    });
    let payload = {};
    try { payload = await response.json(); } catch (_) { /* empty body */ }
    if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    return payload;
  };

  /* ------------------------------------------------------------ snapshots */

  async function printView() {
    const clone = document.documentElement.cloneNode(true);
    clone.querySelectorAll('script, noscript').forEach((node) => node.remove());

    // Inline the stylesheet so the file stands on its own once it is opened
    // from the exports folder, with the workstation long gone.
    try {
      const css = await realFetch('styles.css', {
        headers: { 'X-GuzziOnBoard-Token': token },
      }).then((response) => response.text());
      const head = clone.querySelector('head');
      clone.querySelectorAll('link[rel="stylesheet"]').forEach((link) => link.remove());
      if (head && css) {
        const style = document.createElement('style');
        style.textContent = css;
        head.appendChild(style);
      }
    } catch (_) { /* a plain snapshot is still printable */ }

    // A canvas is pixels, not markup: freeze each one into an image.
    const live = document.querySelectorAll('canvas');
    clone.querySelectorAll('canvas').forEach((canvas, index) => {
      const source = live[index];
      if (!source || !source.toDataURL) return;
      try {
        const image = document.createElement('img');
        image.src = source.toDataURL('image/png');
        image.width = source.width;
        image.height = source.height;
        image.style.maxWidth = '100%';
        canvas.replaceWith(image);
      } catch (_) { /* tainted or detached canvas: leave the element */ }
    });

    clone.setAttribute('data-print-snapshot', new Date().toISOString());
    return '<!doctype html>\n' + clone.outerHTML;
  }

  /* --------------------------------------------------------------- bridge */

  window.gobDesktop = {
    available: true,
    version: host.version,
    backend: host.backend,
    renderer: host.renderer,
    exports: host.exports,
    port: host.port,
    info: () => realFetch('/api/desktop', {
      headers: { 'X-GuzziOnBoard-Token': token },
    }).then((response) => response.json()),
    saveText: (name, text) => post('/api/desktop/save', { name, content: String(text) }),
    saveBinary: (name, base64) => post('/api/desktop/save-binary', { name, content_base64: base64 }),
    printView: async () => post('/api/desktop/print', { html: await printView() }),
    openExternal: (url) => post('/api/desktop/open-external', { url }),
    openFolder: (which) => post('/api/desktop/open-folder', { which: which || 'exports' }),
    quit: () => post('/api/desktop/quit', {}),
  };

  // Links the UI opens for the user belong in their browser, not in a window
  // with no address bar and no way back.
  const realOpen = window.open;
  window.open = function (url, ...rest) {
    if (url && sameOrigin(url)) return realOpen.call(window, url, ...rest);
    if (url) {
      window.gobDesktop.openExternal(String(url)).catch(() => realOpen.call(window, url, ...rest));
      return null;
    }
    return realOpen.call(window, url, ...rest);
  };

  // The host speaks to the window when it refuses to close mid-job, or when
  // it wants to say something the UI should show.
  window.addEventListener('gob-notice', (event) => {
    const message = (event && event.detail) || 'notice from the desktop app';
    if (typeof window.toast === 'function') window.toast(message, 'warn');
  });

  document.addEventListener('DOMContentLoaded', () => {
    document.body.setAttribute('data-desktop', '1');
  });
}());
