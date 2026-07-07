import http from 'http';
const PORT = 9222;
const TOKEN = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4YmUwZmNiYy1iZmZmLTQ5NjEtODhiOC02YzI1MDZhNWQwNDEiLCJlbWFpbCI6IjIxMDQwMDE3NEBxcS5jb20iLCJleHAiOjE3ODMzODYzMTksImlhdCI6MTc4MDc5NDMxOX0.W6YFgnn2uzbG4mH6PY7Fx9q6pqxcPYcgCr5NYkbBBW8';

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

async function checkCanvas(ws, label) {
    const r = await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            const cards = document.querySelectorAll('.card');
            for (const card of cards) {
                if (!card.textContent.includes('主力趋势雷达')) continue;
                const chartDiv = card.querySelector('.tv-lightweight-charts');
                if (!chartDiv) return 'no chart div';
                const canvases = chartDiv.querySelectorAll('canvas');
                const info = [];
                for (const cv of canvases) {
                    const ctx = cv.getContext('2d');
                    if (!ctx) continue;
                    let drawn = 0;
                    const w = cv.width, h = cv.height;
                    for (let x = Math.floor(w*0.1); x < w*0.9; x += Math.floor(w*0.2)) {
                        for (let y = Math.floor(h*0.1); y < h*0.9; y += Math.floor(h*0.2)) {
                            try { if (ctx.getImageData(x,y,1,1).data[3] > 0) drawn++; } catch(e) {}
                        }
                    }
                    info.push({w, h, drawnPixels: drawn});
                }
                const waveV = card.textContent.match(/波动线([\\d.]+)/);
                const avgV = card.textContent.match(/平均线([\\d.]+)/);
                return JSON.stringify({
                    legendWave: waveV ? waveV[1] : null,
                    legendAvg: avgV ? avgV[1] : null,
                    canvases: info,
                });
            }
            return 'no radar panel';
        })()`,
        returnByValue: true
    });
    console.log(`  [${label}] ${r.result?.value}`);
}

async function main() {
    // Open fresh page
    const tab = await cdpReq('PUT', '/json/new?about:blank');
    const ws = new WebSocket(tab.webSocketDebuggerUrl);
    await new Promise((r, reject) => { const t=setTimeout(()=>reject(new Error('ws')),5000); ws.onopen=()=>{clearTimeout(t);r();}; });
    await rpc(ws, 'Runtime.enable');
    await rpc(ws, 'Page.enable');
    await rpc(ws, 'Network.enable');

    // Inject token
    await rpc(ws, 'Page.addScriptToEvaluateOnNewDocument', {
        source: `localStorage.setItem('ta-access-token', '${TOKEN}');`
    });

    // Navigate to analysis page
    await rpc(ws, 'Page.navigate', { url: 'http://localhost:5174/analysis' });
    console.log('Navigating to analysis...');
    await sleep(5000);

    const url = await rpc(ws, 'Runtime.evaluate', { expression: 'location.href', returnByValue: true });
    console.log('URL:', url.result?.value);

    // Check initial state
    console.log('\n=== Initial (日K default) ===');
    await checkCanvas(ws, 'initial');

    // Switch to 周K
    console.log('\n=== Switch to 周K ===');
    await rpc(ws, 'Runtime.evaluate', {
        expression: `document.querySelectorAll('button').forEach(b => { if(b.textContent.trim()==='周K') b.click(); })`,
        returnByValue: true
    });
    await sleep(4000);
    await checkCanvas(ws, '周K');

    // Switch to 月K
    console.log('\n=== Switch to 月K ===');
    await rpc(ws, 'Runtime.evaluate', {
        expression: `document.querySelectorAll('button').forEach(b => { if(b.textContent.trim()==='月K') b.click(); })`,
        returnByValue: true
    });
    await sleep(4000);
    await checkCanvas(ws, '月K');

    ws.close(1000);
}
main().catch(e => console.error(e.message));
