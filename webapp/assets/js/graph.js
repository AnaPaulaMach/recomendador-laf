import cytoscape from "cytoscape";
import dagre from "cytoscape-dagre";

cytoscape.use(dagre);

const text = (...values) => {
  for (const value of values) {
    if (value === null || value === undefined) continue;
    const normalized = String(value).trim();
    if (normalized) return normalized;
  }
  return "Sin etiqueta";
};

const number = (value) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.max(0, Math.min(parsed, 1)) : 0;
};

const escapeText = (value) => text(value).replaceAll("<", "‹").replaceAll(">", "›");
const nodeTypeLabel = (value) =>
  ({
    fact: "Hecho",
    aspect: "Aspecto",
    dimension: "Dimensión",
    rule: "Regla",
    operator: "Operador LAF",
    conclusion: "Conclusión",
    unknown: "Sin tipo",
  })[text(value, "unknown")] || text(value);
const statusLabel = (value) =>
  ({
    accepted: "Aceptado",
    weakened: "Debilitado",
    rejected: "Rechazado",
    undetermined: "Indeterminado",
  })[text(value, "undetermined")] || text(value);

const compactNumber = (value) =>
  number(value).toFixed(2).replace(".", ",");

const compactLiteral = (value) =>
  text(value).replace(
    /([a-z_~][a-z0-9_~]*)\(([a-z]{3,4}\d+)[^)]*\)/gi,
    (_match, predicate, entityId) => `${predicate}(${entityId.toUpperCase()})`,
  );

const lafNodeLabel = (node) => {
  if (text(node?.node_type) === "operator") return text(node?.label, node?.literal);
  const title = text(node?.metadata?.graph_label, node?.metadata?.display_name, compactLiteral(node?.literal), node?.label);
  if (node?.metadata?.view_kind === "summary") {
    if (text(node?.node_type) === "conclusion") {
      return `${title}\nResultado ${compactNumber(node?.weakened_value)}`;
    }
    const evidenceCount = Math.max(Number.parseInt(node?.evidence_count ?? 0, 10) || 0, 0);
    const evidenceLabel = `${evidenceCount} ${evidenceCount === 1 ? "opinión" : "opiniones"}`;
    return `${title}\nInfluencia ${compactNumber(Math.min(number(node?.confidence), number(node?.preference)))} · ${evidenceLabel}`;
  }
  if (node?.metadata?.hide_preference) {
    // Grafo por aspecto: sin preferencia (es 1,00 constante). Además separamos
    // la parte numérica del texto con una línea, y las reglas no llevan números.
    const kind = text(node?.node_type);
    const separator = "─".repeat(14);
    if (kind === "rule") {
      return `${title}\n${separator}\nConfianza ${compactNumber(node?.confidence)}`;
    }
    if (kind === "conclusion") {
      return `${title}\n${separator}\nResultado ${compactNumber(node?.weakened_value)}`;
    }
    const acc = compactNumber(node?.accumulated_value);
    const fin = compactNumber(node?.weakened_value);
    const numbers = acc === fin ? `Respaldo ${fin}` : `Antes ${acc} → después ${fin}`;
    return `${title}\n${separator}\n${numbers}`;
  }
  return [
    title,
    `Conf. ${compactNumber(node?.confidence)} · Pref. ${compactNumber(node?.preference)}`,
    `Acum. ${compactNumber(node?.accumulated_value)} · Final ${compactNumber(node?.weakened_value)}`,
  ].join("\n");
};

