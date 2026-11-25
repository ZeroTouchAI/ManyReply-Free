/* ManyReply DM home page: plays the chat. */
(function () {
  'use strict';

  var steps = document.querySelectorAll('.phone .step');
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (reduce) return; // the finished chat is already showing
  document.documentElement.classList.add('anim');
  steps.forEach(function (s, i) { setTimeout(function () { s.classList.add('in'); }, 600 + i * 750); });
})();
