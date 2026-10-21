const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const shots = [
    ['landing-d','http://localhost:8787/',{width:1280,height:900},null],
    ['landing-m','http://localhost:8787/',{width:390,height:844},null],
    ['signin-d','http://localhost:8787/sign-in',{width:1280,height:900},null],
  ];
  for (const [name,url,vp] of shots){
    const ctx = await b.newContext({viewport:vp, deviceScaleFactor:1});
    const p = await ctx.newPage();
    p.on('pageerror', e => console.log(name,'PAGE_ERR:', String(e).slice(0,200)));
    await p.goto(url,{waitUntil:'networkidle',timeout:20000}).catch(e=>console.log(name,'nav',e.message));
    await p.waitForTimeout(1200);
    await p.screenshot({path:'/tmp/sd-glasa-'+name+'.png'});
    console.log(name,'done');
    await ctx.close();
  }
  // authed dashboard
  const ctx = await b.newContext({viewport:{width:1280,height:900}});
  const p = await ctx.newPage();
  await p.goto('http://localhost:8787/sign-in',{waitUntil:'load'});
  await p.fill('#email','sivadheeraj5356@gmail.com');
  await p.fill('#password','local-test-password-123456');
  await p.click('button');
  await p.waitForTimeout(3500);
  console.log('after login url:', p.url());
  await p.screenshot({path:'/tmp/sd-glasa-dash-d.png'});
  const t = await p.evaluate(() => (document.querySelector('#page')||{innerText:'none'}).innerText.slice(0,120));
  console.log('dash content:', JSON.stringify(t));
  // mobile dash
  const ctx2 = await b.newContext({viewport:{width:390,height:844}});
  const p2 = await ctx2.newPage();
  await p2.goto('http://localhost:8787/sign-in',{waitUntil:'load'});
  await p2.fill('#email','sivadheeraj5356@gmail.com');
  await p2.fill('#password','local-test-password-123456');
  await p2.click('button');
  await p2.waitForTimeout(3500);
  await p2.screenshot({path:'/tmp/sd-glasa-dash-m.png'});
  console.log('dash-m done');
  await b.close();
})();