const asElements = (payload) => {
  const nodes = Array.isArray(payload?.nodes) ? payload.nodes : [];
  const edges = Array.isArray(payload?.edges) ? payload.edges : [];
  return [
    ...nodes.map((node) => ({
      group: "nodes",
      data: {
        id: text(node?.id, "nodo-sin-id"),
        label: lafNodeLabel(node),
        display_name: text(node?.metadata?.display_name, node?.label, node?.literal, node?.id),
        node_type: text(node?.node_type, "unknown"),
        literal: text(node?.literal, node?.id),
        polarity: text(node?.polarity, "neutral"),
        confidence: number(node?.confidence),
        preference: number(node?.preference),
        accumulated_value: number(node?.accumulated_value),
        weakened_value: number(node?.weakened_value),
        acceptability_status: text(node?.acceptability_status, "undetermined"),
        evidence_count: Math.max(Number.parseInt(node?.evidence_count ?? 0, 10) || 0, 0),
        product: text(node?.metadata?.product, ""),
        dimension: text(node?.metadata?.dimension, ""),
        aspect: text(node?.metadata?.aspect, ""),
        source_name: text(node?.metadata?.source, ""),
        operator: text(node?.metadata?.operator, ""),
        plain_summary: String(node?.metadata?.plain_summary || "").trim(),
        is_root: Boolean(node?.metadata?.is_root),
      },
    })),
    ...edges.map((edge) => ({
      group: "edges",
      data: {
        id: text(edge?.id, `${text(edge?.source)}-${text(edge?.target)}`),
        source: text(edge?.source, "origen-sin-id"),
        target: text(edge?.target, "destino-sin-id"),
        edge_type: text(edge?.edge_type, "support"),
        label: text(edge?.label, edge?.edge_type, "relación"),
        rule_id: text(edge?.rule_id, "regla-sin-id"),
      },
    })),
  ];
};

const graphStyle = [
  {
    selector: "node",
    style: {
      label: "data(label)",
      "font-family": "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
      "font-size": 14,
      "font-weight": 500,
      "text-wrap": "wrap",
      "text-max-width": 218,
      "text-valign": "center",
      "text-halign": "center",
      color: "#0f172a",
      width: 238,
      height: 104,
      "background-color": "#fffefb",
      "border-width": 1.4,
      "border-color": "#334155",
    },
  },
  {
    selector: 'node[node_type = "fact"]',
    style: { shape: "rectangle", "background-color": "#fffefb", "border-style": "solid" },
  },
  {
    selector: 'node[node_type = "aspect"]',
    style: { shape: "rectangle", "background-color": "#f0fdfa", "border-color": "#0f766e" },
  },
  {
    selector: 'node[node_type = "dimension"]',
    style: { shape: "rectangle", "background-color": "#fffbeb", "border-color": "#b45309" },
  },
  {
    selector: 'node[node_type = "rule"]',
    style: { shape: "rectangle", width: 270, height: 112, "background-color": "#f8fafc", "border-color": "#64748b", "border-style": "dashed" },
  },
  {
    selector: 'node[node_type = "operator"]',
    style: {
      shape: "ellipse",
      width: 66,
      height: 42,
      "font-family": "Georgia, serif",
      "font-size": 15,
      "font-style": "italic",
      "font-weight": 600,
      "background-color": "#fffefb",
      "border-color": "#334155",
    },
  },
  {
    selector: 'node[operator = "CA"]',
    style: { shape: "diamond", width: 58, height: 58, "font-style": "normal", "border-color": "#be123c" },
  },
  {
    selector: 'node[operator = "AGG"]',
    style: { shape: "diamond", width: 58, height: 58, "font-size": 21, "font-style": "normal", "border-color": "#0f766e" },
  },
  {
    selector: 'node[node_type = "conclusion"]',
    style: { shape: "rectangle", width: 258, height: 112, "background-color": "#ecfdf5", "border-color": "#0f766e", "border-width": 3, "font-weight": 700 },
  },
  {
    selector: 'node[polarity = "negative"]',
    style: { "background-color": "#ffe4e6", "border-color": "#be123c" },
  },
  {
    selector: 'node[acceptability_status = "weakened"]',
    style: { "border-style": "dashed", opacity: 0.78 },
  },
  {
    selector: 'node[acceptability_status = "rejected"], node[acceptability_status = "undetermined"]',
    style: { "border-style": "dotted", opacity: 0.62 },
  },
  {
    selector: "node:selected",
    style: { "overlay-color": "#0f766e", "overlay-opacity": 0.16, "overlay-padding": 7, "border-width": 4 },
  },
  {
    selector: "edge",
    style: {
      width: 2,
      "curve-style": "bezier",
      "target-arrow-shape": "triangle",
      "line-color": "#0f766e",
      "target-arrow-color": "#0f766e",
      label: "",
    },
  },
  {
    selector: 'edge[edge_type = "conflict"]',
    style: {
      "line-color": "#be123c",
      "target-arrow-color": "#be123c",
      "line-style": "dashed",
      "target-arrow-shape": "tee",
    },
  },
];

