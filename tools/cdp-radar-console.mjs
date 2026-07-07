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

async function main() {
    const tabs = await cdpReq('GET', '/json/list');
    const tab = tabs.find(t => t.url && t.url.includes('5174/analysis') && !t.url.includes('login'));
    if (!tab) { console.log('No analysis tab'); return; }

    const ws = new WebSocket(tab.webSocketDebuggerUrl);
    await new Promise((r, reject) => { const t=setTimeout(()=>reject(new Error('ws')),5000); ws.onopen=()=>{clearTimeout(t);r();}; });
    await rpc(ws, 'Runtime.enable');
    await rpc(ws, 'Log.enable');

    // Check performance entries for radar API calls
    const perf = await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            const entries = performance.getEntriesByType('resource');
            const radarReqs = entries.filter(e => e.name.includes('radar'));
            const results = radarReqs.map(r => {
                const url = new URL(r.name);
                return {
                    period: url.searchParams.get('period') || 'unknown',
                    symbol: url.searchParams.get('symbol'),
                    status: 'loaded',
                };
            });
            if (results.length === 0) {
                // Check fetch API tracking
                return JSON.stringify({count: 0, msg: 'no radar API calls in performance entries'});
            }
            // Get most recent
            return JSON.stringify({count: results.length, latest: results[results.length-1], all: results});
        })()`,
        returnByValue: true
    });
    console.log('Network entries:', perf.result?.value);

    // Check React state via fiber
    const fiberCheck = await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            // Check if radar data is in the component state
            const cards = document.querySelectorAll('.card');
            let radarCard = null;
            for (const c of cards) {
                if (c.textContent.includes('主力趋势雷达')) { radarCard = c; break; }
            }
            if (!radarCard) return 'no radar card';
            // Check the card's text content for any data
            return JSON.stringify({
                fullText: radarCard.textContent,
                childCount: radarCard.children.length,
            });
        })()`,
        returnByValue: true
    });
    console.log('Radar card:', fiberCheck.result?.value);

    // Check console for errors
    // Reload the page to capture fresh console
    await rpc(ws, 'Page.enable');
    await rpc(ws, 'Page.navigate', { url: 'http://localhost:5174/analysis' });
    console.log('Refreshing page...');

    // Wait for page load
    await new Promise(r => setTimeout(r, 5000));

    // Get console messages
    const consoleMsgs = await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            // Proxy console.error to capture
            const errors = [];
            const origErr = window.console.error;
            window.console.error = function() {
                const msg = Array.from(arguments).map(a => {
                    if (a instanceof Error) return a.message + '\\n' + a.stack;
                    return String(a);
                }).join(' ');
                errors.push(msg);
                origErr.apply(console, arguments);
            };
            window.__radarErrors = errors;
            return 'hooked - check __radarErrors later';
        })()`,
        returnByValue: true
    });

    // Wait for data to load
    await new Promise(r => setTimeout(r, 5000));

    const errors = await rpc(ws, 'Runtime.evaluate', {
        expression: `JSON.stringify(window.__radarErrors || [])`,
        returnByValue: true
    });
    console.log('Console errors:', errors.result?.value);

    // Final radar check
    const final = await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            const cards = document.querySelectorAll('.card');
            for (const card of cards) {
                if (card.textContent.includes('主力趋势雷达')) {
                    const match = card.textContent.match(/波动线([\\d.]+).*平均线([\\d.]+)/);
                    const chartDiv = card.querySelector('.tv-lightweight-charts');
                    let drawn = 0, sampled = 0;
                    if (chartDiv) {
                        const canvases = chartDiv.querySelectorAll('canvas');
                        for (const cv of canvases) {
                            const ctx = cv.getContext('2d');
                            if (!ctx) continue;
                            for (let x=cv.width*0.1; x<cv.width*0.9; x+=cv.width*0.15) {
                                for (let y=cv.height*0.1; y<cv.height*0.9; y+=cv.height*0.15) {
                                    sampled++;
                                    try { if (ctx.getImageData(x,y,1,1).data[3]>0) drawn++; } catch(e) {}
                                }
                            }
                        }
                    }
                    return JSON.stringify({
                        wave: match?.[1] || null,
                        avg: match?.[2] || null,
                        drawn: drawn+'/'+sampled,
                    });
                }
            }
            return 'no radar';
        })()`,
        returnByValue: true
    });
    console.log('Final radar:', final.result?.value);

    ws.close(1000);
}
main().catch(e => console.error(e.message));
