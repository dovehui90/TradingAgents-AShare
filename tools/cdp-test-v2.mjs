import { readFileSync, writeFileSync } from 'fs';
import http from 'http';

const TOKEN = readFileSync('d:/AIProjects/TradingAgents-AShare/_tmp_test_token.txt', 'utf-8').trim();

function httpReq(method, path, body) {
    return new Promise((resolve, reject) => {
        const req = http.request({ hostname: '127.0.0.1', port: 9222, path, method }, res => {
            let d = '';
            res.on('data', c => d += c);
            res.on('end', () => {
                try { resolve(JSON.parse(d)); } catch (e) { reject(new Error(`Parse error: ${d.slice(0, 200)}`)); }
            });
        });
        req.on('error', reject);
        if (body) req.write(body);
        req.end();
    });
}

function wsCmd(ws, id, method, params) {
    return new Promise((resolve, reject) => {
        ws.send(JSON.stringify({ id, method, params }));
        const handler = e => {
            const d = JSON.parse(e.data);
            if (d.id === id) { ws.removeEventListener('message', handler); resolve(d.result); }
        };
        ws.addEventListener('message', handler);
        setTimeout(() => { ws.removeEventListener('message', handler); resolve(null); }, 5000);
    });
}

function wsWait(ws, method, timeout = 10000) {
    return new Promise(resolve => {
        const handler = e => {
            const d = JSON.parse(e.data);
            if (d.method === method) { ws.removeEventListener('message', handler); resolve(); }
        };
        ws.addEventListener('message', handler);
        setTimeout(() => { ws.removeEventListener('message', handler); resolve(); }, timeout);
    });
}

async function testPage(name, url) {
    console.log(`\n--- ${name}: ${url} ---`);

    // Create tab
    const tab = await httpReq('PUT', `/json/new?url=${encodeURIComponent(url)}`);
    console.log('Tab created:', tab.id);

    const ws = new WebSocket(tab.webSocketDebuggerUrl);
    await new Promise(r => { ws.onopen = r; setTimeout(r, 2000); });

    // Enable Page domain
    await wsCmd(ws, 1, 'Page.enable');

    // Navigate
    await wsCmd(ws, 2, 'Page.navigate', { url });
    await wsWait(ws, 'Page.loadEventFired', 10000);
    await new Promise(r => setTimeout(r, 3000));

    // Inject token if needed
    if (url.includes('briefing')) {
        await wsCmd(ws, 3, 'Runtime.evaluate', {
            expression: `localStorage.setItem('ta-access-token', '${TOKEN}'); 'done'`,
            returnByValue: true
        });
        console.log('Token injected');

        // Reload
        await wsCmd(ws, 4, 'Page.navigate', { url });
        await wsWait(ws, 'Page.loadEventFired', 10000);
        await new Promise(r => setTimeout(r, 3000));
    }

    // Check for 大盘点金
    const text = await wsCmd(ws, 10, 'Runtime.evaluate', {
        expression: `document.body.innerText`,
        returnByValue: true
    });
    const bodyText = text?.result?.value || '';

    const hasDapan = bodyText.includes('大盘点金');
    const hasYang = bodyText.includes('阳谱');
    const hasYin = bodyText.includes('阴谱');

    console.log('  大盘点金 visible:', hasDapan);
    console.log('  阳谱 visible:', hasYang);
    console.log('  阴谱 visible:', hasYin);

    // Find 大盘点金 position
    const pos = await wsCmd(ws, 11, 'Runtime.evaluate', {
        expression: `(() => {
            const el = [...document.querySelectorAll('*')].find(e => e.innerText === '大盘点金' && e.children.length === 0);
            if (!el) return 'NOT_FOUND';
            const prev = el.closest('h1,h2,h3')?.innerText || '';
            const table = el.closest('table') || el.nextElementSibling?.querySelector('table');
            const rows = table ? table.querySelectorAll('tr').length : 0;
            return 'found, nearby title: ' + prev + ', table rows: ' + rows;
        })()`,
        returnByValue: true
    });
    console.log('  位置信息:', pos?.result?.value || 'N/A');

    // Screenshot
    const shot = await wsCmd(ws, 20, 'Page.captureScreenshot', { format: 'png' });
    if (shot?.data) {
        const filepath = `d:/AIProjects/TradingAgents-AShare/frontend/screenshots/${name.replace(/\s/g, '_')}.png`;
        writeFileSync(filepath, Buffer.from(shot.data, 'base64'));
        console.log('  Screenshot:', filepath);
    }

    ws.close();
    await new Promise(r => setTimeout(r, 500));
}

async function main() {
    console.log('=== 大盘点金 前端自测 ===');
    await testPage('Briefing', 'http://127.0.0.1:5173/briefing');
    await testPage('MarketAnalysis', 'http://127.0.0.1:5173/market-analysis');
    console.log('\n=== 完成 ===');
}

main().catch(e => console.error('FAIL:', e.message, e.stack));
