/* Run the actual UI against a fake DOM/API: projection, live queues and exit cancellation. */
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'../rk3588/playground.js'),'utf8');
const geometry=vm.createContext({});vm.runInContext(source.split('/* Browser console:')[0],geometry);
const model=geometry.RoArmModel;
const home=model.points({base:0,shoulder:0,elbow:90,gripper:180});
assert.ok(Math.abs(home[2][0]-30)<1e-9);
assert.ok(Math.abs(home[2][2]-362.88)<1e-9);
assert.ok(Math.abs(home[3][0]-310.15534)<1e-4);
// Rotating the real base rotates XY, while preserving physical heights and lengths.
const left=model.points({base:90,shoulder:0,elbow:90,gripper:180});
assert.ok(Math.abs(left[3][0])<1e-8);assert.ok(Math.abs(left[3][1]-home[3][0])<1e-8);
for(const yaw of [-2,-.4,.75,2])for(const pitch of [.1,.32,.8,1.25]){
  const view={w:400,h:240,yaw,pitch,center:240,focal:280,distance:1200};
  // Projection followed by exact ray/plane intersection must recover world mm.
  for(const plane of ['vertical','horizontal']){
    const anchor=home[3],pixel=model.project(anchor,view),world=model.unproject(pixel,view,anchor,plane);
    if(world)for(let axis=0;axis<3;axis++)assert.ok(Math.abs(world[axis]-anchor[axis])<1e-7);
  }
  // Higher objects are nearer to an eye above the stage, unlike the old inverted view.
  assert.ok(model.project([0,0,300],view).depth<model.project([0,0,0],view).depth);
}

