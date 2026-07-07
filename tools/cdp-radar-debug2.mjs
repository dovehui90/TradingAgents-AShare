import http from 'http';
const PORT = 9222;
const TOKEN = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4YmUwZmNiYy1iZmZmLTQ5NjEtODhiOC02YzI1MDZhNWQwNDEiLCJlbWFpbCI6IjIxMDQwMDE3NEBxcS5jb20iLCJleHAiOjE4MTIzMzg5NzIsImlhdCI6MTc4MDgwMjk3Mn0.RUQODinNpWoi6p0a7wUpIptCrRq5UkGolv9CttPjmqc';

let _seq = 0;
function rpc(ws, method, params) {
    return new Promise((resolve, reject) => {
        const id = ++_seq;
        const t = setTimeout(() => reject(new Error(`timeout: ${method}`)), 12000);
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
    // Create fresh tab
    const tab = await cdpReq('PUT', '/json/new?about:blank');
    console.log('Tab:', tab.id.substring(0,8));

    const ws = new WebSocket(tab.webSocketDebuggerUrl);
    await new Promise((r, reject) => { const t=setTimeout(()=>reject(new Error('ws')),5000); ws.onopen=()=>{clearTimeout(t);r();}; });

    await rpc(ws, 'Runtime.enable');
    await rpc(ws, 'Page.enable');

    // Inject token BEFORE navigation
    await rpc(ws, 'Page.addScriptToEvaluateOnNewDocument', {
        source: `localStorage.setItem('ta-access-token', '${TOKEN}');`
    });

    // Navigate to analysis
    await rpc(ws, 'Page.navigate', { url: 'http://localhost:5173/analysis' });
    console.log('Navigated to /analysis, waiting for load...');
    await sleep(8000);

    const url = await rpc(ws, 'Runtime.evaluate', { expression: 'location.href', returnByValue: true });
    console.log('URL:', url.result?.value);

    if (url.result?.value?.includes('login')) {
        console.log('Still redirected to login. Trying direct localStorage set...');
        await rpc(ws, 'Runtime.evaluate', {
            expression: `localStorage.setItem('ta-access-token', '${TOKEN}')`,
            returnByValue: true
        });
        await rpc(ws, 'Page.navigate', { url: 'http://localhost:5173/analysis' });
        await sleep(6000);
        const url2 = await rpc(ws, 'Runtime.evaluate', { expression: 'location.href', returnByValue: true });
        console.log('URL after retry:', url2.result?.value);
        if (url2.result?.value?.includes('login')) {
            console.log('Cannot bypass login. Token verification may be failing.');
            ws.close(1000);
            return;
        }
    }

    // Check radar canvas rendering
    console.log('\n=== Radar Canvas Check ===');
    const radar = await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            const cards = document.querySelectorAll('.card');
            for (const c of cards) {
                if (!c.textContent.includes('主力趋势雷达')) continue;
                const canvases = c.querySelectorAll('canvas');
                const info = [];
                for (const cv of canvases) {
                    const ctx = cv.getContext('2d');
                    let drawn = 0, total = 0;
                    if (ctx && cv.width > 0 && cv.height > 0) {
                        for (let x = cv.width * 0.1; x < cv.width * 0.9; x += 12) {
                            for (let y = cv.height * 0.1; y < cv.height * 0.9; y += 12) {
                                total++;
                                try { if (ctx.getImageData(Math.floor(x), Math.floor(y), 1, 1).data[3] > 0) drawn++; } catch(e) {}
                            }
                        }
                    }
                    info.push({w: cv.width, h: cv.height, drawn, total, pct: total ? (drawn/total*100).toFixed(1)+'%' : '0%'});
                }
                const wave = c.textContent.match(/波动线([\\d.]+)/);
                const avg = c.textContent.match(/平均线([\\d.]+)/);
                return JSON.stringify({canvasCount: canvases.length, canvases: info, wave: wave?.[1], avg: avg?.[1]});
            }
            return 'no radar card found';
        })()`,
        returnByValue: true
    });
    console.log('Radar:', radar.result?.value);

    // Check Kline period
    const period = await rpc(ws, 'Runtime.evaluate', {
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
    console.log('Period:', period.result?.value);

    // Check K-line canvas
    const kline = await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            const canvases = document.querySelectorAll('canvas');
            let klineCanvases = [];
            for (const cv of canvases) {
                const ctx = cv.getContext('2d');
                let drawn = 0, total = 0;
                if (ctx && cv.width > 200 && cv.height > 200) {
                    for (let x = 20; x < cv.width - 20; x += 20) {
                        for (let y = 20; y < cv.height - 20; y += 20) {
                            total++;
                            try { if (ctx.getImageData(Math.floor(x), Math.floor(y), 1, 1).data[3] > 0) drawn++; } catch(e) {}
                        }
                    }
                    klineCanvases.push({w: cv.width, h: cv.height, drawn, total, hasData: drawn > 5});
                }
            }
            return JSON.stringify(klineCanvases);
        })()`,
        returnByValue: true
    });
    console.log('K-line canvases:', kline.result?.value);

    ws.close(1000);
}
main().catch(e => console.error(e.message));
