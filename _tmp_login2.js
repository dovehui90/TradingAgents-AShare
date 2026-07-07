const http = require('http');
const fs = require('fs');

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

async function main() {
  // Use existing tab
  const ws = new WebSocket('ws://127.0.0.1:9222/devtools/page/994070B5737E2260CAB53FB12E79A81A');
  const messages = [];

  ws.onmessage = (event) => {
    messages.push(JSON.parse(event.data));
  };

  await new Promise(r => ws.onopen = r);
  console.log('Connected to existing tab');

  function ev(expr) {
    return new Promise(resolve => {
      const id = Math.random();
      ws.send(JSON.stringify({id, method:'Runtime.evaluate', params:{expression: expr, returnByValue: true}}));
      const check = () => {
        const m = messages.find(x => x.id === id);
        if(m) resolve(m.result);
        else setTimeout(check, 200);
      };
      setTimeout(check, 200);
    });
  }

  // Check current state
  let r = await ev(`JSON.stringify({url:location.href, title:document.title, inputs:[...document.querySelectorAll('input')].map(i=>({type:i.type,placeholder:i.placeholder,value:i.value})), buttons:[...document.querySelectorAll('button')].map(b=>b.textContent.trim())})`);
  console.log('State:', JSON.parse(r.result.value));

  // Step 1: Enter email in the input field
  r = await ev(`(function(){
    const inp = document.querySelector('input[type="email"]') || document.querySelector('input');
    if(!inp) return 'no input';
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
    setter.call(inp, 'admin@tradingagents.com');
    inp.dispatchEvent(new Event('input', { bubbles: true }));
    inp.dispatchEvent(new Event('change', { bubbles: true }));
    return 'filled: ' + inp.value;
  })()`);
  console.log('Email:', r.result.value);

  await sleep(500);

  // Step 2: Click send verification code button
  r = await ev(`(function(){
    const btns = [...document.querySelectorAll('button')];
    const btn = btns.find(b => b.textContent.includes('发送') || b.textContent.includes('验证码'));
    if(!btn) return 'no send button: ' + btns.map(b=>b.textContent.trim()).join('|');
    btn.click();
    return 'clicked';
  })()`);
  console.log('Send button:', r.result.value);

  // Wait for code to appear
  await sleep(3000);

  // Step 3: Read the verification code from the page
  r = await ev(`(function(){
    const body = document.body.innerText;
    // Look for 6-digit code pattern
    const match = body.match(/\\b\\d{6}\\b/);
    // Also check for any shown code element
    const codeEl = document.querySelector('[class*="code"], [class*="Code"], [class*="token"], [class*="Token"], [class*="verify"]');
    let codeText = codeEl ? codeEl.textContent : '';
    let inputs = [...document.querySelectorAll('input')].map(i=>({type:i.type,placeholder:i.placeholder,value:i.value}));
    return JSON.stringify({body: body.substring(0, 500), match: match ? match[0] : null, codeText, inputs});
  })()`);
  console.log('Code search:', r.result.value);

  // Take screenshot
  ws.send(JSON.stringify({id:'ss', method:'Page.captureScreenshot', params:{format:'png'}}));
  await sleep(2000);
  const ss = messages.find(m => m.id === 'ss');
  if(ss && ss.result) {
    fs.writeFileSync('d:/AIProjects/TradingAgents-AShare/frontend/screenshots/login_step2.png', Buffer.from(ss.result.data, 'base64'));
    console.log('Screenshot saved');
  }

  ws.close();
  process.exit(0);
}

main().catch(e => { console.error(e); process.exit(1); });
setTimeout(() => { console.log('Timeout'); process.exit(1); }, 30000);