function environment(){
  const elements=new Map(),timers=new Map(),actions=[],listeners={},cards=[],intervals=[],frames=[],arcs=[];let nextTimer=1,now=0;
  class Element{
    constructor(tag='div'){this.tag=tag;this.children=[];this.style={};this.dataset={};this.value='';this.checked=false;this.hidden=false;this.width=400;this.height=240;this.className='';this.classList={add:()=>{},toggle:()=>{}};}
    set id(value){this._id=value;elements.set(value,this);}get id(){return this._id;}
    append(...items){this.children.push(...items);if(this.id==='project-grid')cards.push(...items);}
    replaceChildren(...items){this.children=items;}
    setAttribute(key,value){this[key]=value;}removeAttribute(key){delete this[key];}
    getBoundingClientRect(){return{left:0,top:0,width:400,height:240};}
    getContext(){return new Proxy({measureText:text=>({width:text.length*6}),arc:(x,y,r)=>{if(this.id==='robot-view')arcs.push({x,y,r});}},{get:(target,key)=>key in target?target[key]:()=>{}});}
    querySelector(){return new Element();}setPointerCapture(){}scrollIntoView(){}
  }
  const html=fs.readFileSync(path.join(__dirname,'../rk3588/control.html'),'utf8');
  for(const match of html.matchAll(/id="([^"]+)"/g)){const item=new Element();item.id=match[1];}
  elements.get('search').value='';elements.get('coord-speed').value='.5';elements.get('coord-step').value='10';elements.get('model-plane').value='vertical';elements.get('led').value='0';
  const state={mode:'objects',arm:{connected:true,joints:{base:0,shoulder:0,elbow:90,gripper:180},raw:{x:310,y:0,z:236,t:Math.PI}},vision:{detections:[]},events:[]};
  const document={getElementById:id=>elements.get(id),createElement:tag=>new Element(tag),activeElement:null,hidden:false,
    querySelector:()=>new Element(),querySelectorAll:()=>[],addEventListener:(name,callback)=>listeners[name]=callback};
  const response=data=>({ok:true,status:200,json:async()=>data});
  const fetch=(url,options={})=>{
    if(url==='/api/action')return new Promise(resolve=>actions.push({packet:JSON.parse(options.body),options,finish:()=>resolve(response({ok:true,result:{requested:true}}))}));
    return Promise.resolve(response(url==='/api/state'?state:url==='/status'?{ready:false}: {modes:[{id:'m1',width:640,height:480,fps:30,fourcc:'MJPG'}]}));
  };
  class ClockDate extends Date{static now(){return now;}}
  const context=vm.createContext({document,fetch,AbortSignal,URL,console,Date:ClockDate,Math,setInterval:(fn,ms)=>intervals.push({fn,ms}),requestAnimationFrame:fn=>{frames.push(fn);return frames.length;},setTimeout:fn=>{const id=nextTimer++;timers.set(id,fn);return id;},clearTimeout:id=>timers.delete(id),addEventListener:(name,callback)=>listeners[name]=callback,devicePixelRatio:1});
  context.window=context;vm.runInContext(source,context);
  return{elements,actions,listeners,timers,cards,state,intervals,arcs,frame(ms){now=ms;const pending=frames.splice(0);for(const fn of pending)fn();},runTimers(){const pending=[...timers];timers.clear();for(const [,fn] of pending)fn();}};
}
const settle=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
(async()=>{
  const e=environment();await settle();
  const slider=e.elements.get('range-base');
  for(const value of [10,11,12]){slider.value=String(value);slider.oninput();}
  e.runTimers();assert.equal(e.actions.length,1);assert.equal(e.actions[0].packet.angle,12);
  assert.equal(e.actions[0].packet.action,'joint'); // Recognition mode never receives an implicit stop/mode switch.
  for(const value of [13,14]){slider.value=String(value);slider.oninput();}
  e.actions[0].finish();await settle();e.runTimers();
  assert.equal(e.actions.length,2);assert.equal(e.actions[1].packet.angle,14);
  slider.value='15';slider.oninput();e.elements.get('stop').onclick();
  assert.equal(e.actions[2].packet.action,'stop');assert.ok(e.actions[2].packet._ui_sequence>e.actions[1].packet._ui_sequence);
  e.actions[1].finish();e.actions[2].finish();await settle();e.runTimers();assert.equal(e.actions.length,3);
  const led=e.elements.get('led');led.value='123';led.oninput();e.runTimers();
  assert.equal(e.actions[3].packet.action,'led');assert.equal(e.actions[3].packet.value,123);
  led.value='150';led.oninput();e.listeners.pagehide();
  assert.equal(e.actions[4].packet.action,'stop');assert.equal(e.actions[4].options.keepalive,true);
  e.actions[3].finish();await settle();e.runTimers();assert.equal(e.actions.length,5);
  assert.equal(e.elements.get('range-gripper').min,45);assert.equal(e.elements.get('range-gripper').max,180);
  assert.equal(e.elements.get('camera-config').children.length,1);
  assert.ok(e.elements.get('command-help').children.length>=60);
  // Drag the actual rendered end effector, exercising pointer dispatch and the factory IK API.
  const d=environment();await settle();const canvas=d.elements.get('robot-view');
  d.elements.get('model-sync').checked=true;d.elements.get('model-sync').onchange();
  const view={w:400,h:240,yaw:.75,pitch:.32,center:240,focal:288,distance:1200};
  const tip=model.project(home[3],view);
  canvas.onpointerdown({button:0,pointerId:1,clientX:tip.x,clientY:tip.y});
  canvas.onpointermove({clientX:tip.x+4,clientY:tip.y+3});canvas.onpointerup();d.runTimers();
  assert.equal(d.actions[0].packet.action,'cartesian');assert.ok(Math.abs(d.actions[0].packet.y)<1e-7);
  assert.notEqual(d.actions[0].packet.x,310.15534);assert.equal(d.actions[0].packet.direct,true);assert.equal(d.actions[0].packet.t,Math.PI);
  assert.equal('spd' in d.actions[0].packet,false);
  assert.equal(d.elements.get('feedback-base').textContent,'0.0°');
  // A requested target never drives the green model; measured changes animate between samples.
  assert.equal(d.intervals[0].ms,100);
  d.frame(100);d.state.arm.joints.base=40;await d.intervals[0].fn();
  assert.equal(d.elements.get('feedback-base').textContent,'40.0°');
  d.arcs.length=0;d.frame(140);
  const halfway=model.project(model.points({base:20,shoulder:0,elbow:90,gripper:180})[3],view);
  assert.ok(d.arcs.some(arc=>arc.r===7&&Math.abs(arc.x-halfway.x)<1e-8&&Math.abs(arc.y-halfway.y)<1e-8));
  d.arcs.length=0;d.frame(180);
  const measured=model.project(model.points(d.state.arm.joints)[3],view);
  assert.ok(d.arcs.some(arc=>arc.r===7&&Math.abs(arc.x-measured.x)<1e-8&&Math.abs(arc.y-measured.y)<1e-8));
  console.log('UI tests passed: manufacturer FK, perspective ray/plane, latest live input, preserved recognition, stop/exit ordering, camera and command controls.');
})().catch(error=>{console.error(error);process.exitCode=1;});
