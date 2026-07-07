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

async function checkTab(label, port) {
    const tabs = await cdpReq('GET', '/json/list');
    const tab = tabs.find(t => t.url === `http://localhost:${port}/analysis`);
    if (!tab) { console.log(`  [${label}] No tab on port ${port}`); return; }

    const ws = new WebSocket(tab.webSocketDebuggerUrl);
    await new Promise((r, reject) => { const t=setTimeout(()=>reject(new Error('ws')),5000); ws.onopen=()=>{clearTimeout(t);r();}; });
    await rpc(ws, 'Runtime.enable');

    // Check Kline canvas
    const kline = await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            const canvases = document.querySelectorAll('canvas');
            const big = [];
            for (const cv of canvases) {
                if (cv.width > 200 && cv.height > 200) {
                    const ctx = cv.getContext('2d');
                    let drawn = 0, total = 0;
                    if (ctx) {
                        for (let x = 20; x < cv.width - 20; x += 20) {
                            for (let y = 20; y < cv.height - 20; y += 20) {
                                total++;
                                try { if (ctx.getImageData(Math.floor(x), Math.floor(y), 1, 1).data[3] > 0) drawn++; } catch(e) {}
                            }
                        }
                    }
                    big.push({w: cv.width, h: cv.height, drawn, total, hasData: drawn > 10});
                }
            }
            return JSON.stringify({canvasCount: canvases.length, bigCanvases: big});
        })()`,
        returnByValue: true
    });

    // Check radar
    const radar = await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            const cards = document.querySelectorAll('.card');
            for (const c of cards) {
                if (!c.textContent.includes('主力趋势雷达')) continue;
                const canvases = c.querySelectorAll('canvas');
                let drawn = 0, total = 0;
                for (const cv of canvases) {
                    if (cv.width < 100) continue;
                    const ctx = cv.getContext('2d');
                    if (!ctx) continue;
                    for (let x = cv.width * 0.1; x < cv.width * 0.9; x += 15) {
                        for (let y = cv.height * 0.1; y < cv.height * 0.9; y += 15) {
                            total++;
                            try { if (ctx.getImageData(Math.floor(x), Math.floor(y), 1, 1).data[3] > 0) drawn++; } catch(e) {}
                        }
                    }
                }
                const wave = c.textContent.match(/波动线([\\d.]+)/);
                return JSON.stringify({drawn, total, wave: wave?.[1]});
            }
            return 'no radar';
        })()`,
        returnByValue: true
    });

    // Check has symbols loaded
    const loaded = await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            const c = document.querySelector('.card h2');
            return c ? c.textContent.trim() : 'no h2';
        })()`,
        returnByValue: true
    });

    console.log(`  [${label}:${port}] K-line: ${kline.result?.value}, Radar: ${radar.result?.value}, H2: ${loaded.result?.value}`);
    ws.close(1000);
}

async function main() {
    console.log('=== Comparing 5173 vs 5174 ===');
    await checkTab('5173', 5173);
    await checkTab('5174', 5174);
    console.log('Done');
}
main().catch(e => console.error(e.message));
