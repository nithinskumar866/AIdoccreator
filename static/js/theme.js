// Runs before the page paints, so a saved theme never flashes the wrong colours.
(function () {
  var saved = null;
  try { saved = localStorage.getItem("documentor-theme"); } catch (e) { /* private mode */ }
  if (saved === "light" || saved === "dark") document.documentElement.dataset.theme = saved;
})();
