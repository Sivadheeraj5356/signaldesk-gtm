const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const d = await (await b.newContext({viewport:{width:1440,height:900}})).newPage();
  await d.goto('http://127.0.0.1:8787/',{waitUntil:'load',timeout:20000});
  await d.waitForTimeout(1500);
  await d.screenshot({path:'/tmp/fix-landing-d.png'});
  await d.goto('http://127.0.0.1:8787/sign-in',{waitUntil:'load',timeout:20000});
  await d.waitForTimeout(1200);
  await d.screenshot({path:'/tmp/fix-signin-d.png'});
  const m = await (await b.newContext({viewport:{width:390,height:844}})).newPage();
  await m.goto('http://127.0.0.1:8787/',{waitUntil:'load',timeout:20000});
  await m.waitForTimeout(1500);
  await m.screenshot({path:'/tmp/fix-landing-m.png'});
  const ov = await m.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  console.log('mobile overflow px:', ov);
  await b.close();
})();
