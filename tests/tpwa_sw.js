const fs = require('fs'), vm = require('vm');
const code = fs.readFileSync(process.argv[2], 'utf8');
const listeners = {}, posted = [];
let reply = { ok: true, status: 200 };
const ctx = {
  self: { addEventListener: (n, f) => { listeners[n] = f; }, skipWaiting() {}, clients: { claim() {} } },
  URL, btoa, Uint8Array, String, console,
  Response: { redirect: (u, s) => ({ redirect: u, status: s }) },
  fetch: async (u, o) => { posted.push([u, JSON.parse(o.body)]); return reply; },
};
ctx.self.self = ctx.self;
vm.createContext(ctx); vm.runInContext(code, ctx);
const form = (m) => ({ get: k => (m[k] === undefined ? null : m[k]), getAll: k => (k === 'files' ? (m.files || []) : []) });
const mk = (m, method = 'POST', path = '/share') => { let out; const e = { request: { method, url: 'https://x.ts.net' + path, formData: async () => form(m) }, respondWith: p => { out = p; } }; listeners.fetch(e); return out; };
(async () => {
  const f = { name: 'p.png', size: 3, arrayBuffer: async () => new Uint8Array([1, 2, 3]).buffer };
  let r = await mk({ title: 'T', text: 'see https://a.example/x', url: 'https://a.example/x', files: [f] });
  if (r.redirect !== '/?shared=ok' || r.status !== 303) throw new Error('redirect ' + JSON.stringify(r));
  const [u, body] = posted[0];
  if (u !== '/api/inbox' || body.text !== 'T\nsee https://a.example/x' || body.files[0].name !== 'p.png' || body.files[0].data !== 'AQID' || body.tags[0] !== 'shared') throw new Error('body ' + JSON.stringify(body));
  r = await mk({ title: 'same', text: 'same' }); if (posted[1][1].text !== 'same') throw new Error('dedupe ' + posted[1][1].text);
  r = await mk({ url: 'https://only.example' }); if (posted[2][1].text !== 'https://only.example') throw new Error('url only');
  reply = { ok: false, status: 401 }; r = await mk({ text: 'x' }); if (r.redirect !== '/?shared=locked') throw new Error('locked ' + r.redirect);
  reply = { ok: false, status: 500 }; r = await mk({ text: 'x' }); if (r.redirect !== '/?shared=fail') throw new Error('fail');
  ctx.fetch = async () => { throw new Error('offline'); }; r = await mk({ text: 'x' }); if (r.redirect !== '/?shared=fail') throw new Error('offline');
  if (mk({}, 'GET', '/share') !== undefined || mk({}, 'POST', '/other') !== undefined) throw new Error('only POST /share');
  console.log('SW OK');
})().catch(e => { console.error('SW FAIL', e.message); process.exit(1); });
