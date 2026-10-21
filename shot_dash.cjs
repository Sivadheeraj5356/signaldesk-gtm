const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({viewport:{width:1280,height:900}});
  const p = await ctx.newPage();
  const r = await p.goto('http://localhost:8787/sign-in',{waitUntil:'load'});
  console.log('status', r.status());
  const html = await p.content();
  console.log('has email input:', html.includes('id="email"'), 'len', html.length);
  if(!html.includes('id="email"')){ console.log(html.slice(0,300)); await b.close(); return; }
  await p.fill('#email','sivadheeraj5356@gmail.com');
  await p.fill('#password','local-test-password-123456');
  await p.click('button');
  await p.waitForTimeout(4000);
  console.log('after login url:', p.url());
  await p.screenshot({path:'/tmp/sd-glasa-dash-d.png'});
  const t = await p.evaluate(() => (document.querySelector('#page')||{innerText:'none'}).innerText.slice(0,120));
  console.log('dash content:', JSON.stringify(t));
  await b.close();
})();
