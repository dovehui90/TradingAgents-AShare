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
    // Create fresh tab with token
    const tab = await cdpReq('PUT', '/json/new?about:blank');
    const ws = new WebSocket(tab.webSocketDebuggerUrl);
    await new Promise((r, reject) => { const t=setTimeout(()=>reject(new Error('ws')),5000); ws.onopen=()=>{clearTimeout(t);r();}; });
    await rpc(ws, 'Runtime.enable');
    await rpc(ws, 'Page.enable');
    await rpc(ws, 'Network.enable');

    // Inject token and interceptor BEFORE navigation
    await rpc(ws, 'Page.addScriptToEvaluateOnNewDocument', {
        source: `
            localStorage.setItem('ta-access-token', '${TOKEN}');
            // Spy on fetch
            window.__fetchLog = [];
            const origFetch = window.fetch;
            window.fetch = function(...args) {
                const url = typeof args[0] === 'string' ? args[0] : args[0]?.url || 'unknown';
                if (url.includes('radar') || url.includes('/v1/')) {
                    window.__fetchLog.push({url, time: Date.now(), type: 'fetch'});
                }
                return origFetch.apply(this, args);
            };
        `
    });

    // Navigate
    await rpc(ws, 'Page.navigate', { url: 'http://localhost:5174/analysis' });
    console.log('Navigated to analysis');
    await sleep(8000);

    // Check fetch log
    const fetchLog = await rpc(ws, 'Runtime.evaluate', {
        expression: `JSON.stringify(window.__fetchLog || [])`,
        returnByValue: true
    });
    console.log('Fetch log:', fetchLog.result?.value);

    // Check if RadarPanel exists with data
    const radar = await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            const cards = document.querySelectorAll('.card');
            for (const card of cards) {
                if (card.textContent.includes('主力趋势雷达')) {
                    const match = card.textContent.match(/波动线([\\d.]+).*平均线([\\d.]+)/);
                    return JSON.stringify({
                        wave: match?.[1] || null,
                        avg: match?.[2] || null,
                        fullText: card.textContent.substring(0, 200),
                    });
                }
            }
            return 'no radar';
        })()`,
        returnByValue: true
    });
    console.log('Radar:', radar.result?.value);

    // Check K-line
    const kline = await rpc(ws, 'Runtime.evaluate', {
        expression: `JSON.stringify({
            hasKline: document.body.innerText.includes('K线'),
            hasPeriodButtons: document.body.innerText.includes('日K') && document.body.innerText.includes('周K'),
        })`,
        returnByValue: true
    });
    console.log('K-line check:', kline.result?.value);

    ws.close(1000);
}
main().catch(e => console.error(e.message));