const buildInspector = (node, target) => {
  target.replaceChildren();
  const data = node.data();
  const badge = document.createElement("span");
  badge.className = `node-type-tag node-type-${escapeText(data.node_type)}`;
  badge.textContent = nodeTypeLabel(data.node_type);
  const heading = document.createElement("h3");
  heading.className = "mt-3 font-serif text-xl font-semibold";
  heading.textContent = text(data.display_name, data.literal, data.id);
  const explanation = document.createElement("p");
  explanation.className = "mt-3 text-sm leading-6 text-slate-600";
  if (data.node_type === "conclusion") {
    explanation.textContent = "Esta es la recomendación final obtenida después de combinar todos los argumentos visibles.";
  } else if (data.operator === "dMP") {
    explanation.textContent = "Este operador aplica una regla a una evidencia para producir un nuevo argumento.";
  } else if (data.operator === "AGG") {
    explanation.textContent = "Este operador combina los argumentos que apoyan la misma recomendación.";
  } else if (data.operator === "CA") {
    explanation.textContent = "Este operador considera conjuntamente los argumentos a favor y en contra.";
  } else if (data.operator === "SUMMARY") {
    explanation.textContent = "En este paso LAF combina los argumentos, los posibles conflictos y tus preferencias.";
  } else if (data.plain_summary) {
    explanation.textContent = data.plain_summary;
  } else if (data.node_type === "rule") {
    explanation.textContent = "Esta regla conecta evidencias previas con una conclusión derivada.";
  } else if (data.polarity === "negative") {
    explanation.textContent = "Este elemento contradice o reduce la fuerza de la recomendación.";
  } else {
    explanation.textContent = "Este elemento aporta evidencia a favor de la recomendación.";
  }

  const details = document.createElement("details");
  details.className = "graph-technical-details mt-4";
  const summary = document.createElement("summary");
  summary.textContent = "Ver datos técnicos";
  const literal = document.createElement("code");
  literal.className = "mt-3 block break-words rounded-lg bg-slate-100 p-3 text-xs";
  literal.textContent = text(data.literal, data.id);
  const list = document.createElement("dl");
  list.className = "inspector-list mt-4";
  const values = data.node_type === "operator"
    ? []
    : [
        ["Estado en LAF", statusLabel(data.acceptability_status)],
        ["Confianza", compactNumber(data.confidence)],
        ["Preferencia del usuario", compactNumber(data.preference)],
        ["Valor acumulado", compactNumber(data.accumulated_value)],
        ["Valor tras conflictos", compactNumber(data.weakened_value)],
      ];
  if (data.evidence_count > 0) values.push(["Opiniones asociadas", String(data.evidence_count)]);
  values.forEach(([label, value]) => {
    const row = document.createElement("div");
    const term = document.createElement("dt");
    const description = document.createElement("dd");
    term.textContent = label;
    description.textContent = text(value, "0");
    row.append(term, description);
    list.append(row);
  });
  details.append(summary, literal);
  if (values.length) details.append(list);
  target.append(badge, heading, explanation, details);
};

const updateBreadcrumb = (cy, rootId, node, target) => {
  target.replaceChildren();
  let path = [];
  try {
    const result = cy.elements().aStar({
      root: `#${CSS.escape(rootId)}`,
      goal: node,
      directed: false,
    });
    path = result.found ? result.path.nodes().toArray() : [node];
  } catch {
    path = [node];
  }
  path.forEach((item, index) => {
    const li = document.createElement("li");
    li.textContent = text(item.data("display_name"), item.data("literal"), item.id());
    target.append(li);
    if (index < path.length - 1) {
      const separator = document.createElement("li");
      separator.textContent = "›";
      separator.setAttribute("aria-hidden", "true");
      target.append(separator);
    }
  });
};

