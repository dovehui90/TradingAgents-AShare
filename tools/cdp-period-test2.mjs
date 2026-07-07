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
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

async function check(label) {
    const tabs = await cdpReq('GET', '/json/list');
    const tab = tabs.find(t => t.url === 'http://localhost:5173/analysis');
    if (!tab) { console.log('No tab'); return; }
    const ws = new WebSocket(tab.webSocketDebuggerUrl);
    await new Promise((r, reject) => { const t=setTimeout(()=>reject(new Error('ws')),5000); ws.onopen=()=>{clearTimeout(t);r();}; });
    await rpc(ws, 'Runtime.enable');

    const r = await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            const btns = document.querySelectorAll('button');
            let period = 'unknown';
            for (const b of btns) {
                const t = b.textContent.trim();
                if ((t === '日K' || t === '周K' || t === '月K') && b.className.includes('purple')) { period = t; break; }
            }

            // Check ALL canvases, grouped by size
            const canvases = document.querySelectorAll('canvas');
            const groups = {};
            for (const cv of canvases) {
                if (cv.width < 100) continue;
                const key = cv.width + 'x' + cv.height;
                if (!groups[key]) groups[key] = {count: 0, drawn: 0, total: 0};
                groups[key].count++;
                const ctx = cv.getContext('2d');
                if (!ctx) continue;
                for (let x = 5; x < cv.width - 5; x += 4) {
                    for (let y = 5; y < cv.height - 5; y += 4) {
                        groups[key].total++;
                        try { if (ctx.getImageData(x, y, 1, 1).data[3] > 0) groups[key].drawn++; } catch(e) {}
                    }
                }
            }
            const summary = Object.entries(groups).map(([k, v]) => {
                const pct = v.total ? (v.drawn/v.total*100).toFixed(1)+'%' : '0%';
                return k + ' x' + v.count + ': ' + v.drawn + '/' + v.total + ' (' + pct + ')';
            });

            const radarCards = document.querySelectorAll('.card');
            let radarWave = null;
            for (const c of radarCards) {
                if (c.textContent.includes('主力趋势雷达')) {
                    const m = c.textContent.match(/波动线([\\d.]+)/);
                    radarWave = m?.[1];
                }
            }

            return JSON.stringify({period, summary, radarWave});
        })()`,
        returnByValue: true
    });
    console.log(`[${label}]`, r.result?.value);
    ws.close(1000);
}

async function main() {
    await check('初始');

    const tabs = await cdpReq('GET', '/json/list');
    const tab = tabs.find(t => t.url === 'http://localhost:5173/analysis');
    const ws = new WebSocket(tab.webSocketDebuggerUrl);
    await new Promise((r, reject) => { const t=setTimeout(()=>reject(new Error('ws')),5000); ws.onopen=()=>{clearTimeout(t);r();}; });
    await rpc(ws, 'Runtime.enable');

    for (const period of ['日K', '周K', '月K']) {
        console.log('--- Click ' + period + ' ---');
        await rpc(ws, 'Runtime.evaluate', {
            expression: `document.querySelectorAll('button').forEach(b=>{if(b.textContent.trim()==='${period}')b.click();})`,
            returnByValue: true
        });
        await sleep(4000);
        ws.close(1000);
        await check(period);
        // Reconnect for next
        const t = await cdpReq('GET', '/json/list');
        const newTab = t.find(tab => tab.url === 'http://localhost:5173/analysis');
        if (newTab) {
            const ws2 = new WebSocket(newTab.webSocketDebuggerUrl);
            await new Promise((r, reject) => { const t=setTimeout(()=>reject(new Error('ws')),5000); ws2.onopen=()=>{clearTimeout(t);r();}; });
            await rpc(ws2, 'Runtime.enable');
            // Save ws2 for next iteration
        }
    }
    console.log('Done');
}
main().catch(e => console.error(e.message));
