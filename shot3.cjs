const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const p = await (await b.newContext({viewport:{width:1440,height:900}})).newPage();
  await p.goto('http://127.0.0.1:8787/sign-in',{waitUntil:'load',timeout:20000});
  await p.waitForTimeout(1000);
  const vis = await p.evaluate(() => {
    const g = document.getElementById('google');
    return g ? getComputedStyle(g).display : 'missing';
  });
  console.log('google button display when disabled:', vis);
  await p.screenshot({path:'/tmp/fix-signin-d2.png'});
  await b.close();
})();
