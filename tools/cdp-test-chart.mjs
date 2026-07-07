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

async function main() {
    const tabs = await cdpReq('GET', '/json/list');
    const tab = tabs.find(t => t.url === 'http://localhost:5173/analysis');
    if (!tab) { console.log('No tab'); return; }

    const ws = new WebSocket(tab.webSocketDebuggerUrl);
    await new Promise((r, reject) => { const t=setTimeout(()=>reject(new Error('ws')),5000); ws.onopen=()=>{clearTimeout(t);r();}; });
    await rpc(ws, 'Runtime.enable');
    await rpc(ws, 'Page.enable');

    // 1. Directly create a test chart to verify lightweight-charts works
    console.log('=== Testing lightweight-charts directly ===');
    const testResult = await rpc(ws, 'Runtime.evaluate', {
        expression: `(async () => {
            try {
                // Create a test div
                const div = document.createElement('div');
                div.style.cssText = 'width:600px;height:300px;position:fixed;top:10px;right:10px;z-index:99999;background:white;border:2px solid red;';
                document.body.appendChild(div);

                // Dynamically import lightweight-charts
                const m = await import('/node_modules/lightweight-charts/dist/lightweight-charts.esm.development.js');
                const chart = m.createChart(div);
                const series = chart.addSeries(m.LineSeries);
                const data = [
                    { time: { year: 2026, month: 1, day: 5 }, value: 10 },
                    { time: { year: 2026, month: 2, day: 5 }, value: 20 },
                    { time: { year: 2026, month: 3, day: 5 }, value: 15 },
                    { time: { year: 2026, month: 4, day: 5 }, value: 25 },
                    { time: { year: 2026, month: 5, day: 5 }, value: 18 },
                    { time: { year: 2026, month: 6, day: 5 }, value: 22 },
                ];
                series.setData(data);
                chart.timeScale().fitContent();

                await new Promise(r => setTimeout(r, 500));

                // Check if pixels are drawn
                const canvases = div.querySelectorAll('canvas');
                let totalDrawn = 0, totalPx = 0;
                for (const cv of canvases) {
                    const ctx = cv.getContext('2d');
                    if (!ctx) continue;
                    for (let x = 10; x < cv.width - 10; x += 15) {
                        for (let y = 10; y < cv.height - 10; y += 15) {
                            totalPx++;
                            try { if (ctx.getImageData(Math.floor(x), Math.floor(y), 1, 1).data[3] > 0) totalDrawn++; } catch(e) {}
                        }
                    }
                }

                return JSON.stringify({
                    success: true,
                    canvasCount: canvases.length,
                    canvasDims: Array.from(canvases).map(c => ({w: c.width, h: c.height})),
                    drawn: totalDrawn,
                    total: totalPx
                });
            } catch(e) {
                return JSON.stringify({error: e.message, stack: e.stack?.substring(0,500)});
            }
        })()`,
        returnByValue: true,
        awaitPromise: true
    });
    console.log('Test chart result:', testResult.result?.value);

    ws.close(1000);
}
main().catch(e => console.error(e.message));
