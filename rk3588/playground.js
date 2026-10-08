/* RoArm Playground: local API client, 18 experiment panels, real-feedback 3D canvas and visual programs. */
'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const JOINTS = {base:'底座', shoulder:'肩部', elbow:'肘部', gripper:'夹爪'};
  // Each tab numbers its actions so a delayed earlier request cannot supersede its later stop.
  const UI_CLIENT = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  let uiSequence = 0;
  // Commands use degrees; feedback also uses degrees. The model is a schematic, never a precision measurement.
  const PROJECTS = [
    ['face','寻找观众，亮灯致意','让机器人发现人脸，跟随观众，并点头打个招呼。','◎','basic','视觉 · 互动'],
    ['color','魔法指挥棒','挥动彩色卡片，让摄像头和机械臂追随你的方向。','✦','basic','颜色 · 跟随'],
    ['gesture','手势遥控','用张手、握拳和其他手势，指挥灯光与夹爪。','✋','basic','手势 · 控制'],
    ['voice','中文语音控制','说一句短口令，观察声音如何变成文字和动作。','◖','basic','声音 · 指令'],
    ['clap','拍手导演与节奏律动','把拍手变成一个信号，让机械臂回应你的节奏。','♫','basic','声音 · 节奏'],
    ['teach','动作示教与回放','保存你调好的姿态，再让机器人重演一段动作。','↺','creative','记忆 · 序列'],
    ['program','图形化动作编程','组合动作积木，添加重复或条件，编出自己的节目。','▦','creative','逻辑 · 编程'],
    ['markers','视觉标记寻宝','藏一张编号标记，让机器人找到它并告诉你编号。','▣','basic','标记 · 搜索'],
    ['objects','常见物品识别与竞猜','展示杯子、瓶子等物品，看看机器人认出了什么。','◇','basic','物品 · 识别'],
    ['rps','和机器人猜拳','出一个手势，让机器人出拳、判定胜负并庆祝。','✌','basic','手势 · 游戏'],
    ['track','框选目标并追踪','直接在画面里框出目标，让机器人持续寻找它。','⌗','advanced','目标 · 追踪'],
    ['panorama','机器人全景摄影师','分段转动、拍摄与拼接，组成一张更宽的照片。','▤','creative','拍摄 · 拼接'],
    ['difference','机器人找不同','移动一个物品，用前后两张照片发现世界的变化。','◑','basic','图像 · 比较'],
    ['digital','真实反馈驱动的三维机械臂','转动实体机械臂，在三维模型中看到相同的变化。','⌬','creative','空间 · 反馈'],
    ['director','自然语言机器人小导演','写一句话，让本地模型把你的想法编排成动作。','❝','advanced','语言 · 编排'],
    ['agent','现场 Agent 改规则挑战','提出新规则，修改代码，再到真实设备上验证。','↗','creative','创意 · 开发'],
    ['foam','黑色泡沫识别与抓取尝试','先找到桌面黑块，再逐步验证接近和夹起。','⬡','advanced','正在开发'],
    ['imu','头部姿态随动','校准中立位，让头部姿态映射到机械臂方向。','⤴','advanced','硬件接入中']
  ].map(([id,title,description,icon,category,tag],index) => ({id,title,description,icon,category,tag,index:index+1}));
  let state = {}, selected = null, filter = 'all', online = false, liveVideo = false;
  let steps = [], directorSteps = [], selection = null, dragStart = null, programDirty = false;
  let statePollBusy = false, cameraPollBusy = false, lastProgramNames = '';
  let switchingProject = false, requestedProject = null;
  let graspBusy = false;
  let cameraYaw = .75, cameraPitch = .32, modelDrag = null;

  function node(tag, text, className) {
    const item = document.createElement(tag);
    if (text !== undefined) item.textContent = text;
    if (className) item.className = className;
    return item;
  }
  function notify(message, failed = false) {
    $('action-message').textContent = message;
    $('action-message').className = failed ? 'error' : '';
  }
  function actionPacket(actionName, payload = {}) {
    return {action:actionName,...payload,_ui_client:UI_CLIENT,_ui_sequence:++uiSequence};
  }
  // Keep operations explicit. Stop is independent of busy controls and can interrupt a running program.
  async function action(actionName, payload = {}, button) {
    if (button) button.disabled = true;
    try {
      const response = await fetch('/api/action', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(actionPacket(actionName,payload)),signal:AbortSignal.timeout(actionName==='director'?120000:30000)});
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.error || `HTTP ${response.status}`);
      notify(data.result?.ignored ? '未执行：'+(data.result.reason||'请先启动对应模式') : typeof data.result === 'string' ? data.result : '指令已提交，运行结果见设备事件与真实反馈。',!!data.result?.ignored);
      showResult(data.result);
      await pollState();
      return data.result;
    } catch (error) { notify(`操作未完成：${error.message}`, true); return null; }
    finally { if (button) button.disabled = false; }
  }
  async function startMode(mode, options = {}, button) {
    await action('mode', {mode,options}, button);
  }
  function bind(id, callback) { const target = $(id); if (target) target.onclick = () => callback(target); }
  function number(id) { const value = Number($(id).value); if (!Number.isFinite(value)) throw new Error('请输入有效数字'); return value; }
  function panel(html) { $('experiment-panel').innerHTML = html; }
  function buttons(mode, description, extra = '') {
    panel(`<h3>开始实验</h3><p>${description}</p>${extra}<div class="field-row"><button class="primary" id="start-mode">启动实验</button><button id="pause-mode">停止并回到手动</button></div><div id="panel-status" class="panel-status"></div>`);
    bind('start-mode', button => startMode(mode, {}, button));
    bind('pause-mode', button => startMode('manual', {}, button));
  }
  function capabilityText(id) {
    const info = state.demo_status?.[id];
    const value = state.capabilities?.[id==='panorama'?'stitch':id];
    if(['gesture','rps'].includes(id)&&!state.capabilities?.host_worker)return info?.message || '需启动手势 worker';
    if(['voice','clap'].includes(id)&&(value===undefined||value===false||value?.available===false))return value?.reason || value?.error || info?.message || '需启动音频 worker';
    if (typeof value === 'string') return value;
    if (value === false || value?.available === false) return value?.reason || value?.error || '依赖或硬件待准备';
    if(id==='foam')return '正在开发 · 黑块检测可测试';
    if(id==='imu')return '硬件待接入 · 支持模拟输入';
    if (typeof info === 'string') return info;
    if (value === true || value?.available) return (value?.backend?value.backend+' · ':'')+(info?.message||'能力已就绪 · 待现场验收');
    if (info?.message) return info.message;
    if (info?.status) return info.status;
    return '等待设备能力检查';
  }
  function renderCards() {
    const query = $('search').value.trim().toLowerCase();
    $('project-grid').replaceChildren();
    const visible = PROJECTS.filter(project => (filter === 'all' || filter === project.category) && `${project.title} ${project.description} ${project.tag}`.toLowerCase().includes(query));
    $('no-results').hidden = visible.length > 0;
    for (const project of visible) {
      const card = node('button', undefined, `project-card ${project.category}${selected?.id === project.id ? ' selected' : ''}`);
      card.dataset.project = project.id;
      const top = node('div',undefined,'card-top');
      top.append(node('span',project.icon,'project-icon'),node('span',String(project.index).padStart(2,'0')+' / 18','project-number'));
      const bottom = node('div',undefined,'card-bottom');
      const status = node('span',capabilityText(project.id),'card-status');
      if (['foam','imu'].includes(project.id) || state.capabilities?.[project.id] === false) status.classList.add('pending');
      bottom.append(node('span',project.tag),node('span','↗','card-arrow'));
      card.append(top,node('h3',project.title),node('p',project.description),status,bottom);
      card.onclick = () => selectProject(project);
      $('project-grid').append(card);
    }
  }
  // Stop the previous experiment first. Clicks during the stop converge on the latest requested panel.
  async function selectProject(project) {
    requestedProject = project;
    if (switchingProject) return;
    switchingProject = true;
    try {
      if (state.running || (state.mode && state.mode !== 'manual')) {
        notify('正在停止上一个实验…');
        if (await action('stop') === null) return;
      }
      const next = requestedProject;
      selected = next;
      $('experiment-title').textContent = next.title;
      $('experiment-description').textContent = next.description;
      $('results').replaceChildren();
      delete $('results').dataset.image;
      $('video-frame').classList.toggle('selecting',next.id === 'track');
      $('selection-hint').textContent = next.id === 'track' ? '在画面上拖动框选，再启动跟踪' : '识别框来自实际推理';
      lastProgramNames = '';
      renderPanel(next.id);
      const help = node('a','↗ 查看本项目的操作与验收手册','inline-link');
      help.href = `/manuals/acceptance/${String(next.index).padStart(2,'0')}-${next.id}.md`;
      help.target = '_blank'; help.rel = 'noopener';
      const helpRow = node('div',undefined,'field-row'); helpRow.append(help);
      $('experiment-panel').append(helpRow);
      renderCards(); updatePanelStatus();
      document.querySelector('.workspace').scrollIntoView({behavior:'smooth',block:'start'});
    } finally {
      switchingProject = false;
      requestedProject = null;
    }
  }
  function renderPanel(id) {
    if (id === 'face') {
      buttons('face','在画面中站定，观察检测框。可选择只识别、水平跟随，或搜索后致意。',`<div class="field-row"><label for="face-behavior">行为</label><select id="face-behavior"><option value="greet">寻找并致意</option><option value="follow">跟随观众</option><option value="detect">只识别</option></select></div>`);
      bind('start-mode', button => startMode('face',{motion:$('face-behavior').value!=='detect',greet:$('face-behavior').value==='greet'},button));
    } else if (id === 'color') {
      buttons('color','用鲜艳、颜色一致的卡片测试；背景尽量不要出现同色物品。',`<div class="field-row"><label for="target-color">目标颜色</label><select id="target-color"><option value="red">红色</option><option value="green">绿色</option><option value="blue">蓝色</option><option value="yellow">黄色</option></select><select id="color-motion" aria-label="颜色跟随选项"><option value="follow">水平跟随</option><option value="detect">只识别</option></select></div>`);
      bind('start-mode', button => startMode('color',{color:$('target-color').value,motion:$('color-motion').value === 'follow'},button));
    } else if (['gesture','objects','markers','clap'].includes(id)) {
      const descriptions = {gesture:'先确保手部模型已安装。将完整手掌放在画面中；识别状态由设备返回。',objects:'先确保物品模型已安装，使用模型支持的演示类别；置信度是模型输出。',markers:'使用 ArUco 4×4 / 50 字典打印标记，将其正面朝向摄像头。',clap:'先确保音频设备可用。拍一次手，观察声音事件与动作回应。'};
      buttons(id,descriptions[id]);
      if (id === 'clap') {
        const row = node('div',undefined,'field-row'); const test = node('button','发送一次明确的拍手测试事件');
        test.onclick = () => action('clap',{},test); row.append(test); $('experiment-panel').append(row);
      }
    } else if (id === 'voice') {
      buttons('voice','连接麦克风并安装离线中文模型后，可采集真实口令；文字入口用于独立验证口令到动作。',`<div class="field-row"><input class="grow" id="speech-text" value="找人" aria-label="语音文字测试口令"><button id="speech-send">执行文字口令</button></div>`);
      bind('speech-send',button => action('speech',{text:$('speech-text').value},button));
    } else if (id === 'rps') {
      buttons('rps','摄像头猜拳需要手部模型。下面的按钮是手动注入的调试输入，可独立测试胜负规则。',`<div class="field-row"><span class="tag">手动注入 / 调试</span><button id="rps-rock">✊ 石头</button><button id="rps-paper">✋ 布</button><button id="rps-scissors">✌ 剪刀</button></div>`);
      for (const [name,gesture] of Object.entries({rock:'fist',paper:'open',scissors:'victory'})) bind(`rps-${name}`,button => action('gesture',{gesture},button));
    } else if (id === 'teach') {
      panel('<h3>教它记住动作</h3><p>先用右侧控制调好姿态，再记录当前真实关节角度。同一个名称可以连续追加多个姿态。</p><div class="field-row"><input class="grow" id="record-name" value="我的第一支舞" aria-label="动作名称"><button class="primary" id="record-pose">记录当前姿态</button></div><div class="field-row"><select class="grow" id="saved-programs" aria-label="已保存动作"></select><button id="play-recording">回放</button><button id="load-recording">载入积木编辑</button><button id="delete-recording">删除</button></div><div id="panel-status" class="panel-status"></div>');
      bind('record-pose',button => action('record',{name:$('record-name').value.trim()},button));
      bind('play-recording',button => action('program_run',{name:$('saved-programs').value},button));
      bind('load-recording',() => { steps = structuredClone((state.programs || []).find(program => program.name === $('saved-programs').value)?.steps || []); programDirty = true; selectProject(PROJECTS.find(project => project.id === 'program')); });
      bind('delete-recording',button => action('program_delete',{name:$('saved-programs').value},button));
      updatePrograms();
    } else if (id === 'program') renderProgram();
    else if (id === 'track') {
      panel('<h3>选中你的目标</h3><p>在视频中拖动，画出一个包含目标的矩形。先使用静止背景、短时间跟踪；匹配分数是图像相关度，目标丢失会显示真实状态。</p><div class="field-row"><button class="primary" id="track-start">跟踪选中目标</button><button id="track-stop">停止跟踪</button></div><div id="panel-status" class="panel-status"></div>');
      bind('track-start',button => { if (!selection) return notify('请先在实时画面上框选目标。',true); action('track_target',{box:selection},button); });
      bind('track-stop',button => startMode('manual',{},button));
    } else if (id === 'panorama') {
      panel('<h3>拍摄一个宽幅视野</h3><p>从小扇区开始：停稳拍摄后使用真实照片拼接。请先检查扫描范围的障碍与线缆。</p><div class="field-row"><label>起点 ° <input class="short" type="number" id="pan-start" value="-20" min="-180" max="180"></label><label>终点 ° <input class="short" type="number" id="pan-end" value="20" min="-180" max="180"></label><label>步长 ° <input class="short" type="number" id="pan-step" value="10" min="5" max="45"></label><button class="primary" id="panorama-run">拍摄并拼接</button></div><div id="panel-status" class="panel-status"></div>');
      bind('panorama-run',button => action('panorama',{start:number('pan-start'),end:number('pan-end'),step:number('pan-step')},button));
    } else if (id === 'difference') {
      panel('<h3>哪里发生了变化？</h3><p>保持相机和机械臂姿态不变。拍下第一张照片，移动桌面物品，再比较第二张照片。</p><div class="field-row"><button class="primary" id="difference-reference">① 拍下基准照片</button><button id="difference-compare">② 拍照并比较</button></div><div id="panel-status" class="panel-status"></div>');
      bind('difference-reference',button => action('difference_capture',{},button));
      bind('difference-compare',button => action('difference_compare',{},button));
    } else if (id === 'digital') {
      panel('<h3>同一台机械臂，两个视角</h3><p>右侧模型通过真实关节反馈计算各连杆的空间坐标，再做三维透视投影。拖动模型改变观察方向，实体机械臂不会因此运动。</p><div class="field-row"><button id="model-reset">重置三维视角</button><button id="raw-toggle">查看原始反馈</button></div><pre id="raw-state" class="code-preview" hidden></pre><div id="panel-status" class="panel-status"></div>');
      bind('model-reset',() => { cameraYaw=.75;cameraPitch=.32;drawRobot(); });
      bind('raw-toggle',() => { $('raw-state').hidden=!$('raw-state').hidden; $('raw-state').textContent=JSON.stringify(state.arm?.raw || {},null,2); });
    } else if (id === 'director') {
      panel('<h3>把一句话编成动作</h3><p>先生成动作预览，再明确执行。模型由上位机或板端本地服务提供；服务不可用时会显示失败原因。</p><textarea id="director-text" aria-label="导演指令">先看看左边，再回到中间，最后亮灯打招呼。</textarea><div class="field-row"><button class="primary" id="director-plan">生成动作预览</button><button id="director-execute" disabled>执行预览动作</button></div><pre id="director-preview" class="code-preview">等待生成…</pre><div id="panel-status" class="panel-status"></div>');
      bind('director-plan',async button => { directorSteps=[]; $('director-execute').disabled=true; const result=await action('director',{text:$('director-text').value},button); directorSteps=result?.steps || []; $('director-preview').textContent=result ? JSON.stringify(result,null,2) : '生成失败，请查看运行信息'; $('director-execute').disabled=!directorSteps.length; });
      bind('director-execute',button => action('director_run',{steps:directorSteps},button));
    } else if (id === 'agent') {
      panel('<h3>现场改规则挑战</h3><p>请在开发机的 Codex 中提出需求，由 Agent 修改代码、验证并部署。这个入口提供实验线索与验收标准。</p><ol class="checklist"><li>提出一个具体改动：例如“把颜色跟随默认值改成蓝色”。</li><li>让 Agent 找到对应配置或规则，解释将修改的位置。</li><li>检查改动，运行独立测试，再部署到设备。</li><li>用真实卡片、口令或动作验证结果，记录通过或失败。</li></ol><pre class="code-preview">示例需求：\n“让张手手势只亮灯，不移动夹爪。\n请同步修改验收手册并说明实测结果。”</pre><p class="subtle">入口不包含嵌入式 Agent 或云模型调用。</p><div id="panel-status" class="panel-status"></div>');
    } else if (id === 'foam') {
      buttons('foam','正在开发：黑块检测只提供候选。人工示教适用于固定物体位置；记录接近姿态前，请现场摆好泡沫并确认空间。尚未实现任意图像像素到三维抓取。');
      $('start-mode').textContent='启动黑块检测';
      const calibration = node('div',undefined,'field-row');
      for (const [stage,label] of Object.entries({observe:'记录观察姿态',approach:'记录接近姿态',lift:'记录抬起姿态'})) {
        const button = node('button',label);
        button.onclick = () => action('grasp_calibrate',{stage},button);
        calibration.append(button);
      }
      const attempt = node('div',undefined,'field-row');
      const run = node('button','尝试定点抓取','primary'); run.id='grasp-run'; run.disabled=true;
      const poses = node('span',undefined,'panel-status'); poses.id='grasp-poses';
      run.onclick = async () => { graspBusy=true;updatePanelStatus();await action('grasp');graspBusy=false;updatePanelStatus(); };
      attempt.append(run,poses);
      $('experiment-panel').append(calibration,attempt);
    } else if (id === 'imu') {
      panel('<h3>姿态映射与校准</h3><p>外部 ESP32＋IMU 尚需接入。滑块发送明确标注的模拟姿态输入；启用随动后会控制真实机械臂。</p><div class="field-row"><label for="imu-yaw">左右 °</label><input id="imu-yaw" type="range" min="-45" max="45" value="0"><output id="imu-yaw-value">0</output></div><div class="field-row"><label for="imu-pitch">俯仰 °</label><input id="imu-pitch" type="range" min="-20" max="20" value="0"><output id="imu-pitch-value">0</output></div><div class="field-row"><button id="imu-calibrate">设为中立姿态</button><button class="primary" id="imu-input">发送模拟姿态</button><button id="imu-follow">启用真实随动</button><button id="imu-stop">停止随动</button></div><div id="panel-status" class="panel-status"></div>');
      for (const axis of ['yaw','pitch']) $(`imu-${axis}`).oninput=()=>{$(`imu-${axis}-value`).value=$(`imu-${axis}`).value;};
      bind('imu-input',button=>action('imu',{yaw:number('imu-yaw'),pitch:number('imu-pitch'),simulated:true},button));
      bind('imu-calibrate',button=>action('imu_calibrate',{},button));
      bind('imu-follow',button=>startMode('imu',{},button));
      bind('imu-stop',button=>startMode('manual',{},button));
    }
  }

  function stepLabel(step) {
    if (step.type==='joint') return `${JOINTS[step.joint] || step.joint} → ${step.angle ?? (String(step.delta)+' 增量')}°`;
    if (step.type==='pose') return '回到已记录的四关节姿态';
    if (step.type==='wait') return `等待 ${step.seconds} 秒`;
    if (step.type==='led') return `灯光亮度 ${step.value}`;
    if (step.type==='repeat') return `重复 ${step.count} 次：${step.steps.map(stepLabel).join(' → ')}`;
    if (step.type==='if') return `如果发现 ${({face:'人脸',color:'颜色',marker:'标记'})[step.condition]}：${step.steps.map(stepLabel).join(' → ')}`;
    return step.type==='greet' ? '点头致意' : JSON.stringify(step);
  }
  function renderProgram() {
    panel('<h3>搭一个动作程序</h3><p>逐步添加积木，再用“重复”或“如果”包住已有步骤。执行时可随时点击顶部停止。</p><div class="field-row"><select id="block-kind" aria-label="积木类型"><option value="joint">关节到角度</option><option value="led">灯光亮度</option><option value="wait">等待秒数</option><option value="greet">点头致意</option></select><select id="block-joint" aria-label="积木关节"><option value="base">底座</option><option value="shoulder">肩部</option><option value="elbow">肘部</option><option value="gripper">夹爪</option></select><input class="short" id="block-value" type="number" value="10" aria-label="积木数值"><button id="block-add">＋ 添加积木</button></div><div class="field-row"><input class="short" id="repeat-count" type="number" value="2" min="1" max="10" aria-label="重复次数"><button id="block-repeat">全部重复</button><select id="block-condition" aria-label="积木条件"><option value="face">发现人脸</option><option value="color">发现颜色</option><option value="marker">发现标记</option></select><button id="block-if">包进条件</button><button id="block-clear">清空</button></div><div id="block-list"></div><div class="field-row"><input class="grow" id="program-name" value="我的积木程序" aria-label="程序名称"><button id="program-save">保存程序</button><button class="primary" id="program-run">执行当前程序</button></div><div class="field-row"><select class="grow" id="saved-programs" aria-label="已保存程序"></select><button id="program-load">载入程序</button></div><div id="panel-status" class="panel-status"></div>');
    bind('block-add',()=> { const type=$('block-kind').value; const value=number('block-value'); steps.push(type==='joint'?{type,joint:$('block-joint').value,angle:value}:type==='led'?{type,value}:type==='wait'?{type,seconds:value}:{type});programDirty=true;renderSteps(); });
    bind('block-repeat',()=>{if(!steps.length)return notify('请先添加积木。',true); steps=[{type:'repeat',count:number('repeat-count'),steps:structuredClone(steps)}];programDirty=true;renderSteps();});
    bind('block-if',()=>{if(!steps.length)return notify('请先添加积木。',true); steps=[{type:'if',condition:$('block-condition').value,steps:structuredClone(steps)}];programDirty=true;renderSteps();});
    bind('block-clear',()=>{steps=[];programDirty=true;renderSteps();});
    bind('program-save',async button=>{const result=await action('program_save',{name:$('program-name').value.trim(),steps},button);if(result!==null)programDirty=false;});
    bind('program-run',button=>action('program_run',{steps},button));
    bind('program-load',()=>{const program=(state.programs||[]).find(item=>item.name===$('saved-programs').value);if(program){steps=structuredClone(program.steps);$('program-name').value=program.name;programDirty=false;renderSteps();}});
    renderSteps();updatePrograms();
  }
  function renderSteps() {
    if (!$('block-list')) return;
    $('block-list').replaceChildren();
    steps.forEach((step,index)=>{
      const row=node('div',undefined,'program-step'); row.append(node('span',`${index+1}. ${stepLabel(step)}`));
      for (const [label,change] of [['↑',-1],['↓',1],['×',0]]) {
        const button=node('button',label); button.setAttribute('aria-label',change===0?'移除积木':change<0?'上移积木':'下移积木');
        button.onclick=()=>{if(change===0)steps.splice(index,1);else{const other=index+change;if(other>=0&&other<steps.length)[steps[index],steps[other]]=[steps[other],steps[index]];}programDirty=true;renderSteps();};row.append(button);
      } $('block-list').append(row);
    });
    if(!steps.length)$('block-list').append(node('p','还没有积木，先添加一个灯光或关节动作。','subtle'));
  }
  function updatePrograms() {
    if (!$('saved-programs')) return;
    const programs=state.programs||[];const signature=JSON.stringify(programs.map(program=>program.name));
    if(signature===lastProgramNames)return;
    const previous=$('saved-programs').value; $('saved-programs').replaceChildren();
    for(const program of programs){const option=node('option',program.name);option.value=program.name;$('saved-programs').append(option);}
    if(!programs.length){const option=node('option','尚无已保存程序');option.value='';$('saved-programs').append(option);}
    else if(programs.some(program=>program.name===previous))$('saved-programs').value=previous;
    lastProgramNames=signature;
  }
  function updatePanelStatus() {
    if(!selected)return;
    const message=capabilityText(selected.id);
    $('demo-state').textContent=message;
    $('demo-state').className='status-pill'+(['foam','imu'].includes(selected.id)?' warning':'');
    if($('panel-status')) {
      const extra=selected.id==='voice'?{worker:state.workers?.speech||{},recognition:state.voice}:selected.id==='clap'?state.workers?.clap:selected.id==='imu'?state.imu:selected.id==='director'?state.director:selected.id==='panorama'?state.panorama:selected.id==='difference'?state.difference:['gesture','rps'].includes(selected.id)?state.host:null;
      $('panel-status').textContent=message+(extra?'\n'+JSON.stringify(extra):'');
      if (selected.id==='foam' && state.grasp?.message) $('panel-status').textContent=message+'\n'+state.grasp.message;
    }
    if ($('grasp-run')) {
      const poses = state.grasp?.poses || {};
      $('grasp-run').disabled=graspBusy || !!state.running || !['observe','approach','lift'].every(stage=>poses[stage]);
      $('grasp-poses').textContent=Object.entries({observe:'观察',approach:'接近',lift:'抬起'}).map(([stage,label])=>`${label} ${poses[stage]?'✓':'待记录'}`).join(' · ');
    }
    if($('raw-state')&&!$('raw-state').hidden)$('raw-state').textContent=JSON.stringify(state.arm?.raw||{},null,2);
    updatePrograms();
  }
  // Display only URLs generated by this local application, never HTML from the response.
  function showResult(result) {
    if(!result||typeof result!=='object')return;
    if(selected?.id==='rps'&&result.robot) notify(`你：${result.player || '—'} · 机器人：${result.robot} · 结果：${result.outcome || result.result || '—'}`);
    const images=result.images || (result.image?[result.image]:result.path?[result.path]:[]);
    if(!Array.isArray(images))return;
    for(const entry of images){const path=typeof entry==='string'?entry:entry.url||entry.path;if(!path||!/^\/artifacts\/[\w./-]+$/.test(path)||path.includes('..'))continue;const figure=node('figure');const image=node('img');image.src=path+'?t='+Date.now();image.alt=entry.label||'真实处理结果';figure.append(image,node('figcaption',entry.label||path.split('/').pop()));$('results').append(figure);}
  }

  async function pollState() {
    if(statePollBusy)return;
    statePollBusy=true;
    try {
      const response=await fetch('/api/state',{cache:'no-store',signal:AbortSignal.timeout(4000)});
      if(!response.ok)throw new Error(`HTTP ${response.status}`);
      state=await response.json(); online=true;
      $('connection').className='status-pill'+(state.arm?.connected?' online':' warning');
      $('connection').replaceChildren(node('i'),node('span',state.arm?.connected?'串口机械臂在线':'机械臂未连接'));
      if(state.arm?.error)$('connection').title=state.arm.error;
      $('mode-state').textContent=`模式：${state.mode||'—'}${state.running?' · 执行 '+state.job:''}${state.arm?.transport?' · '+state.arm.transport:''}`;
      for(const joint of Object.keys(JOINTS)){
        const value=state.arm?.joints?.[joint];$(`feedback-${joint}`).textContent=Number.isFinite(value)?value.toFixed(1)+'°':'—';
        if(document.activeElement!==$(`angle-${joint}`)&&Number.isFinite(value))$(`angle-${joint}`).value=value.toFixed(1);
      }
      const events=(state.events||[]).slice(-6).reverse();$('activity-feed').replaceChildren();
      if(!events.length)$('activity-feed').append(node('p','暂无设备事件。','subtle'));
      for(const event of events){const row=node('p',undefined,event.level==='error'?'event-error':'');row.append(node('time',eventTime(event.time)),node('span',event.message||''));$('activity-feed').append(row);}
      $('vision-stats').textContent=state.vision?.error?state.vision.error:state.vision?.elapsed_ms?`推理 ${Number(state.vision.elapsed_ms).toFixed(0)} ms`:'等待识别';
      updatePanelStatus();
      for(const card of document.querySelectorAll('[data-project]'))card.querySelector('.card-status').textContent=capabilityText(card.dataset.project);
      if(selected?.id==='panorama'){
        const panorama=state.panorama||{};
        const signature=JSON.stringify([panorama.image,panorama.sources]);
        if($('results').dataset.image!==signature){
          $('results').replaceChildren();
          if(panorama.image)showResult({image:{path:panorama.image,label:'实际拼接结果'}});
          else if(panorama.sources?.length)showResult({images:panorama.sources.map((path,index)=>({path,label:`原始分段照片 ${index+1} · 未拼接`}))});
          $('results').dataset.image=signature;
        }
      }
      drawOverlay();drawRobot();
    } catch(error) {
      online=false;state.arm={connected:false,joints:{},error:error.message};
      $('connection').className='status-pill error';$('connection').replaceChildren(node('i'),node('span','服务连接中断'));
      $('mode-state').textContent='模式：服务不可达';
      for(const joint of Object.keys(JOINTS))$(`feedback-${joint}`).textContent='—';
      drawRobot();drawOverlay();
    } finally { statePollBusy=false; }
  }
  // API event times are Unix seconds; tolerate ISO timestamps and milliseconds for imported events.
  function eventTime(value) {
    if (value === undefined || value === null || value === '') return '—';
    const numeric = Number(value);
    const date = Number.isFinite(numeric) ? new Date(numeric < 1e12 ? numeric*1000 : numeric) : new Date(value);
    return Number.isNaN(date.getTime()) ? '—' : date.toLocaleTimeString('zh-CN',{hour12:false,hour:'2-digit',minute:'2-digit',second:'2-digit'});
  }
  function resetVideo(){liveVideo=false;$('camera').removeAttribute('src');}
  async function pollCamera(){
    if(cameraPollBusy)return;cameraPollBusy=true;
    try{const response=await fetch('/status',{cache:'no-store',signal:AbortSignal.timeout(4000)});if(!response.ok)throw new Error('视频服务不可达');const status=await response.json();$('camera').hidden=!status.ready;$('camera-empty').hidden=!!status.ready;$('camera-state').textContent=status.ready?`实时 · ${status.width}×${status.height} · ${status.fps} FPS`:status.error||'摄像头未就绪';if(status.ready&&!liveVideo){$('camera').src='/stream.mjpg?t='+Date.now();liveVideo=true;}if(!status.ready)resetVideo();}catch(error){resetVideo();$('camera').hidden=true;$('camera-empty').hidden=false;$('camera-state').textContent=error.message;}finally{cameraPollBusy=false;}
  }

  function canvasSize(canvas){const box=canvas.getBoundingClientRect();const ratio=window.devicePixelRatio||1;canvas.width=Math.round(box.width*ratio);canvas.height=Math.round(box.height*ratio);const context=canvas.getContext('2d');context.scale(ratio,ratio);return {context,w:box.width,h:box.height};}
  // Letterboxing uses the same contain geometry as the image, keeping every normalized box aligned.
  function imageRect(w,h){const width=state.vision?.width||$('camera').naturalWidth||640;const height=state.vision?.height||$('camera').naturalHeight||480;const scale=Math.min(w/width,h/height);return{x:(w-width*scale)/2,y:(h-height*scale)/2,w:width*scale,h:height*scale};}
  function drawOverlay(){
    const{context:c,w,h}=canvasSize($('overlay'));
    const rect=imageRect(w,h);
    if(!online||!liveVideo)return;
    c.lineWidth=2;c.font='12px system-ui';
    const hostFresh=Number(state.host?.updated)>Date.now()/1000-3;
    const result=selected?.id==='difference'?state.difference:['gesture','rps'].includes(state.mode)?(hostFresh?state.host:null):state.vision;
    for(const detection of result?.detections||[]){
      if(![detection.x,detection.y,detection.w,detection.h].every(Number.isFinite))continue;
      const x=rect.x+detection.x*rect.w,y=rect.y+detection.y*rect.h;
      const translated={face:'人脸',tracked_target:'跟踪目标',changed:'变化区域',foam:'黑块'};
      const label=translated[detection.label]||detection.label||'目标';
      const showScore=Number.isFinite(detection.confidence)&&!String(result?.confidence_kind||'').includes('presence flag');
      const probability=state.mode==='objects';
      const text=label+(showScore?(probability?' '+Math.round(detection.confidence*100)+'%':' 分数 '+detection.confidence.toFixed(2)):'');
      c.strokeStyle=selected?.id==='difference'?'#ffce87':'#adeca7';
      c.strokeRect(x,y,detection.w*rect.w,detection.h*rect.h);
      const labelWidth=c.measureText(text).width+10;
      c.fillStyle='#173e31';c.fillRect(x,Math.max(0,y-21),labelWidth,21);
      c.fillStyle='#e5fadd';c.fillText(text,x+5,Math.max(15,y-6));
    }
    if(selection&&selected?.id==='track'){
      c.setLineDash([6,4]);c.strokeStyle='#ffcf87';
      c.strokeRect(rect.x+selection.x*rect.w,rect.y+selection.y*rect.h,selection.w*rect.w,selection.h*rect.h);
      c.setLineDash([]);
    }
  }
  function normalizedPoint(event){const bounds=$('overlay').getBoundingClientRect();const rect=imageRect(bounds.width,bounds.height);return{x:Math.max(0,Math.min(1,(event.clientX-bounds.left-rect.x)/rect.w)),y:Math.max(0,Math.min(1,(event.clientY-bounds.top-rect.y)/rect.h))};}
  $('overlay').onpointerdown=event=>{if(selected?.id!=='track'||!liveVideo)return;dragStart=normalizedPoint(event);selection=null;$('overlay').setPointerCapture(event.pointerId);};
  $('overlay').onpointermove=event=>{if(!dragStart)return;const current=normalizedPoint(event);selection={x:Math.min(dragStart.x,current.x),y:Math.min(dragStart.y,current.y),w:Math.abs(current.x-dragStart.x),h:Math.abs(current.y-dragStart.y)};drawOverlay();};
  $('overlay').onpointerup=()=>{dragStart=null;if(selection&&(selection.w<.02||selection.h<.02)){selection=null;notify('框选范围太小，请重新框选。',true);}drawOverlay();};
  $('overlay').onpointercancel=()=>{dragStart=null;selection=null;drawOverlay();};

  // Forward kinematics -> camera rotation -> perspective projection. Unknown feedback draws only the stage.
  function drawRobot(){
    const{context:c,w,h}=canvasSize($('robot-view'));if(!w||!h)return;
    const project=([x,y,z])=>{const rx=x*Math.cos(cameraYaw)-y*Math.sin(cameraYaw),ry=x*Math.sin(cameraYaw)+y*Math.cos(cameraYaw);const depth=ry*Math.cos(cameraPitch)+z*Math.sin(cameraPitch);const vertical=z*Math.cos(cameraPitch)-ry*Math.sin(cameraPitch);const scale=450/(650+depth);return{x:w/2+rx*scale,y:h*.82-vertical*scale,depth};};
    const line=(a,b,color,width=1)=>{const p=project(a),q=project(b);c.strokeStyle=color;c.lineWidth=width;c.lineCap='round';c.beginPath();c.moveTo(p.x,p.y);c.lineTo(q.x,q.y);c.stroke();};
    for(let i=-3;i<=3;i++){line([i*45,-135,0],[i*45,135,0],'#dce3d7');line([-135,i*45,0],[135,i*45,0],'#dce3d7');}
    line([0,0,0],[80,0,0],'#cf8370',2);line([0,0,0],[0,80,0],'#89ac76',2);
    const joints=state.arm?.joints||{};
    if(!online||!state.arm?.connected||!Object.keys(JOINTS).every(key=>Number.isFinite(joints[key]))){c.fillStyle='#768b7e';c.font='12px system-ui';c.textAlign='center';c.fillText('等待真实关节反馈',w/2,h*.42);return;}
    // Manufacturer FK: forearm elevation = pi/2 - (elbow + shoulder); e=90° is horizontal.
    const rad=Math.PI/180,base=joints.base*rad,shoulder=(90-joints.shoulder)*rad;
    const elbow=(90-joints.shoulder-joints.elbow)*rad;
    const spatial=(r,z)=>[r*Math.cos(base),r*Math.sin(base),z];
    const points=[[0,0,0],[0,0,24],spatial(120*Math.cos(shoulder),24+120*Math.sin(shoulder)),spatial(120*Math.cos(shoulder)+110*Math.cos(elbow),24+120*Math.sin(shoulder)+110*Math.sin(elbow))];
    const foot=project(points[0]);c.fillStyle='#c8d4bf';c.beginPath();c.ellipse(foot.x,foot.y,36,12,0,0,Math.PI*2);c.fill();
    for(let i=0;i<points.length-1;i++){line(points[i],points[i+1],'#234b43',i===0?22:13);line(points[i],points[i+1],'#759783',i===0?12:5);}
    for(const point of points.slice(1)){const p=project(point);c.beginPath();c.arc(p.x,p.y,8,0,2*Math.PI);c.fillStyle='#e1e7d8';c.fill();c.strokeStyle='#355b4f';c.lineWidth=3;c.stroke();}
    const end=points[3],opening=Math.max(3,Math.min(22,(180-joints.gripper)*.16+3));const across=[-Math.sin(base),Math.cos(base),0];
    for(const direction of [-1,1]){const start=end.map((value,index)=>value+across[index]*direction*7);const tip=start.map((value,index)=>value+across[index]*direction*opening+(index===2?17:0));line(start,tip,'#dc8850',5);}
  }
  $('robot-view').onpointerdown=event=>{modelDrag={x:event.clientX,y:event.clientY};$('robot-view').setPointerCapture(event.pointerId);};
  $('robot-view').onpointermove=event=>{if(!modelDrag)return;cameraYaw+=(event.clientX-modelDrag.x)*.012;cameraPitch=Math.max(-.2,Math.min(1.1,cameraPitch+(event.clientY-modelDrag.y)*.01));modelDrag={x:event.clientX,y:event.clientY};drawRobot();};
  $('robot-view').onpointerup=$('robot-view').onpointercancel=()=>{modelDrag=null;};

  for(const [joint,label] of Object.entries(JOINTS)){
    const summary=node('div');const value=node('strong','—');value.id=`feedback-${joint}`;summary.append(node('span',label),value);$('joint-summary').append(summary);
    const row=node('div',undefined,'joint-control');const title=node('label',label);title.htmlFor=`angle-${joint}`;const input=node('input');input.id=`angle-${joint}`;input.type='number';input.step='1';input.setAttribute('aria-label',`${label}目标角度`);const minus=node('button','−');const plus=node('button','＋');minus.setAttribute('aria-label',`${label}减小5度`);plus.setAttribute('aria-label',`${label}增大5度`);const go=node('button','到位');minus.onclick=()=>action('joint',{joint,delta:-5},minus);plus.onclick=()=>action('joint',{joint,delta:5},plus);go.onclick=()=>action('joint',{joint,angle:number(input.id)},go);row.append(title,minus,input,node('span','°','unit'),plus,go);$('joint-controls').append(row);
  }
  bind('stop',button=>action('stop',{},button));bind('home',button=>action('home',{},button));bind('led-send',button=>action('led',{value:number('led')},button));bind('reconnect',()=>{resetVideo();pollCamera();});
  $('camera').onerror=()=>{resetVideo();$('camera').hidden=true;$('camera-empty').hidden=false;};
  for(const button of document.querySelectorAll('[data-filter]'))button.onclick=()=>{filter=button.dataset.filter;for(const item of document.querySelectorAll('[data-filter]'))item.classList.toggle('active',item===button);renderCards();};
  $('search').oninput=renderCards;
  // Best-effort stop for leaving the console, using keepalive because pagehide may end ordinary requests.
  function leaveStop(){if(!online)return;fetch('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(actionPacket('stop')),keepalive:true}).catch(()=>{});}
  window.addEventListener('pagehide',leaveStop);document.addEventListener('visibilitychange',()=>{if(document.hidden)leaveStop();});
  window.addEventListener('resize',()=>{drawOverlay();drawRobot();});
  window.addEventListener('beforeunload',event=>{if(programDirty){event.preventDefault();event.returnValue='';}});
  renderCards();drawRobot();pollState();pollCamera();setInterval(pollState,1200);setInterval(pollCamera,2500);
})();