export const initializeArgumentGraph = () => {
  const container = document.getElementById("argument-graph");
  if (!container) return;

  const filters = document.querySelector("[data-graph-filters]");
  const loading = document.querySelector("[data-graph-loading]");
  const counter = document.querySelector("[data-graph-count]");
  const inspector = document.querySelector("[data-node-inspector]");
  const breadcrumb = document.querySelector("[data-graph-breadcrumb]");
  const depthInput = document.querySelector("[data-graph-depth]");
  const groupInput = document.querySelector("[data-graph-group]");
  const summaryFigure = document.querySelector("[data-summary-figure]");
  const technicalGraph = document.querySelector("[data-technical-graph]");
  const technicalPanel = document.querySelector("[data-technical-panel]");
  const pngButton = document.querySelector("[data-export-png]");
  const rankingFigure = document.querySelector("[data-ranking-figure]");
  let rootId = text(container.dataset.graphRoot, "conclusion:recomendar");
  let activeMode = text(container.dataset.graphMode, "summary");
  let technicalLoaded = false;
  let activeLayout = null;
  let activeController = null;

  const cy = cytoscape({
    container,
    elements: [],
    style: graphStyle,
    minZoom: 0.5,
    maxZoom: 4,
    boxSelectionEnabled: true,
  });

  const runLayout = (preserveViewport = false) => {
    if (activeLayout) activeLayout.stop();
    const zoom = cy.zoom();
    const pan = cy.pan();
    const selected = cy.$(":selected").map((item) => item.id());
    const groupBy = groupInput?.value || "hierarchy";
    const options =
      groupBy === "hierarchy"
        ? { name: "breadthfirst", directed: true, spacingFactor: 1.15, padding: 54, animate: false }
        : {
            name: "grid",
            padding: 32,
            avoidOverlap: true,
            condense: false,
            sort: (a, b) =>
              text(a.data(groupBy), a.data("node_type")).localeCompare(
                text(b.data(groupBy), b.data("node_type")),
                "es",
              ),
          };
    activeLayout = cy.layout(options);
    activeLayout.run();
    if (preserveViewport) {
      cy.zoom(zoom);
      cy.pan(pan);
      selected.forEach((id) => cy.getElementById(id).select());
    } else {
      cy.fit(undefined, 36);
      const readableZoom = container.clientWidth < 800 ? 0.7 : 0.9;
      if (activeMode === "summary" && cy.zoom() < readableZoom) {
        cy.zoom(readableZoom);
        cy.center();
      }
    }
  };

  const parameters = (overrideRoot, overrideDepth) => {
    const params = new URLSearchParams(filters ? new FormData(filters) : undefined);
    if (container.dataset.graphEntity) params.set("entity_id", container.dataset.graphEntity);
    if (overrideRoot) params.set("root_id", overrideRoot);
    params.set("mode", activeMode);
    params.set("depth", overrideDepth || (activeMode === "summary" ? "2" : "3"));
    params.set("limit", container.dataset.graphLimit || "250");
    return params;
  };

  const load = async ({ merge = false, focus = "", depth } = {}) => {
    activeController?.abort();
    activeController = new AbortController();
    loading.hidden = false;
    container.setAttribute("aria-busy", "true");
    try {
      const response = await fetch(`${container.dataset.graphUrl}?${parameters(focus, depth)}`, {
        headers: { Accept: "application/json" },
        signal: activeController.signal,
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      rootId = text(payload?.root_id, rootId);
      const elements = asElements(payload);
      if (!merge) cy.elements().remove();
      const existing = new Set(cy.elements().map((item) => item.id()));
      cy.add(elements.filter((item) => !existing.has(item.data.id)));
      if (counter) {
        const total = Number(payload?.total_nodes || cy.nodes().length).toLocaleString("es-AR");
        counter.textContent = `${cy.nodes().length} nodos cercanos`;
        counter.title = `El grafo completo contiene ${total} nodos; esta vista muestra sólo la vecindad de la conclusión`;
      }
      runLayout(merge);
      const focused = cy.getElementById(focus || rootId);
      if (focused.nonempty()) {
        focused.select();
      }
    } catch (error) {
      if (error.name !== "AbortError" && counter) {
        counter.textContent = "No se pudo cargar el fragmento";
      }
    } finally {
      loading.hidden = true;
      container.removeAttribute("aria-busy");
    }
  };

  let filterTimer;
  filters?.addEventListener("input", () => {
    window.clearTimeout(filterTimer);
    filterTimer = window.setTimeout(() => load({ merge: false }), 280);
  });
  filters?.addEventListener("reset", () => window.setTimeout(() => load({ merge: false }), 0));
  depthInput?.addEventListener("change", () => load({ merge: false }));
  groupInput?.addEventListener("change", () => runLayout(true));

  const showMode = (mode) => {
    activeMode = mode;
    container.dataset.graphMode = activeMode;
    if (summaryFigure) summaryFigure.hidden = activeMode !== "summary";
    if (rankingFigure) rankingFigure.hidden = activeMode !== "ranking";
    if (technicalGraph) technicalGraph.hidden = activeMode !== "technical";
    if (technicalPanel) technicalPanel.hidden = activeMode !== "technical";
    if (pngButton) pngButton.hidden = activeMode !== "technical";
    document.querySelectorAll("button[data-graph-mode]").forEach((item) => {
      item.setAttribute("aria-pressed", String(item.dataset.graphMode === activeMode));
    });
    const description = document.querySelector("[data-graph-mode-description]");
    if (description) {
      const descriptionKey = `${activeMode}Description`;
      description.textContent = description.dataset[descriptionKey] || description.textContent;
    }
    if (activeMode === "technical") {
      window.requestAnimationFrame(() => {
        if (technicalLoaded) runLayout(false);
        else {
          technicalLoaded = true;
          load({ merge: false });
        }
      });
    }
  };

  document.querySelectorAll("[data-graph-mode]").forEach((button) => {
    if (button === container) return;
    button.addEventListener("click", () => {
      showMode(text(button.dataset.graphMode, "summary"));
    });
  });

  cy.on("select", "node", (event) => {
    if (inspector) buildInspector(event.target, inspector);
    if (breadcrumb) updateBreadcrumb(cy, rootId, event.target, breadcrumb);
  });
  cy.on("dbltap", "node", (event) => {
    if (activeMode === "technical") load({ merge: true, focus: event.target.id(), depth: 1 });
  });

  document.querySelector("[data-graph-center]")?.addEventListener("click", () => {
    const root = cy.getElementById(rootId);
    if (root.nonempty()) {
      cy.animate({ center: { eles: root }, zoom: 1 }, { duration: 260 });
      root.select();
    }
  });
  document.querySelector("[data-graph-zoom-in]")?.addEventListener("click", () => {
    cy.animate({ zoom: Math.min(cy.zoom() * 1.25, cy.maxZoom()) }, { duration: 180 });
  });
  document.querySelector("[data-graph-zoom-out]")?.addEventListener("click", () => {
    cy.animate({ zoom: Math.max(cy.zoom() / 1.25, cy.minZoom()) }, { duration: 180 });
  });
  pngButton?.addEventListener("click", () => {
    const link = document.createElement("a");
    link.href = cy.png({ full: true, scale: 2, bg: "#ffffff" });
    link.download = "subgrafo-visible.png";
    link.click();
  });
  showMode(activeMode);
};

// Panel acordeón por característica: vista amable (cajas) + toggle "como en el
// Studio" que carga el subgrafo REAL de ese aspecto con el mismo renderizador.
// Conmutador «Resumen» / «Comparar con los demás». Vive aparte de
// initializeArgumentGraph porque esa función necesita el grafo técnico, que ya
// no está en la página (2026-09-10).
export const initializeExplanationModes = () => {
  const buttons = document.querySelectorAll("button[data-graph-mode]");
  if (!buttons.length) return;
  const summaryFigure = document.querySelector("[data-summary-figure]");
  const rankingFigure = document.querySelector("[data-ranking-figure]");
  const show = (mode) => {
    if (summaryFigure) summaryFigure.hidden = mode !== "summary";
    if (rankingFigure) rankingFigure.hidden = mode !== "ranking";
    buttons.forEach((button) => {
      button.setAttribute("aria-pressed", String(button.dataset.graphMode === mode));
    });
  };
  buttons.forEach((button) => {
    button.addEventListener("click", () => show(button.dataset.graphMode || "summary"));
  });
  show("summary");
};

export const initializeAspectAccordion = () => {
  const panel = document.querySelector("[data-aspect-panel]");
  const buttons = document.querySelectorAll(".claim-open");
  if (!panel || !buttons.length) return;

  const titleEl = panel.querySelector("[data-aspect-title]");
  const plainEl = panel.querySelector("[data-aspect-plain]");
  const studioWrap = panel.querySelector("[data-aspect-studio]");
  const graphContainer = panel.querySelector("[data-aspect-graph]");
  const loading = panel.querySelector("[data-aspect-loading]");
  const aspectUrl = panel.dataset.aspectGraphUrl;
  const entity = panel.dataset.graphEntity;
  let cy = null;
  let current = null;
  let loadedKey = "";

  // Sólo la oración del debate: el diagrama de cajas se retiró (2026-09-10).
  // El dibujo del razonamiento vive en "Ver como en el Studio", que es el grafo
  // real del aspecto, no una recreación.
  const renderPlain = (d) => {
    plainEl.replaceChildren();
    const p = document.createElement("p");
    p.className = "claim-narrative mg-caption";
    p.textContent = d.narr || "";
    plainEl.append(p);
  };

  // Menciones concretas del aspecto: ejemplos, no la lista completa. Vienen del
  // mismo endpoint que el grafo; si no hay base detrás, no se dibuja nada.
  const renderExamples = (items) => {
    const box = panel.querySelector("[data-aspect-examples]");
    if (!box) return;
    box.replaceChildren();
    box.hidden = !(items && items.length);
    if (box.hidden) return;
    const title = document.createElement("h4");
    title.textContent = "Menciones detectadas automáticamente en las reseñas";
    const rule = document.createElement("p");
    rule.className = "aspect-examples-rule";
    rule.textContent =
      "Ejemplos elegidos por peso de testimonio: hasta dos de cada polaridad, a favor y en contra.";
    const list = document.createElement("ul");
    items.forEach((item) => {
      const li = document.createElement("li");
      if (item.polarity === "neg") li.className = "is-negative";
      li.textContent = `“${item.excerpt}”`;
      const meta = document.createElement("small");
      const side = item.polarity === "neg" ? "en contra" : "a favor";
      meta.textContent = `${side} · peso de la reseña ${String(item.trust).replace(".", ",")}`;
      li.append(meta);
      list.append(li);
    });
    box.append(title, rule, list);
    if (box.dataset.qualityUrl) {
      const source = document.createElement("p");
      source.className = "aspect-examples-rule";
      const link = document.createElement("a");
      link.href = box.dataset.qualityUrl;
      link.textContent = "Cómo se mide la calidad de esta detección";
      source.append(link);
      box.append(source);
    }
  };

  // Encuadra el grafo, pero no por debajo de MIN_READABLE_ZOOM: con el ajuste
  // automático a secas la tipografía de 14 px caía a ~8 px y el dibujo era
  // ilegible sin acercar (2026-09-10). Si no entra, el panel se desplaza.
  const MIN_READABLE_ZOOM = 0.9;
  const fitReadable = (padding = 20) => {
    if (!cy) return;
    cy.fit(undefined, padding);
    if (cy.zoom() >= MIN_READABLE_ZOOM) return;
    // No entra legible: se muestra desde arriba, que es por donde se lee
    // (hecho + regla → … → resultado); el resto se alcanza arrastrando o con
    // «Ajustar», que sí muestra el grafo completo.
    cy.zoom(MIN_READABLE_ZOOM);
    const box = cy.elements().boundingBox();
    cy.pan({
      x: cy.width() / 2 - (box.x1 + box.w / 2) * MIN_READABLE_ZOOM,
      y: padding - box.y1 * MIN_READABLE_ZOOM,
    });
  };

  // U27: el mensaje no le hace al usuario una pregunta que no puede contestar
  // ("¿motor LAF disponible?") ni nombra un componente interno, y ofrece la
  // única acción que tiene sentido acá: volver a pedir la explicación.
  const showGraphError = (key) => {
    graphContainer.replaceChildren();
    const note = document.createElement("p");
    note.className = "graph-error";
    note.textContent = "No pudimos mostrar la explicación de este punto ahora.";
    const retry = document.createElement("button");
    retry.type = "button";
    retry.className = "button button-secondary button-sm mt-3";
    retry.textContent = "Volver a intentar";
    retry.addEventListener("click", () => {
      loadedKey = "";
      loadStudio(key);
    });
    graphContainer.append(note, retry);
  };

  const loadStudio = async (key) => {
    if (!aspectUrl || !key) {
      graphContainer.textContent = "Este punto no tiene un grafo asociado.";
      return;
    }
    if (loadedKey === key && cy) {
      cy.resize();
      fitReadable(26);
      return;
    }
    loading.hidden = false;
    try {
      const params = new URLSearchParams();
      if (entity) params.set("entity_id", entity);
      params.set("aspect", key);
      const res = await fetch(`${aspectUrl}?${params}`, { headers: { Accept: "application/json" } });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const payload = await res.json();
      renderExamples(payload.examples);
      if (!(payload.nodes && payload.nodes.length)) {
        showGraphError(key);
        loadedKey = "";
        return;
      }
      if (!cy) {
        cy = cytoscape({
          container: graphContainer,
          elements: [],
          style: graphStyle,
          minZoom: 0.2,
          maxZoom: 3,
          boxSelectionEnabled: false,
        });
      }
      cy.elements().remove();
      cy.add(asElements(payload));
      // dagre: jerárquico arriba→abajo, con alto (rankSep = largo de flecha) y
      // separación horizontal (nodeSep) controlados por separado.
      cy.layout({ name: "dagre", rankDir: "TB", rankSep: 40, nodeSep: 26, edgeSep: 8, padding: 22, animate: false }).run();
      fitReadable();
      loadedKey = key;
    } catch {
      showGraphError(key);
      loadedKey = "";
    } finally {
      loading.hidden = true;
    }
  };

  const showStudio = (on) => {
    studioWrap.hidden = !on;
    if (on && current) loadStudio(current.key);
  };

  buttons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const node = btn.dataset.aspectNode || "";
      const same = current && current.node === node && !panel.hidden;
      buttons.forEach((b) => b.setAttribute("aria-expanded", "false"));
      if (same) {
        panel.hidden = true;
        current = null;
        return;
      }
      btn.setAttribute("aria-expanded", "true");
      current = {
        node,
        key: btn.dataset.aspectKey || "",
        label: btn.dataset.aspectLabel || "Característica",
        favor: btn.dataset.aspectFavor || "0",
        against: btn.dataset.aspectAgainst || "0",
        narr: btn.dataset.aspectNarr || "",
      };
      panel.hidden = false;
      if (titleEl) titleEl.textContent = current.label;
      renderPlain(current);
      loadedKey = "";
      // El grafo real del aspecto es la explicación: se muestra siempre, sin
      // casilla previa (2026-09-10).
      showStudio(true);
      panel.scrollIntoView({ block: "nearest" });
    });
  });

  panel.querySelector("[data-aspect-zoom-in]")?.addEventListener("click", () => {
    if (cy) cy.animate({ zoom: Math.min(cy.zoom() * 1.25, cy.maxZoom()), center: { eles: cy.elements() } }, { duration: 150 });
  });
  panel.querySelector("[data-aspect-zoom-out]")?.addEventListener("click", () => {
    if (cy) cy.animate({ zoom: Math.max(cy.zoom() / 1.25, cy.minZoom()) }, { duration: 150 });
  });
  panel.querySelector("[data-aspect-fit]")?.addEventListener("click", () => {
    if (cy) cy.fit(undefined, 20);  // «Ajustar» muestra todo, aunque quede chico
  });
};
