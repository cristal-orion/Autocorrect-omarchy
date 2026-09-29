// Chromium's Wayland IME needs an explicit spellcheck hint. An inherited
// spellcheck=true may otherwise look identical to a disabled code field.
// This bridge only sets that hint: it never reads, sends or replaces text.
(() => {
  const selector = 'textarea,input,[contenteditable="true"],[contenteditable="plaintext-only"]';

  function requestedSiteField(field) {
    const host = location.hostname;
    if (['google.com', 'www.google.com', 'google.it', 'www.google.it'].includes(host))
      return field.matches('textarea[name="q"],input[name="q"]');
    if (['translate.google.com', 'translate.google.it'].includes(host))
      return field.tagName === 'TEXTAREA';
    if (host === 'gemini.google.com')
      return field.matches('[contenteditable="true"][role="textbox"]');
    if (['chatgpt.com', 'chat.openai.com'].includes(host))
      return field.id === 'prompt-textarea' || field.matches('[contenteditable][role="textbox"]');
    return false;
  }

  function prepare(element) {
    const field = element instanceof Element ? element.closest(selector) : null;
    if (!field || field.disabled || field.readOnly) return;
    if (field.tagName === 'INPUT' && !['text', 'search'].includes(field.type)) return;
    if (field.closest('.monaco-editor,.cm-editor,.CodeMirror,[role="code"]')) return;
    if (/password|one-time-code/.test(field.getAttribute('autocomplete') || '')) return;
    if (field.getAttribute('spellcheck') === 'true') return;
    // Respect explicit opt-outs everywhere except the requested, identified
    // search / translation / chat composers, which are ordinary prose fields.
    if (field.spellcheck || requestedSiteField(field)) field.setAttribute('spellcheck', 'true');
  }

  document.addEventListener('focusin', event => prepare(event.composedPath()[0]), true);
  new MutationObserver(() => prepare(document.activeElement)).observe(document, {
    subtree: true, attributes: true, attributeFilter: ['spellcheck', 'contenteditable'],
  });
  prepare(document.activeElement);
})();
