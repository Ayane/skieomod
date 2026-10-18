// Read-only landing-page QA; token mutations are allowed only on the local fixture.
const assert = require('node:assert/strict');
const playwright = require(process.env.CUSTOM_MAP_PLAYWRIGHT || 'playwright');

(async () => {
  const browserName = process.env.CUSTOM_MAP_BROWSER || 'firefox';
  assert(['chromium', 'firefox'].includes(browserName));
  const browser = await playwright[browserName].launch({headless: true,
    ...(process.env.CUSTOM_MAP_BROWSER_EXECUTABLE ? {executablePath: process.env.CUSTOM_MAP_BROWSER_EXECUTABLE} : {}),
    args: browserName === 'chromium' ? ['--no-sandbox'] : []});
  try {
    const base = process.env.CUSTOM_MAP_WEB_URL || 'https://skieomod.emillon.fr';
    const page = await browser.newPage({viewport: {width: 1440, height: 1000}, locale: 'fr-FR'});
    const errors = [], requests = [];
    page.on('pageerror', e => errors.push(e.message));
    page.on('request', req => requests.push(req.url()));
    await page.addInitScript(() => {
      window.customMapCspViolations = [];
      document.addEventListener('securitypolicyviolation', e => window.customMapCspViolations.push(e.effectiveDirective));
    });
    const response = await page.goto(base);
    assert.equal(response.status(), 200);
    assert.match(response.headers()['content-security-policy'], /(?:^|;)\s*script-src 'self'\s*(?:;|$)/);
    await page.waitForSelector('.hero h1');
    assert.equal(await page.locator('.topbar').evaluate(e => getComputedStyle(e).display), 'flex');
    assert.equal(await page.locator('.hero').evaluate(e => getComputedStyle(e).backgroundColor), 'rgb(16, 38, 41)');
    assert.equal(await page.locator('.creation-card').count(), 0);
    assert(!requests.some(url => url.includes('/api/')), 'landing page depends on the old catalogue API');
    assert.deepEqual(await page.evaluate(() => [...document.scripts].filter(e => !e.src).map(e => e.textContent)), []);
    assert.deepEqual(await page.evaluate(() => [...document.querySelectorAll('*')].flatMap(e => [...e.attributes].filter(a => /^on/i.test(a.name)).map(a => a.name))), []);
    assert.match(await page.locator('#installer').innerText(), /pipx install --force --index-url https:\/\/skieomod.emillon.fr/);
    assert.equal(await page.locator('.tutorial-card').count(), 5);
    for (const path of ['editor', 'heightmap', 'scripts', 'mapmods', 'ticket-office']) {
      const tutorial = await page.request.get(base + '/tutorials/' + path + '/');
      assert.equal(tutorial.status(), 200);
      const html = await tutorial.text();
      assert.match(html, /<!doctype html>/i);
      assert(!html.includes('<app-root>'), 'tutorial route returned the landing page');
    }
    await page.getByLabel('Langue', {exact: true}).selectOption('en');
    assert.equal(await page.locator('html').getAttribute('lang'), 'en');
    assert.match(await page.locator('#publier').innerText(), /Web publishing remains available/);
    await page.reload(); await page.waitForSelector('.hero');
    assert.equal(await page.locator('html').getAttribute('lang'), 'en');
    await page.setViewportSize({width: 390, height: 844});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    await page.screenshot({path: process.env.CUSTOM_MAP_SCREENSHOT || '/tmp/skieomod-tools/site-mobile.png', fullPage: true});
    if (new URL(base).hostname === '127.0.0.1') {
      await page.context().addCookies([{name: 'custom_map_session', value: 'browser-test-session', url: base}]);
      await page.goto(base + '/account');
      await page.waitForSelector('#token-label');
      await page.locator('#token-label').fill('Browser QA');
      await page.getByRole('button', {name: 'Create token', exact: true}).click();
      await page.waitForSelector('.tokens li');
      assert.equal(await page.locator('.tokens li').count(), 1);
      assert((await page.locator('.code-block code').innerText()).length > 30);
      await page.getByRole('button', {name: 'Revoke', exact: true}).click();
      await page.waitForFunction(() => document.querySelectorAll('.tokens li').length === 0);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    }
    assert.deepEqual(await page.evaluate(() => window.customMapCspViolations), []);
    assert.deepEqual(errors, []);
    console.log(`${browserName}: landing page, installation, tutorials, strict CSP, FR/EN persistence, mobile and local token lifecycle OK`);
  } finally {await browser.close();}
})().catch(e => {console.error(e); process.exit(1);});
