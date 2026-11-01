/**
 * OKP 摇杆卡（custom:okp-joystick-card）
 *
 * 把集成的 okp_cloud.move 服务包成一个圆形摇杆：按住方向持续移动，
 * 松手（或切走页面、失焦、卡片被移除）立刻松开。
 *
 * 为什么需要这张卡：Home Assistant 没有摇杆实体，也没有任何内置卡片能
 * 表达「按住 / 松开」两段手势——button 只有瞬时点击。而 move dp 本来就是
 * 两段的（按下写方向，松手写 4），所以手势这一段只能由前端卡片负责。
 *
 * 安全约定（与集成侧保持一致）：
 *   - 单次按住最长 10 秒，到点自动松开（集成里的看门狗也是 10+2 秒）；
 *   - 任何可能「手指已经离开但事件丢了」的情况都补发一次 stop；
 *   - 卡片卸载（切视图）时也补发 stop。
 *
 * 配置：
 *   type: custom:okp-joystick-card
 *   entity: vacuum.sao_di_ji_qi_ren   # 可选，用于显示状态并自动推断设备 ID
 *   device_id: 100258a68a             # 多台机器人时才需要
 *   name: 手动遥控                     # 可选标题
 *   size: 220                         # 可选，摇杆直径（px）
 */

const HOLD_LIMIT_MS = 10000;
const DEAD_ZONE = 0.16; // 半径的 16% 内不触发方向

const I18N = {
  zh: {
    title: "手动遥控",
    hint: "按住方向持续移动，松手即刻停止",
    stop: "停",
    unavailable: "集成未就绪",
    held: "移动中",
    released: "已松开",
    limit: "单次按住已达 10 秒上限",
    no_service: "找不到 okp_cloud.move 服务",
  },
  en: {
    title: "Manual remote",
    hint: "Hold a direction to move, release to stop",
    stop: "STOP",
    unavailable: "Integration not ready",
    held: "Moving",
    released: "Released",
    limit: "Hold limit (10 s) reached",
    no_service: "okp_cloud.move service not found",
  },
};

class OkpJoystickCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._active = null;
    this._pointerId = null;
    this._holdTimer = null;
    this._raf = null;
    this._pending = null;
    this._statusText = "";
    this._onVisibility = () => {
      if (document.visibilityState !== "visible") this._release("hidden");
    };
    this._onBlur = () => this._release("blur");
  }

  static getStubConfig(hass) {
    const vac = Object.keys(hass.states).find((e) => e.startsWith("vacuum."));
    return { entity: vac || "", size: 220 };
  }

  setConfig(config) {
    if (config && config.entity && !String(config.entity).includes(".")) {
      throw new Error("entity 需要是实体 ID，例如 vacuum.sao_di_ji_qi_ren");
    }
    this._config = Object.assign({ size: 220 }, config || {});
    this._render();
  }

  getCardSize() {
    return 4;
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) {
      this._t = I18N[(hass && hass.language || "en").startsWith("zh") ? "zh" : "en"];
      this._render();
      document.addEventListener("visibilitychange", this._onVisibility);
      window.addEventListener("blur", this._onBlur);
    }
    this._updateStatus();
  }

  disconnectedCallback() {
    document.removeEventListener("visibilitychange", this._onVisibility);
    window.removeEventListener("blur", this._onBlur);
    // 切到别的视图时补发松开，避免机器人还在跑
    this._release("detached");
  }

  // -- 设备与状态 ---------------------------------------------------------

  _deviceId() {
    if (this._config.device_id) return String(this._config.device_id);
    const entity = this._config.entity;
    const hass = this._hass;
    if (!entity || !hass || !hass.entities || !hass.devices) return null;
    const ent = hass.entities[entity];
    const dev = ent && ent.device_id ? hass.devices[ent.device_id] : null;
    if (!dev || !Array.isArray(dev.identifiers)) return null;
    for (const pair of dev.identifiers) {
      if (Array.isArray(pair) && pair[0] === "okp_cloud" && pair[1]) return String(pair[1]);
    }
    return null;
  }

  _serviceReady() {
    const hass = this._hass;
    const svc = hass && hass.services && hass.services.okp_cloud;
    return !!(svc && svc.move);
  }

  _updateStatus() {
    const el = this.shadowRoot && this.shadowRoot.querySelector(".state");
    if (!el || !this._hass) return;
    const t = this._t || I18N.en;
    let text;
    if (!this._serviceReady()) {
      text = t.unavailable;
    } else if (this._active) {
      text = t.held + " · " + this._active;
    } else if (this._statusText) {
      text = this._statusText;
    } else {
      const st = this._config.entity && this._hass.states[this._config.entity];
      text = st ? st.state : "";
      const battery = st && st.attributes && st.attributes.battery_level;
      if (battery !== undefined && battery !== null) text += " · " + battery + "%";
    }
    el.textContent = text;
  }

  // -- 渲染 ---------------------------------------------------------------

  _render() {
    if (!this._config || !this._t) return;
    const t = this._t;
    const size = Number(this._config.size) || 220;
    const title = this._config.name === undefined ? t.title : this._config.name;

    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; }
        .wrap {
          background: var(--ha-card-background, var(--card-background-color, #fff));
          border-radius: var(--ha-card-border-radius, 12px);
          border: var(--ha-card-border-width, 1px) solid var(--ha-card-border-color, var(--divider-color, rgba(0,0,0,.12)));
          color: var(--primary-text-color, #212121);
          padding: 12px 12px 14px;
          display: flex; flex-direction: column; align-items: center; gap: 8px;
          user-select: none; -webkit-user-select: none;
        }
        .head {
          width: 100%; display: flex; align-items: baseline;
          justify-content: space-between; gap: 8px; font-size: 13px;
        }
        .title { font-weight: 600; }
        .state { color: var(--secondary-text-color, #727272); font-size: 12px; }
        .pad {
          position: relative; width: ${size}px; height: ${size}px;
          touch-action: none; cursor: grab; border-radius: 50%;
        }
        .pad.dragging { cursor: grabbing; }
        svg { display: block; width: 100%; height: 100%; }
        .ring { fill: var(--secondary-background-color, rgba(0,0,0,.04)); stroke: var(--divider-color, rgba(0,0,0,.12)); stroke-width: 1.5; }
        .ring-inner { fill: none; stroke: var(--divider-color, rgba(0,0,0,.10)); stroke-width: 1; }
        .arrow { fill: var(--secondary-text-color, #9e9e9e); transition: fill .08s linear; }
        .arrow.on { fill: var(--primary-color, #03a9f4); }
        .stop {
          position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%);
          width: ${Math.round(size * 0.3)}px; height: ${Math.round(size * 0.3)}px;
          border-radius: 50%; border: 1px solid var(--divider-color, rgba(0,0,0,.16));
          background: var(--card-background-color, #fff);
          color: var(--primary-text-color, #212121);
          font: inherit; font-size: ${Math.max(11, Math.round(size * 0.062))}px;
          font-weight: 600; cursor: pointer; touch-action: manipulation;
        }
        .stop:active { background: var(--secondary-background-color, rgba(0,0,0,.06)); }
        .hint {
          font-size: 11px; color: var(--secondary-text-color, #9e9e9e);
          text-align: center; line-height: 1.4;
        }
        .flash { color: var(--error-color, #db4437); }
      </style>
      <div class="wrap">
        <div class="head"><span class="title">${title}</span><span class="state"></span></div>
        <div class="pad" role="application" aria-label="${t.title}">
          <svg viewBox="0 0 200 200" aria-hidden="true">
            <circle class="ring" cx="100" cy="100" r="97"></circle>
            <circle class="ring-inner" cx="100" cy="100" r="66"></circle>
            <path class="arrow" data-dir="forward"  d="M100 12 L112 34 L104 34 L104 46 L96 46 L96 34 L88 34 Z"></path>
            <path class="arrow" data-dir="backward" d="M100 188 L88 166 L96 166 L96 154 L104 154 L104 166 L112 166 Z"></path>
            <path class="arrow" data-dir="left"     d="M12 100 L34 88 L34 96 L46 96 L46 104 L34 104 L34 112 Z"></path>
            <path class="arrow" data-dir="right"    d="M188 100 L166 112 L166 104 L154 104 L154 96 L166 96 L166 88 Z"></path>
          </svg>
          <button class="stop" type="button">${t.stop}</button>
        </div>
        <div class="hint">${t.hint}</div>
      </div>`;

    this._pad = this.shadowRoot.querySelector(".pad");
    this._stopBtn = this.shadowRoot.querySelector(".stop");
    this._pad.addEventListener("pointerdown", (e) => this._onDown(e));
    this._pad.addEventListener("pointermove", (e) => this._onMove(e));
    this._pad.addEventListener("pointerup", () => this._release("up"));
    this._pad.addEventListener("pointercancel", () => this._release("cancel"));
    this._pad.addEventListener("lostpointercapture", () => this._release("lost"));
    this._stopBtn.addEventListener("click", () => {
      this._release("button");
      this._flash(this._t.released);
    });
    this._updateStatus();
  }

  // -- 手势 ---------------------------------------------------------------

  _onDown(ev) {
    if (ev.button !== undefined && ev.button !== 0) return;
    if (!this._serviceReady()) {
      this._flash(this._t.no_service);
      return;
    }
    ev.preventDefault();
    this._pointerId = ev.pointerId;
    this._pad.setPointerCapture(ev.pointerId);
    this._pad.classList.add("dragging");
    this._update(ev);
  }

  _onMove(ev) {
    if (this._pointerId === null || ev.pointerId !== this._pointerId) return;
    ev.preventDefault();
    // 每帧最多判一次，避免 pointermove 高频刷服务调用
    this._pending = ev;
    if (this._raf) return;
    this._raf = requestAnimationFrame(() => {
      this._raf = null;
      const e = this._pending;
      this._pending = null;
      if (e && this._pointerId !== null) this._update(e);
    });
  }

  _update(ev) {
    const rect = this._pad.getBoundingClientRect();
    const dx = ev.clientX - (rect.left + rect.width / 2);
    const dy = ev.clientY - (rect.top + rect.height / 2);
    const radius = rect.width / 2;
    const dist = Math.hypot(dx, dy) / radius;
    if (dist < DEAD_ZONE) {
      this._apply(null);
      return;
    }
    // 屏幕坐标：0° = 右，90° = 下；四象限各 90° 对应四个方向
    const deg = (Math.atan2(dy, dx) * 180) / Math.PI;
    let dir;
    if (deg >= -135 && deg < -45) dir = "forward";
    else if (deg >= 45 && deg < 135) dir = "backward";
    else if (deg >= -45 && deg < 45) dir = "right";
    else dir = "left";
    this._apply(dir);
  }

  _apply(dir) {
    if (dir === this._active) return;
    this._active = dir;
    this.shadowRoot.querySelectorAll(".arrow").forEach((el) => {
      el.classList.toggle("on", el.dataset.dir === dir);
    });
    if (dir) {
      this._call(dir);
      this._startHoldTimer();
    } else {
      this._clearHoldTimer();
      this._call("stop");
    }
    this._updateStatus();
  }

  _startHoldTimer() {
    this._clearHoldTimer();
    this._holdTimer = setTimeout(() => {
      this._holdTimer = null;
      this._release("limit");
      this._flash(this._t.limit);
    }, HOLD_LIMIT_MS);
  }

  _clearHoldTimer() {
    if (this._holdTimer) {
      clearTimeout(this._holdTimer);
      this._holdTimer = null;
    }
  }

  _release(reason) {
    const holding = this._active !== null || this._pointerId !== null;
    this._clearHoldTimer();
    if (this._raf) {
      cancelAnimationFrame(this._raf);
      this._raf = null;
    }
    this._pending = null;
    this._active = null;
    if (this._pointerId !== null && this._pad) {
      try {
        this._pad.releasePointerCapture(this._pointerId);
      } catch (e) {
        /* 指针已失效，忽略 */
      }
    }
    this._pointerId = null;
    if (this._pad) this._pad.classList.remove("dragging");
    const arrows = this.shadowRoot.querySelectorAll(".arrow");
    if (arrows) arrows.forEach((el) => el.classList.remove("on"));
    // 只有真的在动的时候才发 stop，避免无谓写入
    if (holding) this._call("stop");
    if (reason !== "limit") this._statusText = "";
    this._updateStatus();
  }

  _call(direction) {
    const hass = this._hass;
    if (!hass) return;
    // direction: 0 表示「按住不放」，直到我们显式发 stop（或 10 秒后看门狗松开）
    // stop 本身在集成里直接映射成 move=4（松开），不带停留时间
    const data = { direction, duration: 0 };
    const device = this._deviceId();
    if (device) data.device_id = device;
    hass.callService("okp_cloud", "move", data).catch((err) => {
      this._flash(String(err && err.message ? err.message : err));
      this._release("error");
    });
  }

  _flash(text) {
    const el = this.shadowRoot && this.shadowRoot.querySelector(".state");
    if (!el) return;
    el.textContent = text;
    el.classList.add("flash");
    setTimeout(() => {
      el.classList.remove("flash");
      this._updateStatus();
    }, 2000);
  }
}

if (!customElements.get("okp-joystick-card")) {
  customElements.define("okp-joystick-card", OkpJoystickCard);
}

window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === "okp-joystick-card")) {
  window.customCards.push({
    type: "okp-joystick-card",
    name: "OKP 摇杆",
    description: "按住方向驱动机器人，松手即刻停止（调用 okp_cloud.move）",
    preview: false,
    documentationURL: "https://github.com/RockJesus/ha-okp",
  });
}

console.info("%c OKP-JOYSTICK-CARD %c v1.4.5 ", "background:#03a9f4;color:#fff;border-radius:3px 0 0 3px;padding:2px 4px", "background:#455a64;color:#fff;border-radius:0 3px 3px 0;padding:2px 4px");
