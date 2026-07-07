import http from 'http';
const PORT = 9222;
const TOKEN = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4YmUwZmNiYy1iZmZmLTQ5NjEtODhiOC02YzI1MDZhNWQwNDEiLCJlbWFpbCI6IjIxMDQwMDE3NEBxcS5jb20iLCJleHAiOjE3ODMzODYzMTksImlhdCI6MTc4MDc5NDMxOX0.W6YFgnn2uzbG4mH6PY7Fx9q6pqxcPYcgCr5NYkbBBW8';

let _seq = 0;
function rpc(ws, method, params) {
    return new Promise((resolve, reject) => {
        const id = ++_seq;
        const t = setTimeout(() => reject(new Error(`timeout: ${method}`)), 15000);
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
    // Use the homepage tab (which is not on login)
    const tabs = await cdpReq('GET', '/json/list');
    let tab = tabs.find(t => t.url === 'http://localhost:5174/');
    if (!tab) {
        // Open new tab
        tab = await cdpReq('PUT', '/json/new?about:blank');
    }
    console.log('Using tab:', tab.id.substring(0,8), tab.url?.substring(0, 60));

    const ws = new WebSocket(tab.webSocketDebuggerUrl);
    await new Promise((r, reject) => { const t=setTimeout(()=>reject(new Error('ws')),5000); ws.onopen=()=>{clearTimeout(t);r();}; });
    await rpc(ws, 'Runtime.enable');
    await rpc(ws, 'Page.enable');

    // First, set token directly on the about:blank or current page
    await rpc(ws, 'Runtime.evaluate', {
        expression: `localStorage.setItem('ta-access-token', '${TOKEN}')`,
        returnByValue: true
    });

    // Verify
    const check = await rpc(ws, 'Runtime.evaluate', {
        expression: `localStorage.getItem('ta-access-token')`,
        returnByValue: true
    });
    console.log('Token stored:', check.result?.value?.substring(0, 40) + '...');

    // Navigate to analysis
    await rpc(ws, 'Page.navigate', { url: 'http://localhost:5174/analysis' });
    console.log('Navigating to analysis...');
    await sleep(8000);

    const url = await rpc(ws, 'Runtime.evaluate', { expression: 'location.href', returnByValue: true });
    console.log('Current URL:', url.result?.value);

    if (!url.result?.value?.includes('login')) {
        // Check radar
        const radar = await rpc(ws, 'Runtime.evaluate', {
            expression: `(() => {
                const cards = document.querySelectorAll('.card');
                for (const card of cards) {
                    if (card.textContent.includes('主力趋势雷达')) {
                        const m = card.textContent.match(/波动线([\\d.]+).*平均线([\\d.]+)/);
                        const cv = card.querySelector('.tv-lightweight-charts canvas');
                        let drawn = 0;
                        if (cv) {
                            const ctx = cv.getContext('2d');
                            for (let x=cv.width*0.2;x<cv.width*0.8;x+=cv.width*0.15) {
                                for (let y=cv.height*0.2;y<cv.height*0.8;y+=cv.height*0.15) {
                                    try{if(ctx.getImageData(x,y,1,1).data[3]>0)drawn++;}catch(e){}
                                }
                            }
                        }
                        return JSON.stringify({wave:m?.[1]||null, avg:m?.[2]||null, drawn});
                    }
                }
                return 'no radar';
            })()`,
            returnByValue: true
        });
        console.log('Radar:', radar.result?.value);

        // Check period
        const period = await rpc(ws, 'Runtime.evaluate', {
            expression: `document.querySelectorAll('button').forEach(b=>{if(b.textContent.trim()==='月K'&&b.className.includes('purple'))return'月K';})`,
            returnByValue: true
        });

        // If on monthly, switch to daily and check
        console.log('\nSwitching 日K→周K→月K...');
        for (const p of ['日K', '周K', '月K']) {
            await rpc(ws, 'Runtime.evaluate', {
                expression: `document.querySelectorAll('button').forEach(b=>{if(b.textContent.trim()==='${p}')b.click();})`,
                returnByValue: true
            });
            await sleep(4000);
            const check = await rpc(ws, 'Runtime.evaluate', {
                expression: `(() => {
                    const cards = document.querySelectorAll('.card');
                    for (const card of cards) {
                        if (card.textContent.includes('主力趋势雷达')) {
                            const m = card.textContent.match(/波动线([\\d.]+).*平均线([\\d.]+)/);
                            const cv = card.querySelector('.tv-lightweight-charts canvas');
                            let d = 0, t = 0;
                            if (cv) {
                                const ctx = cv.getContext('2d');
                                for (let x=cv.width*0.15;x<cv.width*0.85;x+=cv.width*0.15) {
                                    for (let y=cv.height*0.15;y<cv.height*0.85;y+=cv.height*0.15) {
                                        t++;
                                        try{if(ctx.getImageData(x,y,1,1).data[3]>0)d++;}catch(e){}
                                    }
                                }
                            }
                            return JSON.stringify({period:'${p}', wave:m?.[1]||null, avg:m?.[2]||null, drawn:d+'/'+t});
                        }
                    }
                    return 'no radar';
                })()`,
                returnByValue: true
            });
            console.log(`  ${p}: ${check.result?.value}`);
        }
    }

    ws.close(1000);
}
main().catch(e => console.error(e.message));
