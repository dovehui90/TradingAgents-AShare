import http from 'http';
import { writeFileSync } from 'fs';

function cdp(method, path) {
    return new Promise((resolve, reject) => {
        http.request({ hostname: '127.0.0.1', port: 9222, path, method }, res => {
            let d = '';
            res.on('data', c => d += c);
            res.on('end', () => {
                try { resolve(JSON.parse(d)); } catch (e) { reject(new Error('Parse: ' + d.slice(0, 300))); }
            });
        }).on('error', reject).end();
    });
}

async function main() {
    // Open MarketAnalysis page (no auth needed)
    console.log('Opening MarketAnalysis...');
    const tab = await cdp('PUT', '/json/new?url=' + encodeURIComponent('http://127.0.0.1:5173/market-analysis'));

    const ws = new WebSocket(tab.webSocketDebuggerUrl);
    await new Promise(r => { ws.onopen = r; setTimeout(r, 3000); });

    function send(id, method, params) {
        return new Promise(resolve => {
            ws.send(JSON.stringify({ id, method, params }));
            const h = e => {
                const d = JSON.parse(e.data);
                if (d.id === id) { ws.removeEventListener('message', h); resolve(d.result || d.error); }
            };
            ws.addEventListener('message', h);
            setTimeout(() => { ws.removeEventListener('message', h); resolve('timeout'); }, 10000);
        });
    }

    // Wait for page load
    await new Promise(r => {
        ws.addEventListener('message', function h(e) {
            const d = JSON.parse(e.data);
            if (d.method === 'Page.loadEventFired') { ws.removeEventListener('message', h); r(); }
        });
        ws.send(JSON.stringify({ id: 0, method: 'Page.enable' }));
        setTimeout(r, 15000);
    });

    // Wait extra for React rendering
    await new Promise(r => setTimeout(r, 5000));

    // Screenshot
    const shot = await send(20, 'Page.captureScreenshot', { format: 'png' });
    if (shot?.data) {
        writeFileSync('d:/AIProjects/TradingAgents-AShare/frontend/screenshots/ma-test.png', Buffer.from(shot.data, 'base64'));
        console.log('Screenshot saved');
    }

    // Get body text
    const text = await send(30, 'Runtime.evaluate', { expression: 'document.body?.innerText || "NO_BODY"', returnByValue: true });
    const body = text?.result?.value || '';
    console.log('Body text length:', body.length);
    console.log('First 500:', body.slice(0, 500));

    // Check title
    const title = await send(31, 'Runtime.evaluate', { expression: 'document.title', returnByValue: true });
    console.log('Title:', title?.result?.value);

    // Check errors
    const errors = [];
    ws.addEventListener('message', function h(e) {
        const d = JSON.parse(e.data);
        if (d.method === 'Runtime.exceptionThrown') {
            errors.push(d.params?.exceptionDetails?.text || d.params?.exceptionDetails?.exception?.description || 'JS exception');
        }
    });
    await send(32, 'Runtime.enable');
    await new Promise(r => setTimeout(r, 1000));
    if (errors.length) console.log('JS errors:', errors.join('; '));

    ws.close();
}

main().catch(e => console.error('FAIL:', e.message));
