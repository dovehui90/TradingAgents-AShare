import http from 'http';
import { readFileSync, writeFileSync } from 'fs';

function cdp(method, path, body) {
    return new Promise((resolve, reject) => {
        const opts = { hostname: '127.0.0.1', port: 9222, path, method, headers: body ? { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(JSON.stringify(body)) } : {} };
        const req = http.request(opts, res => {
            let d = ''; res.on('data', c => d += c); res.on('end', () => resolve(JSON.parse(d)));
        });
        req.on('error', reject);
        if (body) req.write(JSON.stringify(body));
        req.end();
    });
}

function wsDo(wsUrl, msg) {
    return new Promise((resolve, reject) => {
        const ws = new WebSocket(wsUrl);
        ws.onopen = () => ws.send(JSON.stringify(msg));
        ws.onmessage = (e) => {
            const data = JSON.parse(e.data);
            if (data.id === msg.id) { ws.close(); resolve(data); }
        };
        ws.onerror = reject;
        setTimeout(() => reject(new Error('timeout')), 15000);
    });
}

async function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

async function main() {
    const token = readFileSync('d:/AIProjects/TradingAgents-AShare/_tmp_test_token.txt', 'utf8').trim();

    // Get existing tab that has the analysis page already open
    const tabs = await cdp('GET', '/json/list');
    const analysisTab = tabs.find(t => t.url && t.url.includes('analysis'));
    if (!analysisTab) {
        console.log('No analysis tab found, creating new one');
        return;
    }
    console.log('Found existing tab:', analysisTab.id, analysisTab.url);
    const ws = analysisTab.webSocketDebuggerUrl;

    await wsDo(ws, { id: 1, method: 'Page.enable' });
    await wsDo(ws, { id: 2, method: 'Runtime.enable' });

    // Reload and wait
    await wsDo(ws, { id: 3, method: 'Page.navigate', params: { url: 'http://127.0.0.1:5173/analysis' } });
    await sleep(3000);

    // Inject token again
    await wsDo(ws, { id: 4, method: 'Runtime.evaluate', params: {
        expression: `localStorage.setItem('ta-access-token', '${token}'); 'done'`,
        returnByValue: true
    }});
    await wsDo(ws, { id: 5, method: 'Page.navigate', params: { url: 'http://127.0.0.1:5173/analysis' } });
    await sleep(6000);

    // Enter stock
    await wsDo(ws, { id: 6, method: 'Runtime.evaluate', params: {
        expression: `(() => {
            const inputs = document.querySelectorAll('input');
            for (const inp of inputs) {
                if (inp.placeholder && inp.placeholder.includes('搜索')) {
                    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                    setter.call(inp, '300274.SZ');
                    inp.dispatchEvent(new Event('input', { bubbles: true }));
                    inp.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
                    inp.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', bubbles: true }));
                    return 'ok';
                }
            }
            return 'not found';
        })()`,
        returnByValue: true
    }});

    await sleep(8000);

    // Find bollinger panel and scroll to it
    const pos = await wsDo(ws, { id: 7, method: 'Runtime.evaluate', params: {
        expression: `(() => {
            const cards = document.querySelectorAll('.card');
            for (const c of cards) {
                if (c.innerText.includes('布林') && c.innerText.includes('乖离')) {
                    c.scrollIntoView({ behavior: 'instant', block: 'center' });
                    const rect = c.getBoundingClientRect();
                    return JSON.stringify({ x: rect.x, y: rect.y, w: rect.width, h: rect.height });
                }
            }
            return 'not found';
        })()`,
        returnByValue: true
    }});
    console.log('Bollinger position:', pos.result?.result?.value);

    const bollRect = JSON.parse(pos.result?.result?.value);

    // Take clipped screenshot
    const ss = await wsDo(ws, { id: 8, method: 'Page.captureScreenshot', params: {
        format: 'png',
        clip: {
            x: Math.max(0, bollRect.x - 20),
            y: Math.max(0, bollRect.y - 20),
            width: Math.min(1920, bollRect.w + 40),
            height: Math.min(1080, bollRect.h + 40),
            scale: 1
        }
    }});

    if (ss.result?.data) {
        writeFileSync('d:/AIProjects/TradingAgents-AShare/_tmp_bollinger_panel.png', Buffer.from(ss.result.data, 'base64'));
        console.log('Panel screenshot saved');
    }

    // Also dump axis info
    const axisInfo = await wsDo(ws, { id: 9, method: 'Runtime.evaluate', params: {
        expression: `(() => {
            const cards = document.querySelectorAll('.card');
            for (const c of cards) {
                if (c.innerText.includes('布林') && c.innerText.includes('乖离')) {
                    const canvas = c.querySelector('canvas');
                    if (canvas) return 'canvas: ' + canvas.width + 'x' + canvas.height;
                    return 'no canvas, inner: ' + c.innerHTML.substring(0, 300);
                }
            }
            return 'not found';
        })()`,
        returnByValue: true
    }});
    console.log('Canvas info:', axisInfo.result?.result?.value);

    await cdp('GET', '/json/close/' + analysisTab.id);
}

main().catch(e => { console.error('Error:', e.message || e); process.exit(1); });
