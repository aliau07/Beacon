// Re-fetch the status summary every `data-refresh-seconds` (30) and redraw it, so the page stays current
// without a reload. Everything is written with textContent, never innerHTML.
(function () {
  const root = document.querySelector('[data-status-url]');
  if (!root) return;
  const url = root.dataset.statusUrl;
  const seconds = parseInt(root.dataset.refreshSeconds, 10) || 30;
  const overall = root.querySelector('[data-overall]');
  const list = root.querySelector('[data-components]');
  const updated = root.querySelector('[data-updated]');

  function badge(css, text) {
    const span = document.createElement('span');
    span.className = 'badge text-bg-' + css;
    span.textContent = text;
    return span;
  }

  function render(data) {
    overall.className = 'alert alert-' + data.css + ' fs-5 fw-semibold';
    overall.textContent = data.status_label;
    list.replaceChildren();
    for (const component of data.components) {
      const item = document.createElement('li');
      item.className = 'list-group-item d-flex justify-content-between align-items-start gap-2';
      const text = document.createElement('div');
      const name = document.createElement('div');
      name.className = 'fw-semibold';
      name.textContent = component.name;
      text.appendChild(name);
      for (const extra of [component.description, component.message]) {
        if (extra) {
          const line = document.createElement('div');
          line.className = 'small text-muted';
          line.textContent = extra;
          text.appendChild(line);
        }
      }
      item.appendChild(text);
      item.appendChild(badge(component.css, component.status_label));
      list.appendChild(item);
    }
    updated.textContent = new Date(data.updated_at).toLocaleString();
  }

  async function refresh() {
    try {
      const response = await fetch(url, {headers: {Accept: 'application/json'}, cache: 'no-store'});
      if (response.ok) render(await response.json());
    } catch (error) {
      // Offline or a blip: keep showing the last status we had.
    }
  }

  setInterval(refresh, seconds * 1000);
})();
