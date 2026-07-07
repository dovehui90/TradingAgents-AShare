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
    if (!tab) { console.log('No analysis tab on 5173'); return; }
    console.log('Tab:', tab.id.substring(0,8));

    const ws = new WebSocket(tab.webSocketDebuggerUrl);
    await new Promise((r, reject) => { const t=setTimeout(()=>reject(new Error('ws')),5000); ws.onopen=()=>{clearTimeout(t);r();}; });
    await rpc(ws, 'Runtime.enable');
    await rpc(ws, 'Log.enable');

    // Check console errors
    const logs = await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            // Intercept console.error to capture errors
            const errors = [];
            const orig = window.console.error;
            window.console.error = function(...args) {
                errors.push(args.map(String).join(' ').substring(0, 300));
                orig.apply(console, args);
            };
            return JSON.stringify({note: 'capturing errors...'});
        })()`,
        returnByValue: true
    });

    // Check network requests for kline/radar
    const network = await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            const entries = performance.getEntriesByType('resource');
            const mkt = entries.filter(e => e.name.includes('/v1/market/'));
            return JSON.stringify(mkt.map(e => ({
                url: e.name.substring(e.name.indexOf('/v1/')),
                status: e.transferSize > 0 ? 'ok' : 'cached/0',
                size: e.transferSize,
                duration: Math.round(e.duration)
            })));
        })()`,
        returnByValue: true
    });
    console.log('Market API requests:', network.result?.value);

    // Check KlinePanel state via DOM
    const klineInfo = await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            // Look for the Kline panel's header info
            const h2 = document.querySelector('h2');
            const sections = document.querySelectorAll('section');
            for (const s of sections) {
                const text = s.textContent;
                if (text.includes('K线') && text.includes('收盘')) {
                    const dateMatch = text.match(/(\\d{4}-\\d{2}-\\d{2})/);
                    const closeMatch = text.match(/收盘\\s*([\\d.]+)/);
                    const openMatch = text.match(/开盘\\s*([\\d.]+)/);
                    return JSON.stringify({
                        hasDate: !!dateMatch,
                        date: dateMatch?.[1],
                        close: closeMatch?.[1],
                        open: openMatch?.[1],
                        textSnippet: text.substring(0, 300)
                    });
                }
            }
            return 'no kline section';
        })()`,
        returnByValue: true
    });
    console.log('Kline info:', klineInfo.result?.value);

    // Try to access lightweight-charts series data
    const lwCheck = await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            // Check if lightweight-charts is loaded
            const lw = window.lightweight_charts;
            return JSON.stringify({
                lwExists: typeof lw !== 'undefined',
                lwVersion: typeof lw !== 'undefined' ? lw.version : 'N/A'
            });
        })()`,
        returnByValue: true
    });
    console.log('Lightweight charts:', lwCheck.result?.value);

    // Check if there's a visible error overlay
    const errors = await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            const all = document.body.innerText;
            const errMatch = all.match(/Error|错误|TypeError|undefined|null/g);
            return JSON.stringify({
                errorCount: errMatch?.length || 0,
                errors: errMatch?.slice(0, 10),
                bodySnippet: all.substring(0, 500)
            });
        })()`,
        returnByValue: true
    });
    console.log('Page errors:', errors.result?.value);

    ws.close(1000);
}
main().catch(e => console.error(e.message));
