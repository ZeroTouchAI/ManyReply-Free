/* ManyReply DM home page: plays the chat, and wires the sign-up link from config.js. */
(function () {
  'use strict';
  var cfg = window.MANYREPLY_CONFIG || {};
  var url = cfg.zernioSignupUrl || '';
  document.querySelectorAll('[data-zernio]').forEach(function (a) { if (url) a.setAttribute('href', url); });
  var note = document.getElementById('disclosure');
  if (note && url) note.hidden = false; // only say "referral" when there is a referral link

  var steps = document.querySelectorAll('.phone .step');
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (reduce) return; // the finished chat is already showing
  document.documentElement.classList.add('anim');
  steps.forEach(function (s, i) { setTimeout(function () { s.classList.add('in'); }, 600 + i * 750); });
})();
