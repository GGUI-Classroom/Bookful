(function () {
  function debounce(fn, wait) {
    let timer;
    return function debounced(...args) {
      clearTimeout(timer);
      timer = setTimeout(() => fn.apply(this, args), wait);
    };
  }

  function clearSuggestions(container) {
    container.innerHTML = "";
    container.classList.add("d-none");
  }

  function renderSuggestions(container, items, onSelect) {
    if (!items.length) {
      clearSuggestions(container);
      return;
    }

    container.innerHTML = "";
    items.forEach((item) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "list-group-item list-group-item-action";
      button.textContent = item.author
        ? `${item.title} - ${item.author}`
        : item.title;
      button.addEventListener("click", function () {
        onSelect(item);
        clearSuggestions(container);
      });
      container.appendChild(button);
    });

    container.classList.remove("d-none");
  }

  window.initBookLookup = function initBookLookup(config) {
    const titleInput = document.querySelector(config.titleSelector);
    const authorInput = document.querySelector(config.authorSelector);
    const isbnInput = document.querySelector(config.isbnSelector);
    const coverImg = document.querySelector(config.coverImgSelector);
    const coverWrap = document.querySelector(config.coverWrapSelector);
    const suggestions = document.querySelector(config.suggestionsSelector);

    if (!titleInput || !authorInput || !isbnInput || !coverImg || !coverWrap || !suggestions) {
      return;
    }

    const fetchSuggestions = debounce(async function () {
      const query = titleInput.value.trim();
      if (query.length < 2) {
        clearSuggestions(suggestions);
        return;
      }

      try {
        const response = await fetch(`${config.endpoint}?q=${encodeURIComponent(query)}`, {
          headers: { Accept: "application/json" },
        });
        if (!response.ok) {
          clearSuggestions(suggestions);
          return;
        }

        const items = await response.json();
        renderSuggestions(suggestions, items, function (item) {
          titleInput.value = item.title || "";
          authorInput.value = item.author || "";
          isbnInput.value = item.isbn || "";

          if (item.cover_url) {
            coverImg.src = item.cover_url;
            coverWrap.classList.remove("d-none");
          } else {
            coverImg.removeAttribute("src");
            coverWrap.classList.add("d-none");
          }
        });
      } catch (_error) {
        clearSuggestions(suggestions);
      }
    }, 250);

    titleInput.addEventListener("input", fetchSuggestions);

    document.addEventListener("click", function (event) {
      if (!suggestions.contains(event.target) && event.target !== titleInput) {
        clearSuggestions(suggestions);
      }
    });
  };
})();
