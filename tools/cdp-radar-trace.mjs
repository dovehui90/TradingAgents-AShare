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
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

async function main() {
    const tabs = await cdpReq('GET', '/json/list');
    const tab = tabs.find(t => t.url && t.url.includes('5174'));
    if (!tab) { console.log('No 5174 tab'); return; }

    const ws = new WebSocket(tab.webSocketDebuggerUrl);
    await new Promise((r, reject) => { const t=setTimeout(()=>reject(new Error('ws')),5000); ws.onopen=()=>{clearTimeout(t);r();}; });
    await rpc(ws, 'Runtime.enable');

    // Patch setData on all LineSeries and HistogramSeries prototypes BEFORE switching
    // Also patch createChart to track instances
    const patchResult = await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            // Find lightweight charts module scope by traversing canvas parents
            const containers = document.querySelectorAll('.tv-lightweight-charts');
            if (!containers.length) return 'no chart divs';

            // Instead, let's intercept at a higher level - patch the canvas rendering
            // We can't easily access chart instances, so let's check via React DevTools or fiber

            // Try to find chart instances via DOM event listeners or properties
            // lightweight-charts stores some refs on the container div

            // Alternative: just check what data is on the canvas by examining
            // the chart's internal table structure
            const radarContainer = Array.from(containers).find(c => {
                const card = c.closest('.card');
                return card && card.textContent.includes('主力趋势雷达');
            });

            if (!radarContainer) return 'no radar container';

            // Check internal chart structure
            const tables = radarContainer.querySelectorAll('table');
            const rows = radarContainer.querySelectorAll('tr');
            const cells = radarContainer.querySelectorAll('td');

            // The chart data rows typically contain price scale labels and time scale labels
            let timeLabels = [];
            let priceLabels = [];
            for (const td of cells) {
                const text = td.textContent.trim();
                if (text && text.length > 0) {
                    if (/^\\d/.test(text) || /^[一二三四五六日]/.test(text)) {
                        timeLabels.push(text);
                    }
                    if (/^[\\d.-]+$/.test(text) && text.length > 1) {
                        priceLabels.push(text);
                    }
                }
            }

            return JSON.stringify({
                tableCount: tables.length,
                rowCount: rows.length,
                cellCount: cells.length,
                timeLabels: timeLabels.slice(0, 10),
                priceLabels: priceLabels.slice(0, 10),
            });
        })()`,
        returnByValue: true
    });
    console.log('Chart internal structure:', patchResult.result?.value);

    // Now switch to 周K and check
    console.log('\n--- Switching to 周K ---');
    await rpc(ws, 'Runtime.evaluate', {
        expression: `document.querySelectorAll('button').forEach(b => { if(b.textContent.trim()==='周K') b.click(); })`,
        returnByValue: true
    });
    await sleep(4000);

    // Check after switch
    const afterSwitch = await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            const containers = document.querySelectorAll('.tv-lightweight-charts');
            const radarContainer = Array.from(containers).find(c => {
                const card = c.closest('.card');
                return card && card.textContent.includes('主力趋势雷达');
            });
            if (!radarContainer) return 'no radar container';

            const cells = radarContainer.querySelectorAll('td');
            let timeLabels = [];
            let priceLabels = [];
            for (const td of cells) {
                const text = td.textContent.trim();
                if (text && text.length > 0) {
                    if (/^\\d/.test(text)) timeLabels.push(text);
                    if (/^[\\d.-]+$/.test(text) && text.length > 1) priceLabels.push(text);
                }
            }

            // Also get full internal HTML for first 500 chars
            const innerPart = radarContainer.innerHTML.substring(0, 800);

            return JSON.stringify({
                timeLabels: timeLabels.slice(0, 15),
                priceLabels: priceLabels.slice(0, 10),
                innerHTML: innerPart,
            });
        })()`,
        returnByValue: true
    });
    console.log('After 周K switch:', afterSwitch.result?.value);

    ws.close(1000);
}
main().catch(e => console.error(e.message));
