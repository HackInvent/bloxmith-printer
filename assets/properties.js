/** Explicit device discovery never starts an acquisition or changes the saved draft. */
export function mount(root, api) {
  const controller = new AbortController();
  const { signal } = controller;
  const button = root.querySelector('[data-device-refresh]');
  const select = root.querySelector('[data-device-select]');
  const status = root.querySelector('[data-device-status]');
  const t = (key, fallback) => api.t?.('block.printer.' + key, {}, fallback) || fallback;
  const readOnly = typeof api.isReadOnly === 'function' ? api.isReadOnly() : Boolean(api.isReadOnly);
  if (button) button.disabled = readOnly;
  button?.addEventListener('click', async () => {
    if (readOnly || signal.aborted) return;
    button.disabled = true;
    status.textContent = t('device_loading', 'Looking for installed equipment…');
    status.dataset.error = 'false';
    try {
      const response = await api.blockRequest('devices', { method: 'POST', payload: { values: {} } });
      if (signal.aborted) return;
      if (response.error) throw new Error(response.error);
      const current = select.value;
      const first = select.options[0].cloneNode(true);
      const options = [first];
      const seen = new Set(['']);
      if (current) { options.push(new Option(current, current)); seen.add(current); }
      for (const device of response.devices || []) {
        if (!device.id || seen.has(device.id)) continue;
        options.push(new Option(device.label || device.id, device.id));
        seen.add(device.id);
      }
      select.replaceChildren(...options);
      select.value = current;
      status.textContent = response.devices?.length ? t('device_found', 'Equipment list updated. Select a device, then Apply.') : t('device_empty', 'No equipment found.');
    } catch (error) {
      if (signal.aborted) return;
      status.dataset.error = 'true';
      status.textContent = t('device_error', 'Unable to list equipment.') + ' ' + (error?.message || '');
    } finally {
      if (!signal.aborted) button.disabled = readOnly;
    }
  }, { signal });
  return () => controller.abort();
}
