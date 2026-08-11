(function () {
  if (typeof mermaid === "undefined") return;

  mermaid.initialize({ startOnLoad: false });

  var renderMermaid = function () {
    mermaid.run({ querySelector: ".mermaid" });
  };

  if (typeof document$ !== "undefined") {
    document$.subscribe(renderMermaid);
  } else {
    document.addEventListener("DOMContentLoaded", renderMermaid);
  }
})();
