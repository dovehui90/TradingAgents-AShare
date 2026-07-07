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
            if (data.id === msg.id) {
                ws.close();
                resolve(data);
            }
        };
        ws.onerror = reject;
        setTimeout(() => reject(new Error('timeout')), 10000);
    });
}

async function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

async function main() {
    const token = readFileSync('d:/AIProjects/TradingAgents-AShare/_tmp_test_token.txt', 'utf8').trim();
    console.log('Token loaded');

    // Open analysis page for 300274.SZ
    const targetUrl = 'http://127.0.0.1:5173/analysis';
    const tab = await cdp('PUT', `/json/new?url=${encodeURIComponent(targetUrl)}`);
    console.log('Tab:', tab.id);
    const ws = tab.webSocketDebuggerUrl;

    await wsDo(ws, { id: 1, method: 'Page.enable' });
    await wsDo(ws, { id: 2, method: 'Runtime.enable' });
    await sleep(2000);

    // Inject token
    const injResult = await wsDo(ws, {
        id: 3, method: 'Runtime.evaluate', params: {
            expression: `localStorage.setItem('ta-access-token', '${token}'); 'done'`,
            returnByValue: true
        }
    });
    console.log('Token injected:', injResult.result?.result?.value);

    // Reload to apply auth
    await wsDo(ws, { id: 4, method: 'Page.navigate', params: { url: targetUrl } });
    await sleep(5000);

    // Check if page loaded properly
    const title = await wsDo(ws, {
        id: 5, method: 'Runtime.evaluate', params: { expression: 'document.title', returnByValue: true }
    });
    console.log('Page title:', title.result?.result?.value);

    // Try to find the search input and enter stock
    const searchResult = await wsDo(ws, {
        id: 6, method: 'Runtime.evaluate', params: {
            expression: `(() => {
                // Find search bar and enter stock code
                const inputs = document.querySelectorAll('input');
                let searchInput = null;
                for (const inp of inputs) {
                    if (inp.placeholder && (inp.placeholder.includes('搜索') || inp.placeholder.includes('search') || inp.placeholder.includes('代码'))) {
                        searchInput = inp;
                        break;
                    }
                }
                if (!searchInput && inputs.length > 0) searchInput = inputs[0];
                if (searchInput) {
                    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                    setter.call(searchInput, '300274.SZ');
                    searchInput.dispatchEvent(new Event('input', { bubbles: true }));
                    searchInput.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
                    searchInput.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', bubbles: true }));
                    return 'entered 300274.SZ into: ' + (searchInput.placeholder || searchInput.className);
                }
                return 'no input, found ' + inputs.length + ' inputs';
            })()`,
            returnByValue: true
        }
    });
    console.log('Search:', searchResult.result?.result?.value);

    await sleep(8000);

    // Take screenshot
    const ss = await wsDo(ws, {
        id: 7, method: 'Page.captureScreenshot', params: { format: 'png' }
    });
    if (ss.result?.data) {
        const buf = Buffer.from(ss.result.data, 'base64');
        writeFileSync('d:/AIProjects/TradingAgents-AShare/_tmp_bollinger_screenshot.png', buf);
        console.log('Screenshot saved. Size:', buf.length, 'bytes');
    } else {
        console.log('No screenshot data');
    }

    // Find bollinger panel specifically
    const bollInfo = await wsDo(ws, {
        id: 8, method: 'Runtime.evaluate', params: {
            expression: `(() => {
                const cards = document.querySelectorAll('.card');
                let info = [];
                for (const c of cards) {
                    const text = c.innerText.substring(0, 80);
                    if (text.includes('布林') || text.includes('乖离')) {
                        const rect = c.getBoundingClientRect();
                        info.push('Found bollinger panel: ' + JSON.stringify({ x: rect.x, y: rect.y, w: rect.width, h: rect.height }) + ' text: ' + text);
                    }
                }
                return info.length ? info.join('\\n') : 'No bollinger panel found among ' + cards.length + ' cards';
            })()`,
            returnByValue: true
        }
    });
    console.log('Bollinger panel:', bollInfo.result?.result?.value);

    // Close tab
    await cdp('GET', '/json/close/' + tab.id);
}

main().catch(e => { console.error('Error:', e.message || e); process.exit(1); });
