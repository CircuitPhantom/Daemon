/* Daemon promo site. Vanilla JS, no dependencies, no network requests. */
(function () {
  'use strict';
  var doc = document, root = doc.documentElement;
  var reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  var $ = function (s, el) { return (el || doc).querySelector(s); };
  var $$ = function (s, el) { return Array.prototype.slice.call((el || doc).querySelectorAll(s)); };

  /* ---------- Wireframe sphere (the dashboard's signature) ---------- */
  var sphere = (function () {
    var canvas = $('#sphere');
    if (!canvas || !canvas.getContext) return { pulse: function () {} };
    var ctx = canvas.getContext('2d');
    var N = 150, pts = [], edges = [], sparks = [];
    var golden = Math.PI * (3 - Math.sqrt(5));
    var seed = 7;
    function rnd() { seed = (seed * 16807) % 2147483647; return seed / 2147483647; }

    for (var i = 0; i < N; i++) {
      var y = 1 - 2 * (i + 0.5) / N, r = Math.sqrt(1 - y * y), th = i * golden + (rnd() - 0.5) * 0.5;
      y += (rnd() - 0.5) * 0.06;
      pts.push({ x: Math.cos(th) * r, y: y, z: Math.sin(th) * r, ph: rnd() * 6.28, sx: 0, sy: 0, d: 0 });
    }
    var seen = {};
    pts.forEach(function (p, a) {
      var near = pts.map(function (q, b) {
        var dx = p.x - q.x, dy = p.y - q.y, dz = p.z - q.z;
        return { b: b, d: dx * dx + dy * dy + dz * dz };
      }).sort(function (m, n) { return m.d - n.d; }).slice(1, 4);
      near.forEach(function (n) {
        var key = Math.min(a, n.b) + '-' + Math.max(a, n.b);
        if (seen[key] || rnd() < 0.22) return;   // drop a few so it looks hand-wired, like the dashboard
        seen[key] = 1; edges.push([a, n.b]);
      });
    });

    var w = 0, h = 0, dpr = 1, running = false, visible = true, raf = 0;
    var rotY = 0, tiltX = 0.25, tiltY = 0, aimX = 0.25, aimY = 0, energy = 0, last = 0, sparkAt = 0;

    function resize() {
      var rect = canvas.getBoundingClientRect();
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = rect.width; h = rect.height;
      canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      if (!running) draw(0);
    }

    function draw(t) {
      var R = Math.min(w, h) * 0.4, cx = w / 2, cy = h / 2;
      var cyR = Math.cos(rotY + tiltY), syR = Math.sin(rotY + tiltY), cxR = Math.cos(tiltX), sxR = Math.sin(tiltX);
      ctx.clearRect(0, 0, w, h);
      for (var i = 0; i < N; i++) {
        var p = pts[i];
        var k = 1 + Math.sin(t * 0.0011 + p.ph) * (0.025 + energy * 0.09);
        var x = p.x * k, y = p.y * k, z = p.z * k;
        var x1 = x * cyR + z * syR, z1 = -x * syR + z * cyR;
        var y1 = y * cxR - z1 * sxR, z2 = y * sxR + z1 * cxR;
        var s = 2.8 / (2.8 - z2);
        p.sx = cx + x1 * R * s; p.sy = cy + y1 * R * s; p.d = (z2 + 1) / 2;
      }
      ctx.lineWidth = 1;
      for (var e = 0; e < edges.length; e++) {
        var a = pts[edges[e][0]], b = pts[edges[e][1]];
        var d = (a.d + b.d) / 2, mix = Math.max(0, Math.min(1, (a.sx + b.sx) / 2 / w));
        var al = 0.05 + d * d * (0.4 + energy * 0.3);
        // purple on the left, blue on the right
        ctx.strokeStyle = 'rgba(' + Math.round(150 - 70 * mix) + ',' + Math.round(112 + 30 * mix) + ',255,' + al.toFixed(3) + ')';
        ctx.beginPath(); ctx.moveTo(a.sx, a.sy); ctx.lineTo(b.sx, b.sy); ctx.stroke();
      }
      for (var j = 0; j < N; j++) {
        var q = pts[j];
        ctx.fillStyle = 'rgba(205,198,255,' + (0.12 + q.d * 0.7).toFixed(3) + ')';
        ctx.beginPath(); ctx.arc(q.sx, q.sy, 0.7 + q.d * 1.3, 0, 6.2832); ctx.fill();
      }
      // signals travelling along the wires
      for (var n = sparks.length - 1; n >= 0; n--) {
        var sp = sparks[n]; sp.t += sp.v;
        if (sp.t >= 1) { sparks.splice(n, 1); continue; }
        var A = pts[edges[sp.e][0]], B = pts[edges[sp.e][1]];
        var px = A.sx + (B.sx - A.sx) * sp.t, py = A.sy + (B.sy - A.sy) * sp.t, dd = (A.d + B.d) / 2;
        var g = ctx.createRadialGradient(px, py, 0, px, py, 9);
        g.addColorStop(0, 'rgba(225,220,255,' + (0.25 + dd * 0.75).toFixed(3) + ')');
        g.addColorStop(1, 'rgba(110,90,255,0)');
        ctx.fillStyle = g; ctx.beginPath(); ctx.arc(px, py, 9, 0, 6.2832); ctx.fill();
      }
    }

    function frame(t) {
      if (!running) return;
      var dt = Math.min(50, t - (last || t)); last = t;
      rotY += dt * 0.00011 * (1 + energy * 5);
      tiltX += (aimX - tiltX) * 0.04; tiltY += (aimY - tiltY) * 0.04;
      energy *= Math.pow(0.9975, dt);
      if (t > sparkAt) {
        sparkAt = t + 110 + rnd() * 320 - energy * 100;
        sparks.push({ e: Math.floor(rnd() * edges.length), t: 0, v: 0.012 + rnd() * 0.02 });
      }
      draw(t);
      raf = requestAnimationFrame(frame);
    }
    function sync() {
      var should = visible && !doc.hidden && !reduced.matches;
      if (should && !running) { running = true; last = 0; raf = requestAnimationFrame(frame); }
      else if (!should && running) { running = false; cancelAnimationFrame(raf); }
    }

    if ('ResizeObserver' in window) new ResizeObserver(resize).observe(canvas); else window.addEventListener('resize', resize);
    resize();
    if ('IntersectionObserver' in window) {
      new IntersectionObserver(function (en) { visible = en[0].isIntersecting; sync(); }).observe(canvas);
    }
    doc.addEventListener('visibilitychange', sync);
    if (reduced.addEventListener) reduced.addEventListener('change', sync);
    window.addEventListener('pointermove', function (ev) {
      if (ev.pointerType === 'touch') return;
      aimY = (ev.clientX / window.innerWidth - 0.5) * 0.9;
      aimX = 0.25 + (ev.clientY / window.innerHeight - 0.5) * 0.6;
    }, { passive: true });
    sync();

    return {
      pulse: function () {
        energy = 1;
        for (var i = 0; i < 14; i++) sparks.push({ e: Math.floor(rnd() * edges.length), t: 0, v: 0.015 + rnd() * 0.025 });
      }
    };
  })();

  /* ---------- Hero: headline reveal + typed prompts ---------- */
  var h1 = $('#headline');
  if (h1 && !reduced.matches) {
    var words = h1.textContent.trim().split(/\s+/);
    h1.setAttribute('aria-label', h1.textContent.trim());
    h1.textContent = '';
    words.forEach(function (word, i) {
      var outer = doc.createElement('span'), inner = doc.createElement('span');
      outer.className = 'w'; outer.setAttribute('aria-hidden', 'true');
      inner.style.setProperty('--i', i); inner.textContent = word;
      outer.appendChild(inner); h1.appendChild(outer);
      h1.appendChild(doc.createTextNode(' '));
    });
    h1.classList.add('split');
    requestAnimationFrame(function () { requestAnimationFrame(function () { h1.classList.add('go'); }); });
  }
  requestAnimationFrame(function () { var hero = $('.hero'); if (hero) hero.classList.add('loaded'); });

  // Each line is a real tool from FEATURES.md and a behaviour described in the docs.
  var lines = [
    ['call me when the build is done', 'call_me', 'Your phone rings and Daemon reads you the result.'],
    ['remind me at 18:00 to call mom', 'remind_me', 'A Signal message arrives at 18:00.'],
    ['search the web for today’s tech news', 'web_search', 'It finds the pages, reads them and sums them up.'],
    ['pause the music', 'media_control', 'Runs on your laptop, through the agent.'],
    ['check the disk usage', 'execute_command', 'Asks for your approval, then runs the command.'],
    ['open x.com and introduce yourself', 'computer', 'Looks at the screen, then uses mouse and keyboard.']
  ];
  var sayText = $('#say-text'), sayOut = $('#say-out'), sayTool = $('#say-tool'), sayDoes = $('#say-does');
  if (sayText && !reduced.matches) {
    var li = 0, timer = 0;
    var wait = function (ms, fn) { timer = setTimeout(fn, ms); };
    var type = function (text, i) {
      sayText.textContent = text.slice(0, i);
      if (i < text.length) return wait(34 + Math.random() * 50, function () { type(text, i + 1); });
      sayTool.textContent = lines[li][1]; sayDoes.textContent = lines[li][2];
      sayOut.classList.remove('hide'); sphere.pulse();
      wait(3400, erase);
    };
    var erase = function () {
      sayOut.classList.add('hide');
      var step = function () {
        var s = sayText.textContent;
        if (s.length) { sayText.textContent = s.slice(0, -1); return wait(14, step); }
        li = (li + 1) % lines.length;
        wait(350, function () { type(lines[li][0], 1); });
      };
      step();
    };
    sayText.textContent = ''; sayOut.classList.add('hide');
    wait(1700, function () { type(lines[0][0], 1); });
    doc.addEventListener('visibilitychange', function () {   // do not type into a hidden tab
      if (doc.hidden) { clearTimeout(timer); }
      else { clearTimeout(timer); sayText.textContent = ''; sayOut.classList.add('hide'); wait(400, function () { type(lines[li][0], 1); }); }
    });
  }

  /* ---------- Scroll: progress bar, nav state, reveals ---------- */
  var bar = $('.progress'), nav = $('.nav'), ticking = false;
  function onScroll() {
    ticking = false;
    var max = root.scrollHeight - window.innerHeight;
    if (bar) bar.style.setProperty('--p', max > 0 ? (window.scrollY / max).toFixed(4) : 0);
    if (nav) nav.classList.toggle('stuck', window.scrollY > 20);
  }
  window.addEventListener('scroll', function () { if (!ticking) { ticking = true; requestAnimationFrame(onScroll); } }, { passive: true });
  onScroll();

  var reveals = $$('.reveal');
  if ('IntersectionObserver' in window && !reduced.matches) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) { if (en.isIntersecting) { en.target.classList.add('in'); io.unobserve(en.target); } });
    }, { rootMargin: '0px 0px -8% 0px', threshold: 0.08 });
    reveals.forEach(function (el) { io.observe(el); });

    var links = $$('.nav nav a');
    var spy = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (!en.isIntersecting) return;
        links.forEach(function (a) { a.classList.toggle('here', a.getAttribute('href') === '#' + en.target.id); });
      });
    }, { rootMargin: '-45% 0px -50% 0px' });
    $$('main section[id]').forEach(function (s) { spy.observe(s); });
  } else {
    reveals.forEach(function (el) { el.classList.add('in'); });
  }

  /* ---------- Feature tiles ---------- */
  $$('.tile').forEach(function (tile) {
    tile.addEventListener('pointermove', function (ev) {
      var r = tile.getBoundingClientRect();
      tile.style.setProperty('--mx', (ev.clientX - r.left) + 'px');
      tile.style.setProperty('--my', (ev.clientY - r.top) + 'px');
    }, { passive: true });
  });
  $$('.marquee-track').forEach(function (track) {     // duplicate once so the loop is seamless
    track.innerHTML += track.innerHTML;
    track.classList.add('run');
  });
  $$('.wave i').forEach(function (b, i) {
    b.style.setProperty('--n', (i * 7) % 11);
    b.style.setProperty('--h', Math.abs(Math.sin(i * 1.7)).toFixed(2));
  });

  /* ---------- Tool profiles (lists copied from DEFAULT_PROFILES in model_config.py) ---------- */
  var READ_ONLY = ['read_file', 'list_directory', 'search_files', 'search_text', 'fetch_url', 'web_search',
    'system_info', 'get_time', 'calculate', 'calendar_list', 'inbox_search', 'inbox_recent'];
  var REMIND = ['remind_me', 'list_reminders', 'cancel_reminder'];
  var PROFILES = {
    'Off': { tools: [], text: 'Chat only. The model gets no tools.' },
    'Read only': { tools: READ_ONLY, text: 'It can look things up: read files, search the web, check the calendar and inbox. It cannot change anything.' },
    'Assistant': { tools: READ_ONLY.concat(REMIND, ['send_message', 'call_me', 'calendar_add', 'calendar_update', 'calendar_delete',
      'write_file', 'send_file', 'inbox_add', 'inbox_delete', 'start_job']), text: 'Adds reminders, calendar, notes, Signal messages, phone calls and background jobs. Writing or sending a file asks first.' },
    'Desktop': { tools: READ_ONLY.concat(REMIND, ['media_control', 'volume', 'clipboard_read', 'clipboard_write', 'open_url', 'open_app',
      'spotify_play', 'spotify_devices', 'spotify_transfer']), text: 'Read only plus reminders, media keys, volume, clipboard, apps and Spotify.' },
    'Full': { tools: null, text: 'Every tool, including the shell and computer control. The risky ones still ask first, and computer control also needs the switch on the laptop.' }
  };
  var box = $('#toolbox'), desc = $('#profile-desc');
  if (box && desc) {
    var chips = $$('code', box);
    chips.forEach(function (c, i) { c.style.setProperty('--d', i); });
    var apply = function (name) {
      var p = PROFILES[name]; if (!p) return;
      var n = 0;
      chips.forEach(function (c) {
        var on = !p.tools || p.tools.indexOf(c.textContent) !== -1;
        c.classList.toggle('on', on); if (on) n++;
      });
      desc.textContent = '';
      var b = doc.createElement('b'); b.textContent = n + ' of ' + chips.length + ' tools';
      desc.appendChild(b); desc.appendChild(doc.createTextNode(p.text));
    };
    box.classList.add('live');
    $$('input[name="profile"]').forEach(function (inp) {
      inp.addEventListener('change', function () { if (inp.checked) apply(inp.value); });
      if (inp.checked) apply(inp.value);
    });
  }

  /* ---------- Video: load only on click ---------- */
  var video = $('#demo-video'), play = $('#play');
  if (video && play) {
    play.addEventListener('click', function () { var p = video.play(); if (p && p.catch) p.catch(function () {}); video.focus(); });
    video.addEventListener('play', function () { play.hidden = true; });
  }

  /* ---------- Copy commands ---------- */
  var copy = $('#copy');
  if (copy) {
    var label = copy.textContent;
    copy.addEventListener('click', function () {
      var text = $$('#cmds .ln').map(function (l) { return l.textContent; }).join('\n') + '\n';
      var done = function (ok) {
        copy.textContent = ok ? 'Copied' : 'Select and copy manually';
        copy.classList.toggle('done', ok);
        setTimeout(function () { copy.textContent = label; copy.classList.remove('done'); }, 2200);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function () { done(true); }, function () { done(false); });
      } else {
        var ta = doc.createElement('textarea'); ta.value = text; ta.setAttribute('readonly', '');
        ta.style.position = 'fixed'; ta.style.opacity = '0'; doc.body.appendChild(ta); ta.select();
        var ok = false; try { ok = doc.execCommand('copy'); } catch (e) {}
        doc.body.removeChild(ta); done(ok);
      }
    });
  }
})();
