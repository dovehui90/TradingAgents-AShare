import http from 'http';
const PORT = 9222;
let _seq = 0;
function rpc(ws, method, params) {
    return new Promise((resolve, reject) => {
        const id = ++_seq;
        const t = setTimeout(() => reject(new Error(`timeout: ${method}`)), 10000);
        const h = (e) => {
            try { const d = JSON.parse(e.data); if (d.id === id) { clearTimeout(t); ws.removeEventListener('message', h); if (d.error) reject(new Error(JSON.stringify(d.error))); else resolve(d.result); } } catch {}
        };
        ws.addEventListener('message', h);
        ws.send(JSON.stringify({ id, method, params }));
    });
}
function cdpReq(method, path) {
  return new Promise((resolve, reject) => {
    const opts = { hostname: '127.0.0.1', port: PORT, path, method };
    const req = http.request(opts, res => { let d=''; res.on('data',c=>d+=c); res.on('end',()=>{try{resolve(JSON.parse(d))}catch{resolve(d)}}); });
    req.on('error', reject); req.end();
  });
}

async function main() {
    const tabs = await cdpReq('GET', '/json/list');
    const tab = tabs.find(t => t.url && t.url.includes('5174/analysis'));
    if (!tab) { console.log('No analysis tab'); return; }

    const ws = new WebSocket(tab.webSocketDebuggerUrl);
    await new Promise((r, reject) => { const t=setTimeout(()=>reject(new Error('ws')),5000); ws.onopen=()=>{clearTimeout(t);r();}; });
    await rpc(ws, 'Runtime.enable');
    await rpc(ws, 'Log.enable');
    await rpc(ws, 'Network.enable');

    // Get console errors
    const logs = await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            const div = document.createElement('div');
            const orig = window.console.error;
            const errors = [];
            window.console.error = function(...args) { errors.push(args.map(String).join(' ')); orig.apply(console, args); };
            setTimeout(() => { window.console.error = orig; }, 100);
            return JSON.stringify({ hasSession: !!localStorage.getItem('ta-access-token'), url: location.href });
        })()`,
        returnByValue: true
    });
    console.log('Info:', logs.result?.value);

    // Check if there's a form/input that's ready
    const form = await rpc(ws, 'Runtime.evaluate', {
        expression: `JSON.stringify({
            inputExists: !!document.querySelector('textarea, input[type="text"]'),
            submitBtn: Array.from(document.querySelectorAll('button')).filter(b => b.textContent.includes('发送')).map(b => ({text:b.textContent, disabled:b.disabled})),
            streaming: document.body.innerText.includes('streaming') || document.body.innerText.includes('加载'),
            analyzing: document.body.innerText.includes('分析中') || document.body.innerText.includes('running'),
        })`,
        returnByValue: true
    });
    console.log('Form state:', form.result?.value);

    // Check for any Vite error overlay
    const overlay = await rpc(ws, 'Runtime.evaluate', {
        expression: `JSON.stringify({
            viteError: !!document.querySelector('vite-error-overlay'),
            reactError: !!document.querySelector('[class*="error-boundary" i]'),
            bodyClasses: document.body.className,
        })`,
        returnByValue: true
    });
    console.log('Overlay:', overlay.result?.value);

    ws.close(1000);
}
main().catch(e => console.error(e.message));
