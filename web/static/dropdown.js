// Adapt the fallback page's existing select data/events to the shared menu skin.
document.querySelectorAll('select').forEach(select => {
  const trigger = document.createElement('button');
  trigger.type = 'button';
  trigger.className = select.className;
  trigger.style.cssText = 'width:100%;text-align:left;cursor:pointer';
  trigger.setAttribute('aria-haspopup', 'listbox');
  trigger.setAttribute('aria-label', select.id === 'persona' ? 'Persona' : 'Select Skill');
  select.hidden = true;
  select.after(trigger);
  let menu;
  const sync = () => {
    trigger.textContent = `${select.selectedOptions[0]?.textContent || '-- Choose --'} ▾`;
    trigger.disabled = select.disabled;
  };
  const close = () => {
    menu?.remove();
    menu = undefined;
    trigger.setAttribute('aria-expanded', 'false');
    document.removeEventListener('pointerdown', outside);
    window.removeEventListener('resize', close);
    window.removeEventListener('scroll', close, true);
  };
  const outside = event => {
    if (!menu?.contains(event.target) && !trigger.contains(event.target)) close();
  };
  const open = () => {
    close();
    menu = document.createElement('div');
    menu.className = 'model-dd';
    menu.setAttribute('role', 'listbox');
    menu.setAttribute('aria-label', trigger.getAttribute('aria-label'));
    const rect = trigger.getBoundingClientRect();
    const width = Math.min(Math.max(rect.width, 240), 380, innerWidth - 16);
    const height = Math.min(select.options.length * 30 + 10, 240);
    Object.assign(menu.style, {
      position: 'fixed', width: `${width}px`,
      left: `${Math.max(8, Math.min(rect.left, innerWidth - width - 8))}px`,
      top: `${innerHeight - rect.bottom < height && rect.top > height ? rect.top - height - 4 : rect.bottom + 4}px`,
    });
    for (const option of select.options) {
      const item = document.createElement('div');
      item.className = `dd-item${option.selected ? ' active' : ''}`;
      item.setAttribute('role', 'option');
      item.setAttribute('aria-selected', String(option.selected));
      item.tabIndex = 0;
      item.textContent = option.textContent;
      item.onclick = () => {
        select.value = option.value;
        select.dispatchEvent(new Event('change', { bubbles: true }));
        sync(); close(); trigger.focus();
      };
      menu.append(item);
    }
    menu.onkeydown = event => {
      const items = [...menu.children];
      const index = items.indexOf(document.activeElement);
      if (event.key === 'Escape' || event.key === 'Tab') {
        close();
        if (event.key === 'Escape') { event.preventDefault(); trigger.focus(); }
      } else if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault(); document.activeElement.click();
      } else if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
        event.preventDefault();
        items[event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1
          : (index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length]?.focus();
      }
    };
    document.body.append(menu);
    trigger.setAttribute('aria-expanded', 'true');
    (menu.querySelector('[aria-selected="true"]') || menu.firstElementChild)?.focus();
    document.addEventListener('pointerdown', outside);
    window.addEventListener('resize', close);
    window.addEventListener('scroll', close, true);
  };
  trigger.onclick = () => menu ? close() : open();
  trigger.onkeydown = event => {
    if (['ArrowDown', 'ArrowUp'].includes(event.key)) { event.preventDefault(); open(); }
  };
  select.addEventListener('change', sync);
  new MutationObserver(sync).observe(select, { childList: true, subtree: true, attributes: true });
  // The fallback session loader also assigns select.value programmatically.
  const value = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value');
  Object.defineProperty(select, 'value', {
    get() { return value.get.call(this); },
    set(next) { value.set.call(this, next); sync(); },
  });
  sync();
});
