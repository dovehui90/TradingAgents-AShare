import http from 'http';
const PORT = 9222;

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

async function main() {
    const tabs = await cdpReq('GET', '/json/list');
    const tab = tabs.find(t => t.url && t.url.includes('5174/analysis') && !t.url.includes('login'));
    if (!tab) { console.log('No analysis tab'); return; }

    const ws = new WebSocket(tab.webSocketDebuggerUrl);
    await new Promise((r, reject) => { const t=setTimeout(()=>reject(new Error('ws')),5000); ws.onopen=()=>{clearTimeout(t);r();}; });
    await rpc(ws, 'Runtime.enable');

    // Test monthly API
    const monthly = await rpc(ws, 'Runtime.evaluate', {
        expression: `(async () => {
            try {
                const token = localStorage.getItem('ta-access-token');
                const url = '/v1/market/radar?symbol=000001.SH&start_date=2021-06-08&end_date=2026-06-07&period=monthly';
                const resp = await fetch(url, {
                    headers: { 'Authorization': 'Bearer ' + token }
                });
                const text = await resp.text();
                return JSON.stringify({
                    ok: resp.ok,
                    status: resp.status,
                    contentType: resp.headers.get('content-type'),
                    textLen: text.length,
                    textStart: text.substring(0, 300),
                    textEnd: text.substring(text.length - 200),
                });
            } catch(e) {
                return 'error: ' + e.message;
            }
        })()`,
        returnByValue: true,
        awaitPromise: true
    });
    console.log('Monthly API:', monthly.result?.value);

    // Test weekly with more detail
    const weekly = await rpc(ws, 'Runtime.evaluate', {
        expression: `(async () => {
            try {
                const token = localStorage.getItem('ta-access-token');
                const url = '/v1/market/radar?symbol=000001.SH&start_date=2024-06-07&end_date=2026-06-07&period=weekly';
                const resp = await fetch(url, {
                    headers: { 'Authorization': 'Bearer ' + token }
                });
                const text = await resp.text();
                return JSON.stringify({ok: resp.ok, status: resp.status, textLen: text.length, start: text.substring(0, 300)});
            } catch(e) {
                return 'error: ' + e.message + ' ' + e.stack;
            }
        })()`,
        returnByValue: true,
        awaitPromise: true
    });
    console.log('Weekly API:', weekly.result?.value);

    // Check the klinePeriod in store
    const store = await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            // Check which period button is active
            const btns = document.querySelectorAll('button');
            for (const b of btns) {
                const t = b.textContent.trim();
                if ((t === '日K' || t === '周K' || t === '月K') && b.className.includes('purple')) {
                    return t;
                }
            }
            return 'unknown';
        })()`,
        returnByValue: true
    });
    console.log('Active period:', store.result?.value);

    ws.close(1000);
}
main().catch(e => console.error(e.message));
