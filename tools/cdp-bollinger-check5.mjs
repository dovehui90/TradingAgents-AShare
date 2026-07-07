import http from 'http';
import { readFileSync, writeFileSync } from 'fs';

function cdp(method, path, body) {
    return new Promise((resolve, reject) => {
        const opts = { hostname: '127.0.0.1', port: 9222, path, method, headers: body ? { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(JSON.stringify(body)) } : {} };
        const req = http.request(opts, res => { let d = ''; res.on('data', c => d += c); res.on('end', () => { try { resolve(JSON.parse(d)); } catch(e) { resolve(d); } }); });
        req.on('error', reject);
        if (body) req.write(JSON.stringify(body));
        req.end();
    });
}
function wsDo(wsUrl, msg) {
    return new Promise((resolve, reject) => {
        const ws = new WebSocket(wsUrl);
        ws.onopen = () => ws.send(JSON.stringify(msg));
        ws.onmessage = (e) => { const data = JSON.parse(e.data); if (data.id === msg.id) { ws.close(); resolve(data); } };
        ws.onerror = reject;
        setTimeout(() => reject(new Error('timeout')), 15000);
    });
}
async function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

async function main() {
    const token = readFileSync('d:/AIProjects/TradingAgents-AShare/_tmp_test_token.txt', 'utf8').trim();

    const tab = await cdp('PUT', '/json/new?url=http://127.0.0.1:5173/analysis');
    console.log('Tab:', tab.id);
    const ws = tab.webSocketDebuggerUrl;
    await wsDo(ws, { id: 1, method: 'Page.enable' });
    await wsDo(ws, { id: 2, method: 'Runtime.enable' });
    await sleep(2000);

    await wsDo(ws, { id: 3, method: 'Runtime.evaluate', params: { expression: `localStorage.setItem('ta-access-token','${token}');'ok'`, returnByValue: true }});
    await wsDo(ws, { id: 4, method: 'Page.navigate', params: { url: 'http://127.0.0.1:5173/analysis' } });
    await sleep(6000);

    // Enter "000815" without suffix
    let r = await wsDo(ws, { id: 5, method: 'Runtime.evaluate', params: { expression: `(function(){var i=document.querySelector('input[placeholder*=\"搜索\"]');if(!i)return'no input';var d=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;d.call(i,'000815');i.dispatchEvent(new Event('input',{bubbles:true}));setTimeout(function(){i.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));i.dispatchEvent(new KeyboardEvent('keyup',{key:'Enter',bubbles:true}))},200);return'sent 000815'})()`, returnByValue: true }});
    console.log('Enter stock:', r.result?.result?.value);
    await sleep(10000);

    // Get bollinger panel text
    r = await wsDo(ws, { id: 6, method: 'Runtime.evaluate', params: { expression: `(function(){var cs=document.querySelectorAll('.card');for(var i=0;i<cs.length;i++){var t=cs[i].innerText;if(t.indexOf('布林')>=0&&t.indexOf('乖离')>=0){cs[i].scrollIntoView({behavior:'instant',block:'center'});return t.substring(0,800)}}return'not found'})()`, returnByValue: true }});
    console.log('Bollinger text:', r.result?.result?.value);

    // Check what stock symbol is currently loaded
    r = await wsDo(ws, { id: 7, method: 'Runtime.evaluate', params: { expression: `(function(){var h=document.querySelector('h1,h2,h3');if(h)return'heading:'+h.innerText;var t=document.querySelector('[class*=\"symbol\"]');if(t)return'symbol:'+t.innerText;return document.title})()`, returnByValue: true }});
    console.log('Current stock:', r.result?.result?.value);

    // Get bollinger rect and screenshot
    r = await wsDo(ws, { id: 8, method: 'Runtime.evaluate', params: { expression: `(function(){var cs=document.querySelectorAll('.card');for(var i=0;i<cs.length;i++){if(cs[i].innerText.indexOf('布林')>=0){var b=cs[i].getBoundingClientRect();return JSON.stringify({x:b.x,y:b.y,w:b.width,h:b.height})}}return'nf'})()`, returnByValue: true }});
    console.log('Boll rect:', r.result?.result?.value);
    const rect = JSON.parse(r.result?.result?.value);

    r = await wsDo(ws, { id: 9, method: 'Page.captureScreenshot', params: { format: 'png', clip: { x: rect.x, y: rect.y - 40, width: rect.w, height: rect.h + 80, scale: 1 } } });
    if (r.result?.data) {
        writeFileSync('d:/AIProjects/TradingAgents-AShare/_tmp_bollinger_panel2.png', Buffer.from(r.result.data, 'base64'));
        console.log('Screenshot saved');
    }
}

main().catch(e => console.error(e.message || e));
