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

async function checkChartData(ws, label) {
    const r = await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            // Find all chart canvas containers by looking for tv-lightweight-charts
            const containers = document.querySelectorAll('.tv-lightweight-charts');
            const results = [];

            for (const c of containers) {
                // Check if this is in the radar panel
                const card = c.closest('.card');
                if (!card) continue;
                const isRadar = card.textContent.includes('主力趋势雷达');
                if (!isRadar) continue;

                // Get the chart table (internal structure)
                const tables = c.querySelectorAll('table');
                const cells = c.querySelectorAll('td');

                // Count rendered elements - series lines are drawn on canvas
                const canvases = c.querySelectorAll('canvas');

                results.push({
                    isRadar: true,
                    tableCount: tables.length,
                    cellCount: cells.length,
                    canvasCount: canvases.length,
                    // Get canvas dimensions and check if 2D context has content
                    canvasInfo: Array.from(canvases).map((cv, i) => ({
                        index: i,
                        width: cv.width,
                        height: cv.height,
                        clientWidth: cv.clientWidth,
                        clientHeight: cv.clientHeight,
                    })),
                    // Full text of the radar panel for content check
                    radarText: card.textContent.substring(0, 300),
                });
            }

            return JSON.stringify(results);
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

    // 1. First, what period is active?
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
    await checkChartData(ws, 'current');

    // 2. Switch to 日K first and wait
    console.log('\n=== Switch to 日K ===');
    await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            const btns = document.querySelectorAll('button');
            for (const b of btns) {
                if (b.textContent.trim() === '日K') { b.click(); return 'ok'; }
            }
            return 'not found';
        })()`,
        returnByValue: true
    });
    await sleep(3000);
    await checkChartData(ws, '日K');

    // 3. Switch to 周K
    console.log('\n=== Switch to 周K ===');
    await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            const btns = document.querySelectorAll('button');
            for (const b of btns) {
                if (b.textContent.trim() === '周K') { b.click(); return 'ok'; }
            }
            return 'not found';
        })()`,
        returnByValue: true
    });
    await sleep(4000);
    await checkChartData(ws, '周K');

    // 4. Switch to 月K
    console.log('\n=== Switch to 月K ===');
    await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            const btns = document.querySelectorAll('button');
            for (const b of btns) {
                if (b.textContent.trim() === '月K') { b.click(); return 'ok'; }
            }
            return 'not found';
        })()`,
        returnByValue: true
    });
    await sleep(4000);
    await checkChartData(ws, '月K');

    ws.close(1000);
}
main().catch(e => console.error(e.message));
