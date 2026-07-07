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

async function checkRadar(ws, label) {
    const r = await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            const cards = document.querySelectorAll('.card');
            let radar = null;
            for (const c of cards) {
                if (c.textContent.includes('主力趋势雷达')) { radar = c; break; }
            }
            if (!radar) return 'no radar card';
            const text = radar.textContent;
            const hasWave = text.includes('波动线');
            const hasAvg = text.includes('平均线');
            const waveMatch = text.match(/波动线([\\d.]+)/);
            const avgMatch = text.match(/平均线([\\d.]+)/);
            const canvases = radar.querySelectorAll('canvas');
            return JSON.stringify({
                hasWave, hasAvg,
                waveVal: waveMatch ? waveMatch[1] : null,
                avgVal: avgMatch ? avgMatch[1] : null,
                canvasCount: canvases.length,
                firstCanvasW: canvases[0]?.width,
                firstCanvasH: canvases[0]?.height,
            });
        })()`,
        returnByValue: true
    });
    console.log(`  [${label}] ${r.result?.value}`);
}

async function main() {
    const tabs = await cdpReq('GET', '/json/list');
    const tab = tabs.find(t => t.url && t.url.includes('5174'));
    if (!tab) { console.log('No 5174 tab'); return; }

    const ws = new WebSocket(tab.webSocketDebuggerUrl);
    await new Promise((r, reject) => { const t=setTimeout(()=>reject(new Error('ws')),5000); ws.onopen=()=>{clearTimeout(t);r();}; });
    await rpc(ws, 'Runtime.enable');

    // Check current state first
    console.log('=== Initial state ===');
    await checkRadar(ws, 'initial');

    // Check which period is active
    const curPeriod = await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            const btns = document.querySelectorAll('button');
            for (const b of btns) {
                if ((b.textContent.includes('日K') || b.textContent.includes('周K') || b.textContent.includes('月K')) && b.className.includes('purple')) {
                    return b.textContent.trim();
                }
            }
            return 'unknown';
        })()`,
        returnByValue: true
    });
    console.log('Current period:', curPeriod.result?.value);

    // Click 日K to switch
    console.log('\n=== Switching to 日K ===');
    await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            const btns = document.querySelectorAll('button');
            for (const b of btns) {
                if (b.textContent.trim() === '日K') { b.click(); return 'clicked 日K'; }
            }
            return 'not found';
        })()`,
        returnByValue: true
    });
    await sleep(3000);
    await checkRadar(ws, 'after 日K');

    // Switch to 周K
    console.log('\n=== Switching to 周K ===');
    await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            const btns = document.querySelectorAll('button');
            for (const b of btns) {
                if (b.textContent.trim() === '周K') { b.click(); return 'clicked 周K'; }
            }
            return 'not found';
        })()`,
        returnByValue: true
    });
    await sleep(4000);
    await checkRadar(ws, 'after 周K');

    // Check network for radar requests
    const radarReqs = await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            const entries = performance.getEntriesByType('resource');
            const radar = entries.filter(e => e.name.includes('radar'));
            return JSON.stringify(radar.map(r => ({url: r.name.substring(r.name.indexOf('/v1/')), duration: r.duration})));
        })()`,
        returnByValue: true
    });
    console.log('\nRadar API calls:', radarReqs.result?.value);

    // Switch to 月K
    console.log('\n=== Switching to 月K ===');
    await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            const btns = document.querySelectorAll('button');
            for (const b of btns) {
                if (b.textContent.trim() === '月K') { b.click(); return 'clicked 月K'; }
            }
            return 'not found';
        })()`,
        returnByValue: true
    });
    await sleep(4000);
    await checkRadar(ws, 'after 月K');

    ws.close(1000);
}
main().catch(e => console.error(e.message));
