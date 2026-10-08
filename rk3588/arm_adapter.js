/* Preserve the live firmware UI; serialize commands, block BOOT and stop released axes. */
(() => {
  const nativeSend = XMLHttpRequest.prototype.send;
  const nativeOpen = XMLHttpRequest.prototype.open;
  const blocked = new Set([600, 601, 603, 604]);
  const queue = [];
  const active = new Map(); // Each axis retains its start until the matching stop succeeds.
  let sending = false;
  let leaving = false;
  const client = Date.now() + '-' + Math.random().toString(36).slice(2);
  let sequence = 0;

  function stamp(command) {
    // The proxy strips these fields; they prevent late starts after an exit stop.
    if (command?.T === 123) Object.assign(command, {_ui_client:client, _ui_sequence:++sequence});
    return command;
  }

  function status(text) {
    document.getElementById('arm-proxy-status').textContent = text;
    if (parent !== window) parent.postMessage({armStatus: text}, location.origin);
  }
  const note = document.createElement('div');
  note.id = 'arm-proxy-status';
  note.style.cssText = 'padding:12px;color:#bde0ff;text-align:center;position:sticky;top:0;background:#252936;z-index:10';
  document.body.prepend(note);

  // Only one XHR is in flight. Start, feedback and matching stop retain their order.
  function drain() {
    if (sending || !queue.length) return;
    const {xhr, body, command, stoppedStart} = queue.shift();
    sending = true;
    xhr.timeout = 5000; // Server's upstream deadline is three seconds.
    xhr.addEventListener('loadend', () => {
      sending = false;
      if (xhr.status >= 200 && xhr.status < 300) {
        status('机械臂已连接 · BOOT / 重启 / 重置已禁用');
      } else {
        status(xhr.responseText || '机械臂请求失败或超时，请检查网络');
        // Once a start might have reached the arm, retain its axis until a stop succeeds.
        if (!leaving && command?.T === 123 && command.cmd !== 0) window.stopArm();
      }
      if (command?.T === 123 && command.cmd === 0 && xhr.status === 200 && active.get(command.axis) === stoppedStart) {
        active.delete(command.axis);
        if (stoppedStart && !active.size && !leaving && typeof window.getData === 'function') window.getData();
      }
      drain();
    });
    try { nativeSend.call(xhr, body); }
    catch (error) { sending = false; status('机械臂请求失败：' + error.message); drain(); }
  }

  XMLHttpRequest.prototype.open = function(method, rawUrl, ...rest) {
    let url = new URL(rawUrl, document.baseURI);
    let command = null;
    if (url.pathname.endsWith('/js')) {
      // Native code concatenates raw JSON. Encode it before URL parsing can lose # or &.
      const raw = String(rawUrl).split('?json=')[1];
      try {
        try { command = JSON.parse(raw ?? url.searchParams.get('json')); }
        catch (_) { command = JSON.parse(decodeURIComponent(raw)); }
        stamp(command);
        url = new URL('/arm/js', location.origin);
        url.searchParams.set('json', JSON.stringify(command));
      } catch (_) { status('JSON 指令格式错误'); this.armBlocked = true; return; }
    }
    this.armCommand = command;
    this.armBlocked = url.pathname.endsWith('/getDevInfo') || blocked.has(command?.T);
    if (this.armBlocked) { status('BOOT、重启及重置入口已禁用'); return; }
    this.armRequest = url.pathname === '/arm/js';
    nativeOpen.call(this, method, url.href, ...rest);
  };
  XMLHttpRequest.prototype.send = function(body) {
    if (this.armBlocked) return;
    if (!this.armRequest) return nativeSend.call(this, body);
    const command = this.armCommand;
    if (leaving && command?.T === 123 && command.cmd !== 0) return;
    if (command?.T === 123 && command.cmd === 0) {
      // A release need not wait for queued read-only feedback; refresh after stopping.
      for (let i = queue.length - 1; i >= 0; i--) {
        if (queue[i].command?.T === 105) queue.splice(i, 1);
      }
    }
    const stoppedStart = command?.cmd === 0 ? active.get(command.axis) : null;
    if (command?.T === 123 && command.cmd !== 0 && command.axis >= 1 && command.axis <= 4)
      active.set(command.axis, {mode:command.m});
    queue.push({xhr: this, body, command, stoppedStart});
    drain();
  };

  function stopAxis(mode, axis, speed = 10) {
    const xhr = new XMLHttpRequest();
    xhr.open('GET', '/arm/js?json=' + JSON.stringify({T: 123, m: mode, axis, cmd: 0, spd: speed}), true);
    xhr.send();
  }
  window.stopArm = function(all = false) {
    const axes = all ? [1, 2, 3, 4] : [...active.keys()];
    const mode = [...active.values()].at(-1)?.mode ?? 0;
    // spd=0 immediately freezes the firmware's shared T123 speed, then clears each axis.
    for (const axis of axes) stopAxis(mode, axis, 0);
  };

  // Pointer capture replaces duplicate mouse/touch handlers and catches release off-button.
  for (const button of document.querySelectorAll('[onmousedown*="cmdSend("]')) {
    const match = button.getAttribute('onmousedown').match(/cmdSend\((\d+),(\d+),(\d+)\)/);
    if (!match) continue;
    const [mode, axis, direction] = match.slice(1).map(Number);
    for (const event of ['mousedown', 'mouseup', 'touchstart', 'touchend']) button.removeAttribute('on' + event);
    button.style.touchAction = 'none';
    let pressed = false;
    button.addEventListener('pointerdown', event => {
      if (event.button !== 0) return;
      event.preventDefault();
      button.setPointerCapture(event.pointerId);
      pressed = true;
      window.cmdSend(mode, axis, direction);
    });
    const release = () => { if (pressed) { pressed = false; stopAxis(mode, axis); } };
    button.addEventListener('pointerup', release);
    button.addEventListener('pointercancel', release);
    button.addEventListener('lostpointercapture', release);
  }
  window.addEventListener('blur', () => window.stopArm());
  document.addEventListener('visibilitychange', () => { if (document.hidden) window.stopArm(); });
  window.addEventListener('pagehide', () => {
    // The page may disappear before queued XHRs run. Keepalive carries four explicit stops.
    leaving = true;
    // Discard starts which have not been sent, so none can follow the final stops.
    for (let i = queue.length - 1; i >= 0; i--) {
      if (queue[i].command?.T === 123 && queue[i].command.cmd !== 0) queue.splice(i, 1);
    }
    for (const [axis, start] of active) {
      const url = '/arm/js?json=' + encodeURIComponent(JSON.stringify(stamp({T:123, m:start.mode, axis, cmd:0, spd:0})));
      fetch(url, {keepalive:true}).catch(() => {});
    }
  });
  // BOOT is a legacy getDevInfo entry. Do not invoke it even if a firmware adds its button.
  window.getDevInfo = () => status('BOOT 入口已禁用；使用反馈读取设备状态');
  for (const button of document.querySelectorAll('button')) {
    if (button.textContent.trim() === 'BOOT' || (button.getAttribute('onclick') || '').includes('getDevInfo')) {
      button.disabled = true;
      button.title = '按任务要求禁用 BOOT';
    }
  }
  status('原生控制页面已加载 · BOOT / 重启 / 重置已禁用');
  // A read-only feedback request verifies arm connectivity without starting any motion.
  if (typeof window.getData === 'function') window.getData();
  // Refresh measured angles after the servo settles; never delay an active jog's release.
  setInterval(() => {
    if (!leaving && !document.hidden && !sending && !queue.length && !active.size && typeof window.getData === 'function') window.getData();
  }, 1000);
})();
