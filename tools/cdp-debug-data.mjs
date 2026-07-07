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
    const tab = tabs.find(t => t.url === 'http://localhost:5173/analysis');
    if (!tab) { console.log('No tab'); return; }

    const ws = new WebSocket(tab.webSocketDebuggerUrl);
    await new Promise((r, reject) => { const t=setTimeout(()=>reject(new Error('ws')),5000); ws.onopen=()=>{clearTimeout(t);r();}; });
    await rpc(ws, 'Runtime.enable');

    // Fetch kline data directly from browser
    const klineRaw = await rpc(ws, 'Runtime.evaluate', {
        expression: `(async () => {
            const token = localStorage.getItem('ta-access-token');
            const resp = await fetch('/v1/market/kline?symbol=000001.SH&start_date=2025-12-09&end_date=2026-06-07&period=daily', {
                headers: { 'Authorization': 'Bearer ' + token }
            });
            const data = await resp.json();
            if (data.candles && data.candles.length > 0) {
                const first = data.candles[0];
                const last = data.candles[data.candles.length - 1];
                return JSON.stringify({
                    count: data.candles.length,
                    firstDate: first.date,
                    firstClose: first.close,
                    lastDate: last.date,
                    lastClose: last.close,
                    sample: data.candles[0]
                });
            }
            return JSON.stringify({error: 'no candles', keys: Object.keys(data)});
        })()`,
        returnByValue: true,
        awaitPromise: true
    });
    console.log('Kline data:', klineRaw.result?.value);

    // Check what toChartTime produces for a sample date
    const timeCheck = await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            function toChartTime(value, period) {
                const m = /^(\\d{4})-(\\d{2})-(\\d{2})$/.exec(value);
                if (!m) return null;
                const year = Number(m[1]);
                const month = Number(m[2]);
                const day = Number(m[3]);
                if (!Number.isFinite(year) || !Number.isFinite(month) || !Number.isFinite(day)) return null;
                if (period === 'daily') return { year, month, day };
                return (Date.UTC(year, month - 1, day) / 1000);
            }
            return JSON.stringify({
                daily: toChartTime('2026-06-05', 'daily'),
                weekly: toChartTime('2026-06-05', 'weekly'),
                monthly: toChartTime('2026-06-30', 'monthly'),
            });
        })()`,
        returnByValue: true
    });
    console.log('Time check:', timeCheck.result?.value);

    // Check if canvas is visible (not hidden by CSS)
    const cssCheck = await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            const canvases = document.querySelectorAll('canvas');
            const visibility = [];
            for (const cv of canvases) {
                if (cv.width > 200) {
                    const style = window.getComputedStyle(cv);
                    const rect = cv.getBoundingClientRect();
                    visibility.push({
                        w: cv.width, h: cv.height,
                        display: style.display,
                        visibility: style.visibility,
                        opacity: style.opacity,
                        rectW: Math.round(rect.width),
                        rectH: Math.round(rect.height),
                        rectX: Math.round(rect.x),
                        rectY: Math.round(rect.y),
                    });
                }
            }
            return JSON.stringify(visibility);
        })()`,
        returnByValue: true
    });
    console.log('Canvas CSS:', cssCheck.result?.value);

    // Try to access the React fiber to check series data
    const fiberCheck = await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            // Walk React fiber tree to find KlinePanel or RadarPanel state
            const root = document.getElementById('root');
            if (!root) return 'no root';

            // Count all react fibers
            function countFibers(el, depth) {
                if (depth > 50) return 0;
                const key = Object.keys(el).find(k => k.startsWith('__reactFiber'));
                if (!key) {
                    let c = 0;
                    for (const child of el.children) c += countFibers(child, depth + 1);
                    return c;
                }
                return 1;
            }

            // Check canvas parent for react props
            const canvases = document.querySelectorAll('canvas');
            for (const cv of canvases) {
                if (cv.width > 200) {
                    let parent = cv.parentElement;
                    while (parent) {
                        const key = Object.keys(parent).find(k => k.startsWith('__reactProps'));
                        if (key) {
                            const props = parent[key];
                            return JSON.stringify({
                                found: true,
                                hasRef: !!props.ref,
                                hasChildren: !!props.children,
                                className: props.className,
                            });
                        }
                        parent = parent.parentElement;
                    }
                }
            }
            return 'no fiber found';
        })()`,
        returnByValue: true
    });
    console.log('Fiber:', fiberCheck.result?.value);

    ws.close(1000);
}
main().catch(e => console.error(e.message));
