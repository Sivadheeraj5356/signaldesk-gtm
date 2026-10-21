const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({viewport:{width:1440,height:1000}});
  await ctx.addCookies([{name:'signaldesk_session',value:'MH1Q9TF2pujF_tYTH5uHcLP8NyRD1d5yy_cLhce6qcZD0k1QtViY0A',domain:'127.0.0.1',path:'/'}]);
  const p = await ctx.newPage();
  await p.goto('http://127.0.0.1:8787/',{waitUntil:'load',timeout:20000});
  await p.waitForTimeout(3500);
  await p.click('[data-tab="workflow"]');
  await p.waitForTimeout(1500);
  await p.evaluate(()=>window.scrollTo(0,document.body.scrollHeight));
  await p.waitForTimeout(700);
  await p.screenshot({path:'/tmp/iso-workflow-granted2.png'});
  await b.close();
})();
