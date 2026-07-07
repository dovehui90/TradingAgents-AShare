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

    // Look for chart instances through React fiber
    const result = await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            // Find the radar chart container div
            const cards = document.querySelectorAll('.card');
            let radarDiv = null;
            for (const c of cards) {
                if (c.textContent.includes('主力趋势雷达')) {
                    radarDiv = c.querySelector('.tv-lightweight-charts');
                    break;
                }
            }
            if (!radarDiv) return 'no radar chart div';

            // List all non-standard properties on the container
            const props = [];
            for (const key of Object.getOwnPropertyNames(radarDiv)) {
                if (!key.startsWith('on') && typeof radarDiv[key] !== 'function') {
                    try {
                        const val = radarDiv[key];
                        const type = typeof val;
                        if (type === 'object' && val !== null) {
                            props.push(key + ': ' + (Array.isArray(val) ? 'Array(' + val.length + ')' : val.constructor?.name || 'object'));
                        } else if (type !== 'string' || key === 'style' || key === 'classList') {
                            // skip DOM standard props
                        } else {
                            props.push(key + ': ' + type + ' = ' + String(val).substring(0, 50));
                        }
                    } catch(e) {}
                }
            }

            // Also check React fiber for chart refs
            const fiberKey = Object.keys(radarDiv).find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
            let fiberInfo = null;
            if (fiberKey) {
                let fiber = radarDiv[fiberKey];
                for (let i = 0; i < 5 && fiber; i++) {
                    fiberInfo = {
                        type: fiber.type?.name || fiber.type?.displayName || (typeof fiber.type === 'string' ? fiber.type : '?'),
                        hasMemoizedState: !!fiber.memoizedState,
                        hasRef: !!fiber.ref,
                        tag: fiber.tag,
                    };
                    fiber = fiber.return;
                }
            }

            // Also try to access chart via canvas - chart might store itself on the canvas parent
            const canvasParent = radarDiv.querySelector('div > div');
            if (canvasParent) {
                const cpProps = Object.keys(canvasParent).filter(k => !k.startsWith('on'));
                return JSON.stringify({
                    canvasParentCustomProps: cpProps.slice(0, 20),
                    fiberInfo,
                    props: props.slice(0, 20),
                });
            }

            return JSON.stringify({fiberInfo, props: props.slice(0, 20)});
        })()`,
        returnByValue: true
    });
    console.log('Properties:', result.result?.value);

    ws.close(1000);
}
main().catch(e => console.error(e.message));
