const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const { chromium } = require(process.argv[2]);
const payload = JSON.parse(fs.readFileSync(0, 'utf8'));

(async () => {
  let browser;
  try {
    browser = await chromium.launch({ headless: true });
  } catch (error) {
    if (error.message.includes("Executable doesn't exist")) {
      process.stderr.write('Chromium executable not installed');
      process.exitCode = 77;
      return;
    }
    throw error;
  }
  const requests = [];
  const server = http.createServer((request, response) => {
    if (request.url.startsWith('/api/docs')) {
      response.writeHead(200, { ...payload.headers, 'Content-Type': 'text/html' });
      response.end(payload.html);
    } else {
      requests.push({ url: request.url, key: request.headers['x-functions-key'] });
      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.end('{"openapi":"3.0.0","info":{"title":"stub","version":"1"},"paths":{}}');
    }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const origin = `http://127.0.0.1:${server.address().port}`;
  try {
    const page = await browser.newPage();
    await page.route('https://cdn.jsdelivr.net/**', route => route.abort());
    await page.addInitScript(() => {
      window.SwaggerUIBundle = config => {
        window.intercept = config.requestInterceptor;
        const spec = config.requestInterceptor({ url: config.url, loadSpec: true, headers: {} });
        window.specDone = fetch(spec.url, { headers: spec.headers }).then(response => response.json());
        return {};
      };
      window.SwaggerUIBundle.presets = { apis: {} };
    });
    for (const query of ['?keep=yes&code=CANARY_KEY_9f3a&code=SECOND', '?keep=yes', '?keep=yes&code=']) {
      await page.goto('about:blank');
      await page.goto(`${origin}/api/docs${query}#section`);
      await page.evaluate(() => window.specDone);
      assert.equal(page.url(), `${origin}/api/docs?keep=yes#section`);
      const specRequest = requests.filter(request => request.url === '/api/openapi.json').at(-1);
      assert.equal(specRequest.key, query.includes('CANARY') ? 'CANARY_KEY_9f3a' : undefined);
      assert.ok(!specRequest.url.includes('code='));
      const leaked = await page.evaluate(() => {
        const urls = [
          ['/api/operation', false], ['/api/openapi.json', false],
          ['https://evil.example/api/openapi.json', true],
          [`//${window.location.host}/api/openapi.json`, true],
          ['/api/openapi.json?other=1', true], ['https://[broken', true],
        ];
        return urls.some(([url, loadSpec]) =>
          'x-functions-key' in window.intercept({ url, loadSpec, headers: {} }).headers);
      });
      assert.equal(leaked, false);
    }
    process.stdout.write('PASS: address redacted; spec header only; operation and cross-origin keys absent\n');
  } finally {
    await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => { process.stderr.write(error.stack); process.exitCode = 1; });
