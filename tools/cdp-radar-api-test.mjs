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

    console.log('Tab:', tab.id.substring(0,8));
    const ws = new WebSocket(tab.webSocketDebuggerUrl);
    await new Promise((r, reject) => { const t=setTimeout(()=>reject(new Error('ws')),5000); ws.onopen=()=>{clearTimeout(t);r();}; });
    await rpc(ws, 'Runtime.enable');

    // Directly call the API from the browser console
    const directCall = await rpc(ws, 'Runtime.evaluate', {
        expression: `(async () => {
            try {
                const token = localStorage.getItem('ta-access-token');
                const resp = await fetch('/v1/market/radar?symbol=000001.SH&start_date=2025-12-09&end_date=2026-06-07&period=daily', {
                    headers: { 'Authorization': 'Bearer ' + token }
                });
                const data = await resp.json();
                return JSON.stringify({
                    ok: resp.ok,
                    status: resp.status,
                    hasPoints: !!data.points,
                    pointsCount: data.points?.length,
                    firstPoint: data.points?.[0],
                    lastPoint: data.points?.[data.points?.length - 1],
                    hasName: !!data.name,
                });
            } catch(e) {
                return 'error: ' + e.message;
            }
        })()`,
        returnByValue: true,
        awaitPromise: true
    });
    console.log('Direct daily API:', directCall.result?.value);

    // Also test weekly
    const weeklyCall = await rpc(ws, 'Runtime.evaluate', {
        expression: `(async () => {
            const token = localStorage.getItem('ta-access-token');
            const resp = await fetch('/v1/market/radar?symbol=000001.SH&start_date=2024-06-07&end_date=2026-06-07&period=weekly', {
                headers: { 'Authorization': 'Bearer ' + token }
            });
            const data = await resp.json();
            return JSON.stringify({ok: resp.ok, pointsCount: data.points?.length, first: data.points?.[0], last: data.points?.[data.points?.length-1]});
        })()`,
        returnByValue: true,
        awaitPromise: true
    });
    console.log('Direct weekly API:', weeklyCall.result?.value);

    // Check if the chart refs exist
    const refsCheck = await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            const cards = document.querySelectorAll('.card');
            for (const card of cards) {
                if (!card.textContent.includes('主力趋势雷达')) continue;
                const chartDiv = card.querySelector('.tv-lightweight-charts');
                if (!chartDiv) return 'no chart div';
                // Check the canvas dimensions
                const canvases = chartDiv.querySelectorAll('canvas');
                return JSON.stringify(Array.from(canvases).map(c => ({w: c.width, h: c.height})));
            }
            return 'no radar';
        })()`,
        returnByValue: true
    });
    console.log('Canvas dims:', refsCheck.result?.value);

    ws.close(1000);
}
main().catch(e => console.error(e.message));
