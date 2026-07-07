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
    await rpc(ws, 'Log.enable');

    // Collect existing console messages by intercepting
    // First, check Runtime.consoleAPICalled
    const msgs = [];
    const handler = (e) => {
        try {
            const d = JSON.parse(e.data);
            if (d.method === 'Runtime.consoleAPICalled') {
                const args = d.params?.args || [];
                const text = args.map(a => {
                    if (a.type === 'string') return a.value;
                    if (a.type === 'object') return JSON.stringify(a.value || a.objectId || '{}');
                    return a.value != null ? String(a.value) : 'null';
                }).join(' ');
                msgs.push(`[${d.params?.type}] ${text.substring(0, 300)}`);
            }
        } catch {}
    };
    ws.addEventListener('message', handler);

    // Trigger a re-render by evaluating something
    await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            // Trigger some activity to generate console messages
            const cards = document.querySelectorAll('.card');
            const canvases = document.querySelectorAll('canvas');
            return JSON.stringify({cards: cards.length, canvases: canvases.length});
        })()`,
        returnByValue: true
    });

    await sleep(2000);
    ws.removeEventListener('message', handler);

    // Filter for relevant messages
    const relevant = msgs.filter(m =>
        m.includes('error') || m.includes('Error') || m.includes('warn') ||
        m.includes('fail') || m.includes('undefined') || m.includes('null') ||
        m.includes('chart') || m.includes('Chart') || m.includes('series') ||
        m.includes('setData') || m.includes('lightweight')
    );

    console.log('Console messages (' + msgs.length + ' total, ' + relevant.length + ' relevant):');
    for (const m of relevant.slice(0, 30)) {
        console.log(' ', m);
    }

    // Also try to manually set data on a chart
    console.log('\n--- Testing manual setData ---');
    const testResult = await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            // Try to find the lightweight-charts createChart reference
            // Look for the chart instance in the DOM
            const container = document.querySelector('.absolute.inset-0');
            if (!container) return 'no container';

            // Check if chart instance exists on the element
            const keys = Object.keys(container);
            const reactKeys = keys.filter(k => k.startsWith('__react'));
            return JSON.stringify({
                hasReactFiber: reactKeys.length > 0,
                reactKeys: reactKeys.map(k => k.substring(0, 30)),
                containerHTML: container.outerHTML?.substring(0, 200)
            });
        })()`,
        returnByValue: true
    });
    console.log('Container:', testResult.result?.value);

    ws.close(1000);
}
main().catch(e => console.error(e.message));
