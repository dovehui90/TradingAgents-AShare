import { readFileSync, writeFileSync } from 'fs';
import http from 'http';

const TOKEN = readFileSync('d:/AIProjects/TradingAgents-AShare/_tmp_test_token.txt', 'utf-8').trim();

function httpReq(method, path) {
    return new Promise((resolve, reject) => {
        http.request({ hostname: '127.0.0.1', port: 9222, path, method }, res => {
            let d = '';
            res.on('data', c => d += c);
            res.on('end', () => { try { resolve(JSON.parse(d)); } catch (e) { reject(new Error(d.slice(0, 500))); } });
        }).on('error', reject).end();
    });
}

async function probePage(name, url, injectToken = false) {
    console.log(`\n=== ${name} ===`);

    const tab = await httpReq('PUT', `/json/new?url=${encodeURIComponent(url)}`);
    const ws = new WebSocket(tab.webSocketDebuggerUrl);
    await new Promise(r => { ws.onopen = r; setTimeout(r, 2000); });

    function cmd(id, method, params) {
        return new Promise((resolve) => {
            ws.send(JSON.stringify({ id, method, params }));
            const h = e => { const d = JSON.parse(e.data); if (d.id === id) { ws.removeEventListener('message', h); resolve(d.result); } };
            ws.addEventListener('message', h);
            setTimeout(() => { ws.removeEventListener('message', h); resolve(null); }, 8000);
        });
    }

    function waitEvent(method, timeout = 15000) {
        return new Promise(resolve => {
            const h = e => { const d = JSON.parse(e.data); if (d.method === method) { ws.removeEventListener('message', h); resolve(); } };
            ws.addEventListener('message', h);
            setTimeout(() => { ws.removeEventListener('message', h); resolve(); }, timeout);
        });
    }

    await cmd(1, 'Page.enable');
    await cmd(2, 'Page.navigate', { url });
    await waitEvent('Page.loadEventFired', 15000);
    await new Promise(r => setTimeout(r, 4000));

    if (injectToken) {
        await cmd(3, 'Runtime.evaluate', { expression: `localStorage.setItem('ta-access-token', '${TOKEN}')`, returnByValue: true });
        await cmd(4, 'Page.navigate', { url });
        await waitEvent('Page.loadEventFired', 15000);
        await new Promise(r => setTimeout(r, 4000));
    }

    // Get console errors
    const errors = [];
    const errH = e => {
        try {
            const d = JSON.parse(e.data);
            if (d.method === 'Runtime.consoleAPICalled' && d.params?.type === 'error') {
                errors.push(d.params.args?.map(a => a.value).join(' '));
            }
            if (d.method === 'Runtime.exceptionThrown') {
                errors.push(d.params?.exceptionDetails?.text || 'JS error');
            }
        } catch {}
    };
    ws.addEventListener('message', errH);
    await cmd(5, 'Runtime.enable');

    // Get page text content
    await new Promise(r => setTimeout(r, 2000));
    const text = await cmd(10, 'Runtime.evaluate', { expression: 'document.body?.innerText || "NO_BODY"', returnByValue: true });
    const bodyText = text?.result?.value || 'EMPTY';

    console.log('Page text length:', bodyText.length);
    console.log('Page text first 2000 chars:');
    console.log(bodyText.slice(0, 2000));

    if (bodyText.length > 2000) {
        // Show middle-late part too
        const mid = Math.floor(bodyText.length / 2);
        console.log('\n--- Middle section ---');
        console.log(bodyText.slice(mid, mid + 800));
    }

    if (errors.length) console.log('\nCONSOLE ERRORS:', errors.join('\n'));

    ws.close();
}

async function main() {
    console.log('=== CDP Page Probe ===\n');

    // Test MarketAnalysis (no auth needed)
    await probePage('MarketAnalysis', 'http://127.0.0.1:5173/market-analysis');

    // Test Briefing with token injection
    await probePage('Briefing', 'http://127.0.0.1:5173/briefing', true);
}

main().catch(e => console.error('FAIL:', e.message));
