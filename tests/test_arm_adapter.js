/* Exercise real adapter code with a fake DOM/XHR; never connect to physical hardware. */
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = require('node:path');

function environment() {
  const sent = [];
  const keepalive = [];
  const listeners = {};
  const timers = [];
  const buttonListeners = {};
  const attributes = {onmousedown:'cmdSend(0,1,1);', onmouseup:'cmdSend(0,1,0);'};
  const button = {
    style:{}, textContent:'B L',
    getAttribute: key => attributes[key],
    removeAttribute: key => delete attributes[key],
    addEventListener: (name, fn) => buttonListeners[name] = fn,
    setPointerCapture: () => {},
  };
  class XHR {
    constructor() { this.listeners = {}; this.status = 0; this.responseText = ''; }
    open(method, url) { this.url = url; }
    addEventListener(name, fn) { this.listeners[name] = fn; }
    send() { sent.push(this); }
    finish(status = 200) { this.status = status; this.listeners.loadend(); }
  }
  const elements = {};
  const document = {
    baseURI:'http://localhost/arm/', hidden:false,
    createElement: () => ({style:{}}),
    body:{prepend: element => elements[element.id] = element},
    getElementById: id => elements[id],
    querySelectorAll: query => query === 'button' ? [button] : [button],
    addEventListener: (name, fn) => listeners[name] = fn,
  };
  const context = vm.createContext({XMLHttpRequest:XHR, URL, document,
    location:{origin:'http://localhost'}, parent:{postMessage:() => {}},
    fetch:(url, options) => { keepalive.push({url, options}); return Promise.resolve(); },
    addEventListener:(name, fn) => listeners[name] = fn,
    setInterval:(fn, ms) => timers.push({fn, ms}),
  });
  context.window = context;
  context.cmdSend = (mode, axis, cmd) => {
    const xhr = new XHR();
    xhr.open('GET', 'js?json=' + JSON.stringify({T:123, m:mode, axis, cmd, spd:10}), true);
    xhr.send();
  };
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../rk3588/arm_adapter.js'), 'utf8'), context);
  const command = xhr => JSON.parse(new URL(xhr.url, 'http://localhost').searchParams.get('json'));
  return {context, sent, keepalive, listeners, buttonListeners, command, timers};
}

// Poll measured feedback at rest, but keep the command queue free during a jog.
{
  const e = environment();
  let reads = 0;
  e.context.getData = () => reads++;
  e.timers[0].fn();
  assert.equal(reads, 1);
  e.context.cmdSend(0, 1, 1);
  e.timers[0].fn();
  assert.equal(reads, 1);
}

// Releasing outside a button must send exactly one stop after the outstanding start.
{
  const e = environment();
  e.buttonListeners.pointerdown({button:0, pointerId:1, preventDefault:() => {}});
  e.buttonListeners.pointerup();
  e.buttonListeners.lostpointercapture();
  assert.equal(e.sent.length, 1);
  assert.equal(e.command(e.sent[0]).cmd, 1);
  e.sent[0].finish();
  assert.equal(e.sent.length, 2);
  assert.equal(e.command(e.sent[1]).axis, 1);
  assert.equal(e.command(e.sent[1]).cmd, 0);
  e.sent[1].finish();
  e.listeners.blur();
  assert.equal(e.sent.length, 2);
}

// A succeeding start on the same axis must survive the earlier stop's acknowledgement.
{
  const e = environment();
  e.context.cmdSend(0, 1, 1);
  e.context.cmdSend(0, 1, 0);
  e.context.cmdSend(0, 1, 2);
  e.sent[0].finish();
  e.sent[1].finish();
  e.listeners.blur();
  e.sent[2].finish();
  assert.equal(e.command(e.sent[3]).cmd, 0);
}

// Pending feedback may be discarded so a released key does not wait for another read.
{
  const e = environment();
  e.context.cmdSend(0, 1, 1);
  const feedback = new e.context.XMLHttpRequest();
  feedback.open('GET', 'js?json={"T":105}', true);
  feedback.send();
  e.context.cmdSend(0, 1, 0);
  e.sent[0].finish();
  assert.equal(e.command(e.sent[1]).T, 123);
  assert.equal(e.command(e.sent[1]).cmd, 0);
}

// BOOT and reset commands never reach native XHR; raw JSON keeps special characters.
{
  const e = environment();
  for (const T of [600, 601, 603, 604]) {
    const xhr = new e.context.XMLHttpRequest();
    xhr.open('GET', 'js?json=' + JSON.stringify({T}), true);
    xhr.send();
  }
  e.context.getDevInfo();
  assert.equal(e.sent.length, 0);
  const xhr = new e.context.XMLHttpRequest();
  xhr.open('GET', 'js?json=' + JSON.stringify({T:202, name:'a&b#c+d 空格.txt'}), true);
  xhr.send();
  assert.equal(e.command(e.sent[0]).name, 'a&b#c+d 空格.txt');
}

// Leaving cancels queued starts, then issues explicit keepalive stops for tracked axes.
{
  const e = environment();
  e.context.cmdSend(0, 1, 1);
  e.context.cmdSend(0, 2, 1);
  e.listeners.pagehide();
  assert.equal(e.keepalive.length, 2);
  assert.ok(e.keepalive.every(item => e.command(item).cmd === 0));
  e.sent[0].finish();
  assert.equal(e.sent.length, 1);
}

console.log('Adapter tests passed: serialized release, restart tracking, BOOT block, JSON encoding, page exit.');
