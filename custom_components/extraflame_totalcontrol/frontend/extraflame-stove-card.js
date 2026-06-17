/**
 * Extraflame Stove Card - Home Assistant Lovelace custom card
 *
 * Reads a "visual" sensor exposed by the Shad107/ha-extraflame-totalcontrol
 * integration (state = stove name, attribute carries an inline SVG of the
 * stove). Renders the SVG inside an ha-card. Click on the SVG opens
 * more-info on the climate entity (or any entity passed via tap_action_entity).
 *
 * Pure vanilla web-component - no LitElement dependency, no build step.
 * Compatible with Home Assistant >= 2024.1.
 */

const CARD_VERSION = "0.1.6";

class ExtraflameStoveCard extends HTMLElement {
  setConfig(config) {
    if (!config || !config.entity) {
      throw new Error('entity (the *_visual sensor) is required');
    }
    this._config = config;
  }

  set hass(hass) {
    this._hass = hass;
    const entity = this._config.entity;
    const state = hass.states[entity];
    this._ensureSkeleton();
    if (!state) {
      this._body.innerHTML =
        `<div class="error">Entity not found: <code>${entity}</code></div>`;
      return;
    }
    const attrs = state.attributes || {};
    const svg = attrs.svg || '';
    // Title priority:
    //   1. explicit config.title (user wins)
    //   2. model name from the cloud resource_id mapping (e.g. "Teodora Evo")
    //   3. user-given stove name from the TotalControl app
    //   4. friendly_name as last resort (may include the platform suffix)
    const title =
      this._config.title !== undefined
        ? this._config.title
        : attrs.model || attrs.stove_name || attrs.friendly_name || '';
    const subtitle = attrs.model && attrs.stove_name && attrs.stove_name !== attrs.model
      ? attrs.stove_name
      : '';
    this._body.innerHTML = `
      ${title ? `<div class="title">${title}</div>` : ''}
      ${subtitle ? `<div class="subtitle">${subtitle}</div>` : ''}
      <div class="svg-wrap">${svg || '<div class="empty">No SVG available</div>'}</div>
    `;
    this._wireClick();
  }

  _ensureSkeleton() {
    if (this._card) return;
    this._card = document.createElement('ha-card');
    const style = document.createElement('style');
    style.textContent = `
      :host { display: block; }
      .title {
        padding: 12px 16px 0;
        font-size: 1.05em;
        font-weight: 500;
        color: var(--primary-text-color);
      }
      .subtitle {
        padding: 0 16px 4px;
        font-size: 0.85em;
        color: var(--secondary-text-color);
      }
      .svg-wrap {
        padding: 8px 8px 12px;
        display: flex;
        justify-content: center;
      }
      .svg-wrap svg {
        display: block;
        max-width: 280px;
        width: 100%;
        height: auto;
      }
      .empty {
        color: var(--secondary-text-color);
        font-style: italic;
        padding: 32px;
        text-align: center;
      }
      .error {
        color: var(--error-color);
        padding: 16px;
        font-family: monospace;
        font-size: 0.9em;
      }
    `;
    this._card.appendChild(style);
    this._body = document.createElement('div');
    this._card.appendChild(this._body);
    this.appendChild(this._card);
  }

  _wireClick() {
    const wrap = this._body.querySelector('.svg-wrap');
    if (!wrap) return;
    if (this._config.tap_action === 'none') {
      wrap.style.cursor = '';
      wrap.onclick = null;
      return;
    }
    wrap.style.cursor = 'pointer';
    wrap.onclick = () => {
      const target = this._config.tap_action_entity || this._config.entity;
      this._fireMoreInfo(target);
    };
  }

  _fireMoreInfo(entityId) {
    const ev = new CustomEvent('hass-more-info', {
      bubbles: true,
      composed: true,
      detail: { entityId },
    });
    this.dispatchEvent(ev);
  }

  getCardSize() {
    return 5;
  }

  static getStubConfig(hass) {
    const candidate =
      Object.keys(hass.states).find(
        (id) =>
          id.startsWith('sensor.') &&
          /visual$/.test(id) &&
          hass.states[id].attributes &&
          hass.states[id].attributes.svg,
      ) || 'sensor.visual';
    return { entity: candidate };
  }
}

customElements.define('extraflame-stove-card', ExtraflameStoveCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: 'extraflame-stove-card',
  name: 'Extraflame Stove',
  description: 'Renders an inline SVG of an Extraflame pellet stove.',
  preview: true,
});

// Header banner once per process to confirm load
if (!window.__extraflameStoveCardLogged) {
  // eslint-disable-next-line no-console
  console.info(
    `%c EXTRAFLAME-STOVE-CARD %c ${CARD_VERSION} `,
    'color: white; background: #ff7a18; font-weight: 700;',
    'color: #ff7a18; background: transparent;',
  );
  window.__extraflameStoveCardLogged = true;
}
