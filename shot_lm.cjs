const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const p = await (await b.newContext({viewport:{width:390,height:844}})).newPage();
  await p.goto('http://127.0.0.1:8787/',{waitUntil:'load',timeout:20000});
  await p.waitForTimeout(1500);
  await p.screenshot({path:'/tmp/sd-glasa-landing-m2.png'});
  const overflow = await p.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  console.log('horizontal overflow px:', overflow);
  await b.close();
})();
