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
    if (!tab) { console.log('No analysis tab on 5173'); return; }
    console.log('Tab:', tab.id.substring(0,8));

    const ws = new WebSocket(tab.webSocketDebuggerUrl);
    await new Promise((r, reject) => { const t=setTimeout(()=>reject(new Error('ws')),5000); ws.onopen=()=>{clearTimeout(t);r();}; });
    await rpc(ws, 'Runtime.enable');

    // 1. Radar canvas check
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
            return 'no radar';
        })()`,
        returnByValue: true
    });
    console.log('Radar:', radar.result?.value);

    // 2. Period
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

    // 3. Kline canvas
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
            return JSON.stringify(big);
        })()`,
        returnByValue: true
    });
    console.log('K-line:', kline.result?.value);

    ws.close(1000);
}
main().catch(e => console.error(e.message));
