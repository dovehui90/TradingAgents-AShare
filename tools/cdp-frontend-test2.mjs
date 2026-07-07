import http from 'http';
import { writeFileSync, readFileSync } from 'fs';

const TOKEN = readFileSync('d:/AIProjects/TradingAgents-AShare/_tmp_test_token.txt', 'utf-8').trim();

function cdp(method, path) {
    return new Promise((resolve, reject) => {
        http.request({ hostname: '127.0.0.1', port: 9222, path, method }, res => {
            let d = '';
            res.on('data', c => d += c);
            res.on('end', () => { try { resolve(JSON.parse(d)); } catch (e) { reject(new Error(d.slice(0, 300))); } });
        }).on('error', reject).end();
    });
}

async function testPage(name, url) {
    console.log(`\n=== ${name}: ${url} ===`);

    // Step 1: Navigate to root to set origin
    const tab = await cdp('PUT', `/json/new?url=${encodeURIComponent('http://127.0.0.1:5173/')}`);
    const ws = new WebSocket(tab.webSocketDebuggerUrl);
    await new Promise(r => { ws.onopen = r; });

    function send(id, method, params) {
        return new Promise(resolve => {
            const t = setTimeout(() => resolve(null), 10000);
            const h = e => {
                try {
                    const d = JSON.parse(e.data);
                    if (d.id === id) { clearTimeout(t); ws.removeEventListener('message', h); resolve(d.result || d.error); }
                } catch {}
            };
            ws.addEventListener('message', h);
            ws.send(JSON.stringify({ id, method, params }));
        });
    }

    // Error listener
    ws.addEventListener('message', e => {
        try {
            const d = JSON.parse(e.data);
            if (d.method === 'Runtime.exceptionThrown') {
                console.log('  JS ERROR:', (d.params?.exceptionDetails?.text || '').slice(0, 200));
            }
        } catch {}
    });

    await send(1, 'Page.enable');
    await send(2, 'Runtime.enable');

    // Wait for root page load
    await new Promise(r => {
        const h = e => {
            try { const d = JSON.parse(e.data); if (d.method === 'Page.loadEventFired') { ws.removeEventListener('message', h); r(); } } catch {}
        };
        ws.addEventListener('message', h);
        setTimeout(r, 15000);
    });
    await new Promise(r => setTimeout(r, 2000));

    // Step 2: Inject token into localStorage
    const injectResult = await send(3, 'Runtime.evaluate', {
        expression: `localStorage.setItem('ta-access-token', '${TOKEN}'); localStorage.getItem('ta-access-token')?.substring(0, 20) || 'FAIL'`,
        returnByValue: true
    });
    console.log('Token inject:', injectResult?.result?.value);

    // Step 3: Navigate to target page
    await send(4, 'Page.navigate', { url });
    await new Promise(r => {
        const h = e => {
            try { const d = JSON.parse(e.data); if (d.method === 'Page.loadEventFired') { ws.removeEventListener('message', h); r(); } } catch {}
        };
        ws.addEventListener('message', h);
        setTimeout(r, 15000);
    });
    await new Promise(r => setTimeout(r, 4000));

    // Step 4: Check page content
    const title = await send(10, 'Runtime.evaluate', { expression: 'document.title', returnByValue: true });
    const url2 = await send(11, 'Runtime.evaluate', { expression: 'location.href', returnByValue: true });
    console.log('Title:', title?.result?.value);
    console.log('URL:', url2?.result?.value);

    const body = await send(12, 'Runtime.evaluate', {
        expression: 'document.body?.innerText?.slice(0, 2000) || "NULL"',
        returnByValue: true
    });
    const text = body?.result?.value || '';
    console.log('Has "大盘点金":', text.includes('大盘点金'));
    console.log('Has "阳谱":', text.includes('阳谱'));
    console.log('Has "阴谱":', text.includes('阴谱'));
    console.log('Has "盘前速递":', text.includes('盘前速递'));
    console.log('Has "智能分析":', text.includes('智能分析'));

    // Show key content
    const lines = text.split('\n').filter(l => l.trim());
    console.log('\nPage content (first 30 lines):');
    lines.slice(0, 30).forEach(l => console.log('  ', l));

    // Screenshot
    const shot = await send(20, 'Page.captureScreenshot', { format: 'png' });
    if (shot?.data) {
        const fp = `d:/AIProjects/TradingAgents-AShare/frontend/screenshots/test_${name}.png`;
        writeFileSync(fp, Buffer.from(shot.data, 'base64'));
        console.log('Screenshot:', fp);
    }

    ws.close();
    await new Promise(r => setTimeout(r, 500));
}

async function main() {
    console.log('=== 大盘点金 CDP 前端自测 ===');
    await testPage('briefing', 'http://127.0.0.1:5173/briefing');
    await testPage('market-analysis', 'http://127.0.0.1:5173/market-analysis');
    console.log('\n=== 完成 ===');
}

main().catch(e => console.error('FAIL:', e.message));
