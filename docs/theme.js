/* Light / dark / auto, applied before the page paints so it never flashes. Auto follows the device. */
(function () {
  'use strict';
  var KEY = 'mrdm.theme';
  function get() { try { var v = localStorage.getItem(KEY); return v === 'light' || v === 'dark' ? v : 'auto'; } catch (e) { return 'auto'; } }
  function apply(v) { var r = document.documentElement; if (v === 'light' || v === 'dark') r.setAttribute('data-theme', v); else r.removeAttribute('data-theme'); }
  function set(v) { try { if (v === 'auto') localStorage.removeItem(KEY); else localStorage.setItem(KEY, v); } catch (e) { /* storage blocked: the choice lasts until reload */ } apply(v); }
  window.MRTheme = { get: get, set: set, next: function () { // Auto, the opposite of the device, the device, Auto (the original's order)
    var dark = window.matchMedia && matchMedia('(prefers-color-scheme: dark)').matches, order = dark ? ['auto', 'light', 'dark'] : ['auto', 'dark', 'light'];
    var n = order[(order.indexOf(get()) + 1) % 3]; set(n); return n; } };
  apply(get());
})();
