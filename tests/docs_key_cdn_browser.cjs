const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const { chromium } = require(process.argv[2]);
const payload = JSON.parse(fs.readFileSync(0, 'utf8'));
const canary = 'REDIRECT_CANARY_823';
const spec = JSON.stringify({
  openapi: '3.0.0', info: { title: 'Redirect safety fixture', version: '1' },
  paths: { '/api/ping': { get: { responses: { 200: { description: 'OK' } } } } },
});
const listen = server => new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const close = server => new Promise(resolve => server.close(resolve));
const originOf = server => `http://127.0.0.1:${server.address().port}`;

(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
    args: ['--no-sandbox'],
  });
  const requests = [];
  const reply = (request, response) => {
    requests.push({ origin: request.headers.host, method: request.method,
      url: request.url, key: request.headers['x-functions-key'] ?? null });
    response.setHeader('Access-Control-Allow-Origin', '*');
    response.setHeader('Access-Control-Allow-Headers', 'x-functions-key,x-requested-with');
    if (request.method === 'OPTIONS') {
      response.writeHead(204).end();
      return;
    }
    response.writeHead(200, { 'Content-Type': 'application/json' });
    response.end(spec);
  };
  const destination = http.createServer(reply);
  await listen(destination);
  const server = http.createServer((request, response) => {
    if (request.url.startsWith('/api/docs')) {
      response.writeHead(200, { ...payload.headers, 'Content-Type': 'text/html' });
      response.end(payload.html);
    } else if (request.url === '/api/openapi.json' && payload.scenario !== 'normal') {
      requests.push({ origin: request.headers.host, method: request.method,
        url: request.url, key: request.headers['x-functions-key'] ?? null });
      const target = payload.scenario === 'cross-origin'
        ? `${originOf(destination)}/redirected-operation`
        : payload.scenario === 'chain' ? '/redirect-hop' : '/redirected-operation';
      response.writeHead(payload.status, { Location: target }).end();
    } else if (request.url === '/redirect-hop') {
      requests.push({ origin: request.headers.host, method: request.method,
        url: request.url, key: request.headers['x-functions-key'] ?? null });
      response.writeHead(308, { Location: `${originOf(destination)}/redirected-operation` }).end();
    } else {
      reply(request, response);
    }
  });
  await listen(server);
  const origin = originOf(server);
  try {
    const page = await browser.newPage();
    const failedAssets = [];
    const assetResponses = [];
    page.on('requestfailed', request => {
      if (request.url().startsWith('https://cdn.jsdelivr.net/')) {
        failedAssets.push(request.failure()?.errorText);
      }
    });
    page.on('response', response => {
      if (response.url().startsWith('https://cdn.jsdelivr.net/')) assetResponses.push(response);
    });
    // Observe the actual native-fetch options without changing their behavior.
    await page.addInitScript(() => {
      const nativeFetch = window.fetch;
      window.fetchCalls = [];
      window.fetch = (url, options) => {
        window.fetchCalls.push({ url: String(url), redirect: options?.redirect,
          key: options?.headers?.['x-functions-key'] });
        return nativeFetch(url, options);
      };
    });
    await page.goto(`${origin}/api/docs?keep=yes&code=${canary}#section`);
    if (await page.evaluate(() => typeof SwaggerUIBundle === 'undefined')) {
      const networkErrors = failedAssets.filter(error =>
        /ERR_(NAME_NOT_RESOLVED|CONNECTION|TIMED_OUT|INTERNET_DISCONNECTED)/.test(error));
      if (networkErrors.length) {
        process.stderr.write(`CDN unavailable: ${networkErrors.join(', ')}`);
        process.exitCode = 77;
        return;
      }
      throw new Error(`CDN bundle did not execute (including possible SRI failure): ${failedAssets}`);
    }
    assert.equal(await page.locator('script[src][integrity][crossorigin="anonymous"]').count(), 1);
    assert.ok(assetResponses.some(response =>
      response.url().includes('swagger-ui-dist@5.32.4/swagger-ui-bundle.js') && response.ok()));
    assert.equal(page.url(), `${origin}/api/docs?keep=yes#section`);
    assert.ok((await page.evaluate(() => performance.getEntriesByType('navigation')[0].name))
      .includes(`code=${canary}`));

    if (payload.scenario === 'normal') {
      await page.locator('.opblock-summary').click();
      await page.getByRole('button', { name: 'Execute', exact: true }).click();
      await page.locator('.responses-inner .response-col_status').filter({ hasText: '200' }).first()
        .waitFor();
      await page.evaluate(() => fetch('/favicon.ico'));
      assert.ok(requests.some(request => request.url === '/api/ping'));
      assert.ok(requests.some(request => request.url === '/favicon.ico'));
    } else {
      // Wait for Swagger's own completed download error, not merely a failed fetch event.
      await page.getByText('Failed to load API definition.').waitFor({ timeout: 15000 });
      assert.equal(await page.locator('.opblock').count(), 0);
    }
    const specRequests = requests.filter(request => request.url === '/api/openapi.json');
    assert.equal(specRequests.length, 1);
    assert.equal(specRequests[0].key, canary);
    const otherRequests = requests.filter(request => request.url !== '/api/openapi.json');
    assert.ok(otherRequests.every(request => request.key === null &&
      !new URL(request.url, origin).searchParams.has('code')));
    if (payload.scenario !== 'normal') {
      assert.ok(otherRequests.every(request => request.url === '/favicon.ico'));
    }
    const fetchCalls = await page.evaluate(() => window.fetchCalls);
    assert.equal(fetchCalls.find(request => request.key === canary).redirect, 'error');
    process.stdout.write(`PASS ${payload.scenario}/${payload.status}: ${JSON.stringify(requests)}\n`);
  } finally {
    process.stdout.write(`REQUEST_LOG ${JSON.stringify(requests)}\n`);
    await browser.close();
    await Promise.all([close(server), close(destination)]);
  }
})().catch(error => { process.stderr.write(error.stack); process.exitCode = 1; });
