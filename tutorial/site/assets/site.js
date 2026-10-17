/* Shared site behavior: course map, TOC scroll-spy, labs, quiz. */
(function () {
  'use strict';

  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };

  /* ---------- course map (index) ---------- */
  function buildMap() {
    var host = $('#map');
    if (!host || !window.COURSE) return;
    var parts = window.COURSE.parts;
    var html = '';
    parts.forEach(function (p) {
      var items = window.COURSE.chapters.filter(function (c) { return c.part === p[0]; });
      if (!items.length) return;
      html += '<div class="map-head"><span>' + p[0] + '</span><em>' + p[1] + '</em></div>';
      items.forEach(function (c) {
        html += '<a class="chap" href="chapters/' + c.slug + '.html">'
          + '<span class="part">' + (c.star ? '● 核心' : '○ 选读') + '</span>'
          + '<span class="no">' + c.label.replace(/[^0-9A-Z]/g, '') + '</span>'
          + '<h3>' + c.label + '</h3><p>' + c.blurb + '</p></a>';
      });
    });
    host.innerHTML = html;
  }

  /* ---------- TOC highlight ---------- */
  function buildSpy() {
    var links = $$('.toc a');
    if (!links.length) return;
    var heads = links.map(function (a) { return document.getElementById(a.getAttribute('href').slice(1)); });
    var current = -1;
    function update() {
      var best = 0;
      heads.forEach(function (h, i) {
        if (h && h.getBoundingClientRect().top <= 140) best = i;
      });
      if (best !== current) {
        if (current >= 0) links[current].classList.remove('active');
        links[best].classList.add('active');
        current = best;
      }
    }
    window.addEventListener('scroll', update, { passive: true });
    update();
  }

  /* ---------- lab: tokenizer ---------- */
  function labTokens() {
    var input = $('#tok-input');
    if (!input) return;
    var out = $('#tok-out'), stat = $('#tok-stat');
    var priceIn = $('#price-in'), priceOut = $('#price-out'), reply = $('#reply-len');

    function tokenize(text) {
      var toks = [];
      var buf = '';
      for (var i = 0; i < text.length; i++) {
        var ch = text[i];
        if (/[一-鿿　-〿＀-￯]/.test(ch)) {
          if (buf) { toks.push(buf); buf = ''; }
          toks.push(ch);
        } else if (/\s/.test(ch)) {
          if (buf) { toks.push(buf); buf = ''; }
          toks.push(ch);
        } else if (/[A-Za-z0-9]/.test(ch)) {
          buf += ch;
          if (buf.length >= 4) { toks.push(buf); buf = ''; }
        } else {
          if (buf) { toks.push(buf); buf = ''; }
          toks.push(ch);
        }
      }
      if (buf) toks.push(buf);
      return toks;
    }

    function run() {
      var toks = tokenize(input.value || '');
      out.innerHTML = toks.map(function (t) {
        var ai = /[一-鿿]/.test(t) ? '' : ' ai-tok';
        return '<span class="tok' + ai + '">' + (t === '\n' ? '↵' : t.replace(/ /g, '␣')) + '</span>';
      }).join('');
      var n = toks.length;
      var replyN = Math.max(0, parseInt(reply.value, 10) || 0);
      var pin = parseFloat(priceIn.value) || 0, pout = parseFloat(priceOut.value) || 0;
      var cost = n * pin / 1e6 + replyN * pout / 1e6;
      stat.textContent = '共 ' + n + ' 个 token（含空白与标点）；'
        + '一次调用约 ' + n + ' 输入 + ' + replyN + ' 输出；'
        + '按你填的单价合计约 ' + cost.toFixed(4) + ' 元。\n'
        + '同一句话问 30 个学生各 1 次，就是上面数字的 30 倍。';
    }
    input.addEventListener('input', run);
    [priceIn, priceOut, reply].forEach(function (el) { el.addEventListener('input', run); });
    run();
  }

  /* ---------- lab: gradient descent ---------- */
  function labGradient() {
    var canvas = $('#gd-canvas');
    if (!canvas) return;
    var ctx = canvas.getContext('2d');
    var lrEl = $('#gd-lr'), startEl = $('#gd-start'), info = $('#gd-info');
    var x = 0, path = [], running = false, timer = null;
    var lrVal = $('#gd-lr-val');
    function showLr() { if (lrVal) lrVal.textContent = '= ' + parseFloat(lrEl.value).toFixed(2); }
    showLr();

    // Loss surface: one global valley plus a local dip; optimum near x = 2.54.
    function loss(x) { return 2.7 + 0.55 * Math.sin(1.9 * (x - 0.1)) + 0.30 * Math.pow(x - 2.4, 2); }
    function grad(x) { return 1.045 * Math.cos(1.9 * (x - 0.1)) + 0.60 * (x - 2.4); }

    function draw() {
      var w = canvas.width, h = canvas.height;
      ctx.clearRect(0, 0, w, h);
      var xmin = -1, xmax = 5.5, ymin = 2, ymax = 6;
      var px = function (v) { return 40 + (v - xmin) / (xmax - xmin) * (w - 70); };
      var py = function (v) { return h - 40 - (v - ymin) / (ymax - ymin) * (h - 70); };

      ctx.strokeStyle = '#d9cfbc'; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(40, h - 40); ctx.lineTo(w - 30, h - 40); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(40, 20); ctx.lineTo(40, h - 40); ctx.stroke();
      ctx.fillStyle = '#8b8273'; ctx.font = '11px monospace';
      ctx.fillText('参数值', w - 70, h - 18);
      ctx.save(); ctx.translate(14, 120); ctx.rotate(-Math.PI / 2); ctx.fillText('损失', 0, 0); ctx.restore();

      ctx.strokeStyle = '#2f5d50'; ctx.lineWidth = 2; ctx.beginPath();
      for (var i = 0; i <= 300; i++) {
        var v = xmin + (xmax - xmin) * i / 300;
        var y = loss(v);
        if (i === 0) ctx.moveTo(px(v), py(y)); else ctx.lineTo(px(v), py(y));
      }
      ctx.stroke();

      ctx.fillStyle = '#b4552d';
      path.forEach(function (p, i) {
        ctx.globalAlpha = 0.25 + 0.75 * (i / Math.max(1, path.length - 1));
        ctx.beginPath(); ctx.arc(px(p), py(loss(p)), i === path.length - 1 ? 5 : 3, 0, 6.3); ctx.fill();
      });
      ctx.globalAlpha = 1;
    }

    function reset() {
      clearInterval(timer); running = false;
      x = parseFloat(startEl.value);
      path = [x];
      info.textContent = '起点 x = ' + x.toFixed(2) + '，损失 = ' + loss(x).toFixed(3) + '。点"走一步"或"自动"。';
      draw();
    }

    function step() {
      var lr = parseFloat(lrEl.value);
      var g = grad(x);
      x = x - lr * g;
      x = Math.max(-1, Math.min(5.5, x));
      path.push(x);
      if (path.length > 60) path.shift();
      var stalled = Math.abs(g) < 0.01;
      info.textContent = 'x = ' + x.toFixed(3) + '，损失 = ' + loss(x).toFixed(3)
        + '，当前斜率 = ' + g.toFixed(3) + (stalled ? '（已接近平坦处）' : '');
      draw();
      if (stalled && running) { clearInterval(timer); running = false; }
    }

    $('#gd-step').addEventListener('click', step);
    $('#gd-reset').addEventListener('click', reset);
    $('#gd-auto').addEventListener('click', function () {
      if (running) { clearInterval(timer); running = false; return; }
      running = true;
      timer = setInterval(step, 220);
    });
    lrEl.addEventListener('input', showLr);
    lrEl.addEventListener('change', reset);
    startEl.addEventListener('change', reset);
    reset();
  }

  /* ---------- lab: attention ---------- */
  function labAttention() {
    var host = $('#att-grid');
    if (!host) return;
    var words = ['小猫', '坐在', '垫子', '上', '因为', '它', '很累'];
    // Illustrative weights, hand-authored to show pronoun resolution.
    var M = [
      [0.42, 0.18, 0.10, 0.04, 0.06, 0.12, 0.08],
      [0.30, 0.34, 0.16, 0.04, 0.05, 0.06, 0.05],
      [0.14, 0.10, 0.46, 0.10, 0.04, 0.10, 0.06],
      [0.08, 0.12, 0.36, 0.24, 0.06, 0.08, 0.06],
      [0.05, 0.04, 0.03, 0.02, 0.34, 0.12, 0.40],
      [0.08, 0.05, 0.10, 0.03, 0.22, 0.30, 0.22],
      [0.04, 0.03, 0.05, 0.02, 0.30, 0.16, 0.40]
    ];
    var rows = words.map(function (w, i) {
      var cells = M[i].map(function (v, j) {
        var a = v.toFixed(2);
        return '<span class="att-cell" data-r="' + i + '" data-c="' + j + '" style="background:rgba(180,85,45,'
          + (v * 1.9).toFixed(2) + ')" title="' + words[i] + ' → ' + words[j] + '：' + a + '">' + a + '</span>';
      }).join('');
      return '<div class="att-row"><span class="att-head">' + w + '</span>' + cells + '</div>';
    }).join('');
    host.innerHTML = '<div class="att-row att-top"><span class="att-head"></span>'
      + words.map(function (w) { return '<span class="att-head">' + w + '</span>'; }).join('') + '</div>' + rows;

    $$('.att-cell', host).forEach(function (c) {
      c.addEventListener('click', function () {
        $$('.att-cell', host).forEach(function (o) { o.classList.remove('hot'); });
        var r = +c.dataset.r;
        $$('.att-cell[data-r="' + r + '"]', host).forEach(function (o) { o.classList.add('hot'); });
        $('#att-out').textContent = '「' + words[r] + '」这一行在看：'
          + words.map(function (w, j) { return w + ' ' + M[r][j].toFixed(2); })
              .sort(function (a, b) { return parseFloat(b.split(' ').pop()) - parseFloat(a.split(' ').pop()); })
              .slice(0, 3).join('，')
          + '。\n注意「它」那一行最重的是「小猫」，不是最近出现的「垫子」。'
          + '这是统计上学会的指代倾向，不是逻辑推理。';
      });
    });
  }

  /* ---------- lab: context budget ---------- */
  function labContext() {
    var wrap = $('#ctx-bars');
    if (!wrap) return;
    var win = $('#ctx-window');
    var specs = [
      ['系统提示 / 项目规则', '#doc-sys', 400],
      ['任务说明', '#doc-task', 300],
      ['参考资料（检索）', '#doc-rag', 0],
      ['对话历史', '#doc-chat', 1200],
      ['代码与日志', '#doc-code', 800]
    ];
    var total = $('#ctx-total');

    function render() {
      var W = parseInt(win.value, 10) * 1000;
      var sum = 0;
      var html = '';
      specs.forEach(function (s) {
        var v = parseInt($(s[1]).value, 10);
        sum += v;
        var pct = Math.min(100, v / W * 100);
        html += '<div class="bar-row"><span class="bar-label">' + s[0] + '</span>'
          + '<span class="bar-track"><span class="bar-fill" style="width:' + pct.toFixed(1) + '%"></span></span>'
          + '<span class="bar-val">' + v.toLocaleString() + '</span></div>';
      });
      wrap.innerHTML = html;
      var ratio = sum / W;
      total.textContent = '合计 ' + sum.toLocaleString() + ' / ' + W.toLocaleString()
        + ' token（' + (ratio * 100).toFixed(0) + '%）。'
        + (ratio > 0.8 ? '\n已超过 80%：留给模型回答和工具输出的空间很少，' + '响应会变慢变贵，关键指令也更容易被冲淡。先删旧对话，而不是换更大的窗口。'
          : '\n还有余量。注意长会话里每一轮都会重新发送全部历史，费用按总量累加。');
      total.className = 'readout' + (ratio > 0.8 ? ' warn' : '');
    }
    $$('input[type=range]', wrap.parentNode).forEach(function (el) { el.addEventListener('input', render); });
    win.addEventListener('input', render);
    render();
  }

  /* ---------- lab: agent loop ---------- */
  function labAgent() {
    var btn = $('#agent-step');
    if (!btn) return;
    var log = $('#agent-log');
    var inject = $('#agent-inject');
    var steps = [
      ['观察', '读任务：把首页主色从米色改成墨绿。工具：读文件、改文件、跑测试。'],
      ['决策', '先定位颜色定义在哪。调用 search("--paper")。'],
      ['行动', '工具返回：assets/style.css 第 3 行。'],
      ['决策', '改这一行，然后跑构建确认没有语法错误。'],
      ['行动', '构建通过。但页面用了 4 处硬编码的浅色背景。'],
      ['检查', '只改一个变量会让页面半绿半米。需要一并替换，再截图确认。'],
      ['完成', '输出 diff、构建结果、截图。报告：改了 5 处，未处理深色模式。']
    ];
    var i = 0;
    function add(kind, text) {
      var p = document.createElement('div');
      p.className = 'agent-line ' + (kind === '行动' ? 'act' : kind === '检查' ? 'chk' : '');
      p.innerHTML = '<b>' + kind + '</b>' + text;
      log.appendChild(p);
      log.scrollTop = log.scrollHeight;
    }
    btn.addEventListener('click', function () {
      if (i >= steps.length) { log.innerHTML = ''; i = 0; btn.textContent = '走一步'; return; }
      add(steps[i][0], steps[i][1]);
      i++;
      if (inject.checked && i === 4) {
        add('故障注入', '假设 Agent 直接相信"构建通过 = 改对了"，跳过截图检查就宣布完成。页面实际半绿半米。');
        add('教训', '构建只证明文件能解析，不证明需求达成。检查步骤不能省。');
        i = steps.length;
      }
      if (i >= steps.length) btn.textContent = '重来';
    });
  }

  /* ---------- lab: quantization size ---------- */
  function labQuant() {
    var p = $('#q-params'), b = $('#q-bits'), out = $('#q-out');
    if (!p) return;
    function run() {
      var params = parseFloat(p.value);           // billions
      var bits = parseFloat(b.value);
      var gb = params * bits / 8;
      var kv = params * 0.00009 * (parseFloat($('#q-ctx').value) / 1000); // rough KV growth
      out.textContent = params.toFixed(1) + 'B 参数，按每权重 ' + bits + ' bit 估算：\n'
        + '权重约 ' + gb.toFixed(1) + ' GB（' + (gb * 1024).toFixed(0) + ' MiB）。\n'
        + '再加上上下文缓存（粗略）约 ' + kv.toFixed(1) + ' GB，总需求约 ' + (gb + kv).toFixed(1) + ' GB。\n'
        + (gb + kv > 8 ? '超过 8GB 显存：要么换更小的量化，要么走 CPU/内存，速度会明显下降。'
                       : '8GB 显存内大致放得下，但仍要留出系统和框架开销。');
    }
    [p, b, $('#q-ctx')].forEach(function (el) { el.addEventListener('input', run); });
    run();
  }

  /* ---------- quiz ---------- */
  var QUIZ = [
    ['“模型”“聊天产品”“API”“Agent”四个词的关系，最准确的是：',
     ['它们是同一个东西的不同叫法', '模型是参数与计算，产品是界面，API 是程序调用入口，Agent 是能调工具循环执行的那层', 'Agent 就是参数量更大的模型', 'API 是给模型训练用的'],
     1, '模型是底座；聊天产品是给人用的外壳；API 是给程序用的接口；Agent 是在模型之上加了工具、循环与约束的程序。'],
    ['关于 token，下面哪句是对的？',
     ['一个汉字永远等于一个 token', 'token 只用于英文', '中文、标点、JSON 符号都占 token，具体数目由分词器决定', 'token 数量与费用无关'],
     2, '不同模型的分词器不同，汉字常为 1–2 个 token，标点与格式符号同样计数。'],
    ['注意力机制的本质，最接近下面哪一种描述？',
     ['模型在逐字查字典', '模型按学到的相关性，给不同位置分配不同的权重来组合信息', '模型在运行一段 if-else 逻辑', '模型在联网搜索'],
     1, '注意力是加权组合，权重来自训练得到的相似度计算。它体现统计倾向，不是逻辑推理。'],
    ['模型“编造了一个不存在的引用”，这属于：',
     ['知识过时', '幻觉', '不遵守指令', '网络故障'],
     1, '输出流畅但与事实不符、且模型自身无法察觉，是幻觉的典型形态。'],
    ['上下文污染的典型症状是：',
     ['模型拒绝回答', '回答越来越慢但内容正确', '模型反复回到早先的错误方案，或忽略最新要求', '窗口自动清空'],
     2, '污染来自无关或错误信息占据了注意力。换新会话并交出一份干净的交接摘要通常最有效。'],
    ['“说得出 / 跑得通 / 测得过 / 现场看得见”四级验证里，自动化测试通过属于：',
     ['说得出', '跑得通', '测得过', '现场看得见'],
     2, '测试通过证明的是“在测试覆盖的条件下成立”，仍不等于真人和真实环境下的闭环。'],
    ['关于 API 与订阅，下面哪句正确？',
     ['订阅通常包含无限 API 调用', 'API 按用量计费，订阅一般只覆盖产品界面内的使用', 'API 比订阅一定便宜', '两者没有区别'],
     1, '订阅面向人使用产品，API 面向程序调用并按量计费，额度与价格以官方为准。'],
    ['让 Agent 改代码时，最不该省的一步是：',
     ['让它一次改完所有文件', '把上下文塞得越满越好', '改完自己跑测试并查看 diff', '让它顺便重构整个项目'],
     2, '一次一改、看 diff、跑测试，是把“它说改好了”变成“我能确认改好了”的唯一方式。'],
    ['量化（如 Q4）主要换来什么、代价是什么？',
     ['换来更高准确率，代价是更慢', '换来更小的体积与更低的显存占用，代价是精度可能略降', '换来更长上下文，代价是费用更高', '没有代价'],
     1, '量化用更少位数存权重；通常精度损失有限，但在难题、长推理上更容易暴露。'],
    ['子代理最核心的价值是：',
     ['让模型变聪明', '上下文隔离：失败尝试随子代理结束，不污染主对话', '可以跳过验证', '能自动部署到生产'],
     1, '隔离是它的主要收益；代价是它看不到主对话细节，所以派活要说全，结论要复核。'],
    ['“现场变化任务”在课程验收中的作用是：',
     ['考察记忆背诵', '验证项目真的改得动，而不是只有演示路径能跑', '增加作业量', '考察打字速度'],
     1, '临时改动会暴露硬编码、耦合与缺失的测试，是“能不能维护”的最快检验。'],
    ['关于 AI 与人的分工，课程给出的立场是：',
     ['AI 负责判断，人负责执行', '人是路由器：决定交给谁、给多少上下文、信不信、停不停', '人只需要写提示词', '全部交给 Agent 即可'],
     1, '选对问题与判断“做完了没有”无法外包，因为外包的前提是你能验收。']
  ];

  function buildQuiz() {
    var host = $('#quiz');
    if (!host) return;
    var answered = 0, right = 0;
    QUIZ.forEach(function (q, qi) {
      var div = document.createElement('div');
      div.className = 'quiz-q';
      var opts = q[1].map(function (o, oi) {
        return '<button class="opt" data-q="' + qi + '" data-o="' + oi + '">' + o + '</button>';
      }).join('');
      div.innerHTML = '<div class="qtext">' + (qi + 1) + '. ' + q[0] + '</div>' + opts
        + '<div class="why"></div>';
      host.appendChild(div);
    });
    host.addEventListener('click', function (e) {
      var btn = e.target.closest('button.opt');
      if (!btn || btn.disabled) return;
      var qi = +btn.dataset.q, oi = +btn.dataset.o;
      var q = QUIZ[qi], box = btn.parentNode;
      var right_idx = q[2];
      $$('button.opt', box).forEach(function (b, i) {
        b.disabled = true;
        if (i === right_idx) b.classList.add('right');
      });
      if (oi !== right_idx) btn.classList.add('wrong');
      var why = $('.why', box);
      why.textContent = (oi === right_idx ? '对了。' : '不对。正确答案是：' + q[1][right_idx] + '。') + q[3];
      why.classList.add('show');
      answered++;
      if (oi === right_idx) right++;
      var score = $('#score');
      score.textContent = '已答 ' + answered + ' / ' + QUIZ.length + '，答对 ' + right + ' 题。';
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    buildMap();
    buildSpy();
    labTokens();
    labGradient();
    labAttention();
    labContext();
    labAgent();
    labQuant();
    buildQuiz();
  });
})();
