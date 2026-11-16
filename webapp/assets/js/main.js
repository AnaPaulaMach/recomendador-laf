import "htmx.org";
import "../css/app.css";

const synchronizeRangeOutputs = (root = document) => {
  root.querySelectorAll("[data-preference-slider]").forEach((input) => {
    const output = root.querySelector(`[data-output-for="${CSS.escape(input.id)}"]`);
    const update = () => {
      if (output) output.textContent = Number(input.value || 0).toFixed(1);
    };
    input.addEventListener("input", update);
    update();
  });
  root.querySelectorAll("[data-filter-output]").forEach((output) => {
    const input = root.getElementById(output.dataset.filterOutput);
    const update = () => {
      output.textContent = Number(input?.value || 0).toFixed(2).replace(".", ",");
    };
    input?.addEventListener("input", update);
    update();
  });
};

const initializeDomainSelector = () => {
  const selector = document.getElementById("id_domain");
  if (!selector) return;
  selector.addEventListener("change", () => {
    const target = new URL(window.location.href);
    target.searchParams.set("domain", selector.value);
    window.location.assign(target);
  });
};

const initializeCategoryPicker = (root = document) => {
  root.querySelectorAll("[data-category-picker]:not([data-picker-ready])").forEach((picker) => {
    picker.dataset.pickerReady = "true";

    const input = picker.querySelector('[role="combobox"]');
    const listbox = picker.querySelector('[role="listbox"]');
    const options = Array.from(picker.querySelectorAll("[data-category-option]"));
    const noResults = picker.querySelector("[data-category-no-results]");
    let activeIndex = -1;

    if (!input || !listbox) return;

    const normalize = (value) =>
      value
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "")
        .toLocaleLowerCase("es")
        .trim();

    const visibleOptions = () => options.filter((option) => !option.hidden);

    const clearActiveOption = () => {
      options.forEach((option) => {
        option.removeAttribute("data-active");
        option.setAttribute("aria-selected", "false");
      });
      input.removeAttribute("aria-activedescendant");
      activeIndex = -1;
    };

    const activateOption = (index) => {
      const visible = visibleOptions();
      if (!visible.length) return;

      const nextIndex = (index + visible.length) % visible.length;
      clearActiveOption();
      activeIndex = nextIndex;
      const option = visible[nextIndex];
      option.dataset.active = "true";
      option.setAttribute("aria-selected", "true");
      input.setAttribute("aria-activedescendant", option.id);
      option.scrollIntoView({ block: "nearest" });
    };

    const openList = () => {
      listbox.hidden = false;
      input.setAttribute("aria-expanded", "true");
    };

    const closeList = () => {
      listbox.hidden = true;
      input.setAttribute("aria-expanded", "false");
      clearActiveOption();
    };

    const filterOptions = () => {
      const query = normalize(input.value);
      options.forEach((option) => {
        option.hidden = !normalize(option.dataset.search || option.textContent).includes(query);
      });
      if (noResults) noResults.hidden = visibleOptions().length > 0;
      clearActiveOption();
    };

    input.addEventListener("focus", () => {
      filterOptions();
      openList();
    });

    input.addEventListener("input", () => {
      filterOptions();
      openList();
    });

    input.addEventListener("keydown", (event) => {
      const visible = visibleOptions();

      if (event.key === "ArrowDown") {
        event.preventDefault();
        openList();
        activateOption(activeIndex + 1);
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        openList();
        activateOption(activeIndex <= 0 ? visible.length - 1 : activeIndex - 1);
      } else if (event.key === "Enter" && visible.length) {
        event.preventDefault();
        const selected = activeIndex >= 0 ? visible[activeIndex] : visible.length === 1 ? visible[0] : null;
        selected?.click();
      } else if (event.key === "Escape") {
        event.preventDefault();
        closeList();
      }
    });

    document.addEventListener("pointerdown", (event) => {
      if (!picker.contains(event.target)) closeList();
    });
  });
};

const initializeProductImages = (root = document) => {
  root.querySelectorAll("[data-product-image]:not([data-image-ready])").forEach((container) => {
    container.dataset.imageReady = "true";
    const image = container.querySelector("[data-product-image-source]");
    const fallback = container.querySelector("[data-product-image-fallback]");
    if (!image || !fallback) return;

    const showFallback = () => {
      image.hidden = true;
      fallback.hidden = false;
    };
    image.addEventListener("error", showFallback, { once: true });
    if (image.complete && image.naturalWidth === 0) showFallback();
  });
};

document.addEventListener("DOMContentLoaded", () => {
  synchronizeRangeOutputs();
  initializeDomainSelector();
  initializeCategoryPicker();
  initializeProductImages();
  if (document.querySelector("#argument-graph, [data-graph-mode], [data-aspect-panel]")) {
    import("./graph.js").then(
      ({ initializeArgumentGraph, initializeExplanationModes, initializeAspectAccordion }) => {
        initializeArgumentGraph();
        initializeExplanationModes();
        initializeAspectAccordion();
      },
    );
  }
});

document.addEventListener("htmx:afterSwap", (event) => {
  synchronizeRangeOutputs(event.detail.target);
  initializeCategoryPicker(event.detail.target);
  initializeProductImages(event.detail.target);
});
