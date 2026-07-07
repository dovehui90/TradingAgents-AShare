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
    const tab = tabs.find(t => t.url && t.url.includes('5174'));
    if (!tab) { console.log('No 5174 tab'); return; }

    const ws = new WebSocket(tab.webSocketDebuggerUrl);
    await new Promise((r, reject) => { const t=setTimeout(()=>reject(new Error('ws')),5000); ws.onopen=()=>{clearTimeout(t);r();}; });
    await rpc(ws, 'Runtime.enable');

    // Check React fiber/props for RadarPanel to see its state
    const state = await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            // Get all canvas elements and their dimensions
            const canvases = document.querySelectorAll('canvas');
            const info = [];
            for (const c of canvases) {
                info.push({w: c.width, h: c.height, clientW: c.clientWidth, clientH: c.clientHeight});
            }

            // Check for any Vite error overlay
            const viteErr = document.querySelector('vite-error-overlay');

            // Check window.__ZUSTAND stores
            let storeState = null;
            try {
                // Try to access zustand store via React internals
                const root = document.getElementById('root');
                const fiberKey = Object.keys(root).find(k => k.startsWith('__reactFiber'));
                if (fiberKey) {
                    let fiber = root[fiberKey];
                    for (let i=0; i<20 && fiber; i++) fiber = fiber.return || fiber.stateNode?.return;
                }
            } catch(e) { storeState = e.message; }

            return JSON.stringify({
                canvasInfo: info,
                viteError: !!viteErr,
                storeState,
                bodyTextEnd: document.body.innerText.substring(0, 1000),
            });
        })()`,
        returnByValue: true
    });
    console.log('Detailed state:', state.result?.value);

    ws.close(1000);
}
main().catch(e => console.error(e.message));
