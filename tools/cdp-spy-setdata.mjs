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

    // SPY: Patch ISeriesApi.setData to capture calls
    console.log('=== Spying on setData ===');
    const spyResult = await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            // The chart module is imported as ES module, so we can't easily patch it.
            // Instead, patch the canvas context to see what's drawn.
            const origGetContext = HTMLCanvasElement.prototype.getContext;
            const calls = [];
            HTMLCanvasElement.prototype.getContext = function(type, ...args) {
                const ctx = origGetContext.call(this, type, ...args);
                if (type === '2d' && this.width > 100 && this.height > 100) {
                    // Patch fill, stroke, etc.
                    if (ctx) {
                        const origFill = ctx.fill;
                        const origStroke = ctx.stroke;
                        const origFillRect = ctx.fillRect;
                        const origBeginPath = ctx.beginPath;
                        const origMoveTo = ctx.moveTo;
                        const origLineTo = ctx.lineTo;
                        const origFillText = ctx.fillText;
                        const origStrokeText = ctx.strokeText;
                        ctx.fill = function(...a) { calls.push('fill:'+a.slice(0,3)); return origFill.apply(this, a); };
                        ctx.stroke = function(...a) { calls.push('stroke'); return origStroke.apply(this, a); };
                        ctx.fillRect = function(...a) { calls.push('fillRect:'+a.slice(0,4)); return origFillRect.apply(this, a); };
                        ctx.beginPath = function() {
                            // Don't log beginPath - it's too frequent
                            return origBeginPath.apply(this);
                        };
                    }
                }
                return ctx;
            };
            return JSON.stringify({patched: true});
        })()`,
        returnByValue: true
    });
    console.log('Patch:', spyResult.result?.value);

    // Trigger a data refresh by switching to weekly and back
    console.log('\n--- Refresh: click 周K ---');
    await rpc(ws, 'Runtime.evaluate', {
        expression: `document.querySelectorAll('button').forEach(b=>{if(b.textContent.trim()==='周K')b.click();})`,
        returnByValue: true
    });
    await sleep(5000);

    // Check if the patch captured anything
    const captured = await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            // Can't access closure variable. Check if any rendering happened.
            const canvases = document.querySelectorAll('canvas');
            let totalDrawn = 0, totalPx = 0;
            for (const cv of canvases) {
                if (cv.width > 200 && cv.height > 200) {
                    const ctx = cv.getContext('2d');
                    if (!ctx) continue;
                    for (let x = 5; x < cv.width - 5; x += 10) {
                        for (let y = 5; y < cv.height - 5; y += 10) {
                            totalPx++;
                            try { if (ctx.getImageData(x, y, 1, 1).data[3] > 0) totalDrawn++; } catch(e) {}
                        }
                    }
                }
            }
            return JSON.stringify({totalDrawn, totalPx, pct: totalPx ? (totalDrawn/totalPx*100).toFixed(2)+'%' : '0%'});
        })()`,
        returnByValue: true
    });
    console.log('After switching to weekly:', captured.result?.value);

    // Switch back to daily
    await rpc(ws, 'Runtime.evaluate', {
        expression: `document.querySelectorAll('button').forEach(b=>{if(b.textContent.trim()==='日K')b.click();})`,
        returnByValue: true
    });
    await sleep(5000);

    const afterDaily = await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            const canvases = document.querySelectorAll('canvas');
            let totalDrawn = 0, totalPx = 0;
            for (const cv of canvases) {
                if (cv.width > 200 && cv.height > 200) {
                    const ctx = cv.getContext('2d');
                    if (!ctx) continue;
                    for (let x = 5; x < cv.width - 5; x += 10) {
                        for (let y = 5; y < cv.height - 5; y += 10) {
                            totalPx++;
                            try { if (ctx.getImageData(x, y, 1, 1).data[3] > 0) totalDrawn++; } catch(e) {}
                        }
                    }
                }
            }
            return JSON.stringify({totalDrawn, totalPx, pct: totalPx ? (totalDrawn/totalPx*100).toFixed(2)+'%' : '0%'});
        })()`,
        returnByValue: true
    });
    console.log('After switching back to daily:', afterDaily.result?.value);

    ws.close(1000);
}
main().catch(e => console.error(e.message));
