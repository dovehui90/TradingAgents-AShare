import http from 'http';
const PORT = 9222;
const TOKEN = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4YmUwZmNiYy1iZmZmLTQ5NjEtODhiOC02YzI1MDZhNWQwNDEiLCJlbWFpbCI6IjIxMDQwMDE3NEBxcS5jb20iLCJleHAiOjE3ODMzODYzMTksImlhdCI6MTc4MDc5NDMxOX0.W6YFgnn2uzbG4mH6PY7Fx9q6pqxcPYcgCr5NYkbBBW8';
let _seq = 0;
function rpc(ws, method, params) {
    return new Promise((resolve, reject) => {
        const id = ++_seq;
        const t = setTimeout(() => reject(new Error(`timeout: ${method}`)), 15000);
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
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

async function main() {
    // Open blank page and inject token
    const tab = await cdpReq('PUT', '/json/new?about:blank');
    const ws = new WebSocket(tab.webSocketDebuggerUrl);
    await new Promise((r, reject) => { const t=setTimeout(()=>reject(new Error('ws')),5000); ws.onopen=()=>{clearTimeout(t);r();}; });
    await rpc(ws, 'Runtime.enable');
    await rpc(ws, 'Page.enable');
    await rpc(ws, 'Network.enable');

    // Inject token before navigating
    await rpc(ws, 'Page.addScriptToEvaluateOnNewDocument', {
        source: `localStorage.setItem('ta-access-token', '${TOKEN}');`
    });

    // Navigate to analysis page
    await rpc(ws, 'Page.navigate', { url: 'http://localhost:5174/analysis' });
    console.log('Navigated to analysis page');
    await sleep(8000);

    const url = await rpc(ws, 'Runtime.evaluate', { expression: 'location.href', returnByValue: true });
    console.log('URL:', url.result?.value);

    // Find the textarea/input and type a stock symbol
    const hasInput = await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            const ta = document.querySelector('textarea');
            const input = document.querySelector('input[type="text"]');
            const el = ta || input;
            if (el) {
                const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')?.set || Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
                nativeInputValueSetter.call(el, '分析贵州茅台600519.SH');
                el.dispatchEvent(new Event('input', { bubbles: true }));
                return 'typed: ' + el.value;
            }
            return 'no input found';
        })()`,
        returnByValue: true
    });
    console.log('Input:', hasInput.result?.value);

    // Find and click send button
    const sendBtn = await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            const btns = document.querySelectorAll('button');
            for (const b of btns) {
                if (b.textContent.includes('发送') && !b.disabled) {
                    b.click();
                    return 'clicked send';
                }
            }
            return 'send button not found';
        })()`,
        returnByValue: true
    });
    console.log('Send:', sendBtn.result?.value);

    // Wait and check what happened
    await sleep(5000);
    const state = await rpc(ws, 'Runtime.evaluate', {
        expression: `JSON.stringify({
            bodyText: document.body.innerText.substring(document.body.innerText.length - 300),
            hasError: document.body.innerText.includes('失败') || document.body.innerText.includes('error'),
            hasRunning: document.body.innerText.includes('分析中') || document.body.innerText.includes('running'),
            hasJobId: document.body.innerText.includes('job_'),
        })`,
        returnByValue: true
    });
    console.log('After submit:', state.result?.value);

    await sleep(5000);
    const state2 = await rpc(ws, 'Runtime.evaluate', {
        expression: `JSON.stringify({
            bodyText: document.body.innerText.substring(document.body.innerText.length - 500),
        })`,
        returnByValue: true
    });
    console.log('After 10s:', state2.result?.value);

    ws.close(1000);
}
main().catch(e => console.error(e.message));
