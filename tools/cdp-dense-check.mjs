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

async function check(label) {
    const tabs = await cdpReq('GET', '/json/list');
    const tab = tabs.find(t => t.url === 'http://localhost:5173/analysis');
    if (!tab) { console.log('No tab'); return; }
    const ws = new WebSocket(tab.webSocketDebuggerUrl);
    await new Promise((r, reject) => { const t=setTimeout(()=>reject(new Error('ws')),5000); ws.onopen=()=>{clearTimeout(t);r();}; });
    await rpc(ws, 'Runtime.enable');

    const result = await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            const canvases = document.querySelectorAll('canvas');
            const groups = {};
            for (const cv of canvases) {
                if (cv.width < 50) continue;
                const key = cv.width + 'x' + cv.height;
                if (!groups[key]) groups[key] = {w: cv.width, h: cv.height, totalDrawn: 0, totalPx: 0, count: 0};
                const g = groups[key];
                g.count++;
                const ctx = cv.getContext('2d');
                if (!ctx) continue;
                // Scan every 4 pixels for dense check
                for (let x = 5; x < cv.width - 5; x += 4) {
                    for (let y = 5; y < cv.height - 5; y += 4) {
                        g.totalPx++;
                        try { if (ctx.getImageData(x, y, 1, 1).data[3] > 0) g.totalDrawn++; } catch(e) {}
                    }
                }
            }
            const summary = Object.values(groups).map(g => ({
                w: g.w, h: g.h, count: g.count,
                drawn: g.totalDrawn, total: g.totalPx,
                pct: (g.totalDrawn/g.totalPx*100).toFixed(1)+'%'
            }));
            // Also check Radar specifically
            const cards = document.querySelectorAll('.card');
            let radarInfo = null;
            for (const c of cards) {
                if (c.textContent.includes('主力趋势雷达')) {
                    const wave = c.textContent.match(/波动线([\\d.]+)/);
                    const avg = c.textContent.match(/平均线([\\d.]+)/);
                    radarInfo = {wave: wave?.[1], avg: avg?.[1]};
                }
            }
            return JSON.stringify({summary, radar: radarInfo});
        })()`,
        returnByValue: true
    });
    console.log(`[${label}] Canvas groups:`, result.result?.value);
    ws.close(1000);
}

async function main() {
    await check('current state');
    console.log('Done');
}
main().catch(e => console.error(e.message));
