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

async function checkSeries(ws, label) {
    const r = await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            // Access chart internals via React fiber
            const radarCards = [];
            const cards = document.querySelectorAll('.card');
            for (const card of cards) {
                if (!card.textContent.includes('主力趋势雷达')) continue;

                // Find the chart container
                const chartDiv = card.querySelector('.tv-lightweight-charts');
                if (!chartDiv) { radarCards.push({found: 'no chart div'}); continue; }

                // Access chart instance via canvas parent
                const canvases = chartDiv.querySelectorAll('canvas');
                const info = [];
                for (const cv of canvases) {
                    // Try to check if canvas has drawn content by sampling pixels
                    const ctx = cv.getContext('2d');
                    if (!ctx) continue;
                    // Sample a few pixels across the canvas to check if it's blank
                    const w = cv.width;
                    const h = cv.height;
                    const samples = [];
                    for (let x = Math.floor(w * 0.1); x < w * 0.9; x += Math.floor(w * 0.2)) {
                        for (let y = Math.floor(h * 0.1); y < h * 0.9; y += Math.floor(h * 0.2)) {
                            try {
                                const pixel = ctx.getImageData(x, y, 1, 1).data;
                                samples.push({x, y, r: pixel[0], g: pixel[1], b: pixel[2], a: pixel[3]});
                            } catch(e) {
                                samples.push({x, y, err: e.message});
                            }
                        }
                    }
                    const nonTransparent = samples.filter(s => s.a > 0);
                    info.push({
                        w, h,
                        totalSamples: samples.length,
                        nonTransparent: nonTransparent.length,
                        sampleColors: nonTransparent.slice(0, 5),
                    });
                }

                radarCards.push({
                    canvasInfo: info,
                    // Check React fiber for the RadarPanel component
                    radarTextSample: card.textContent.substring(0, 200),
                });
            }
            return JSON.stringify(radarCards);
        })()`,
        returnByValue: true
    });
    console.log(`[${label}] ${r.result?.value}`);
}

async function main() {
    const tabs = await cdpReq('GET', '/json/list');
    const tab = tabs.find(t => t.url && t.url.includes('5174'));
    if (!tab) { console.log('No 5174 tab'); return; }

    const ws = new WebSocket(tab.webSocketDebuggerUrl);
    await new Promise((r, reject) => { const t=setTimeout(()=>reject(new Error('ws')),5000); ws.onopen=()=>{clearTimeout(t);r();}; });
    await rpc(ws, 'Runtime.enable');

    // Check current state
    console.log('=== Current State ===');
    const curPeriod = await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            const btns = document.querySelectorAll('button');
            for (const b of btns) {
                const t = b.textContent.trim();
                if ((t === '日K' || t === '周K' || t === '月K') && b.className.includes('purple')) return t;
            }
            return 'unknown';
        })()`,
        returnByValue: true
    });
    console.log('Active period:', curPeriod.result?.value);

    // Check console errors
    const errors = await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            // Intercept console.error temporarily
            const captured = [];
            const orig = window.console.error;
            window.console.error = function() { captured.push(Array.from(arguments).map(String).join(' ')); };
            setTimeout(() => { window.console.error = orig; }, 50);
            return 'interceptor installed';
        })()`,
        returnByValue: true
    });

    await checkSeries(ws, 'current');

    // Switch to 周K and check
    console.log('\n=== Switching to 周K ===');
    await rpc(ws, 'Runtime.evaluate', {
        expression: `document.querySelectorAll('button').forEach(b => { if(b.textContent.trim()==='周K') b.click(); })`,
        returnByValue: true
    });
    await sleep(4000);
    await checkSeries(ws, '周K');

    // Check for any errors that occurred
    const capturedErrors = await rpc(ws, 'Runtime.evaluate', {
        expression: `JSON.stringify(window.__capturedErrors || [])`,
        returnByValue: true
    });
    console.log('Captured errors:', capturedErrors.result?.value);

    ws.close(1000);
}
main().catch(e => console.error(e.message));
