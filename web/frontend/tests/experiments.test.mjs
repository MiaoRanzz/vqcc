import test from "node:test";
import assert from "node:assert/strict";
import { chromium } from "playwright";

const url = process.env.VQCC_EXPERIMENTS_TEST_URL;

// All API requests are intercepted; only static assets come from the server.
test("experiment loading, failures, empty filters and navigation retain honest state", {
  skip: !url, timeout: 45000,
}, async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.CHROMIUM_PATH || "/root/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome",
    args: ["--no-sandbox"],
  });
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  let mode = "loading";
  const errors = [], writes = [];
  try {
    const page = await browser.newPage();
    page.setDefaultTimeout(5000);
    page.on("pageerror", (error) => errors.push(error.message));
    const records = ["first", "second", "third"].map((id) => ({
      id, task: "invsqrt", hypothesis: id, validation_status: "PASS",
      official_cost: 100, created_at: "2026-11-03T09:00:00+08:00",
    }));
    await page.route("**/api/v1/**", async (route) => {
      const request = route.request();
      const endpoint = new URL(request.url());
      if (request.method() !== "GET") {
        writes.push(request.url());
        await route.fulfill({status: 405, json: {message: "Read-only test"}});
      } else if (endpoint.pathname.endsWith("/session")) {
        await route.fulfill({json: {csrf_token: "fixture", read_only: true}});
      } else if (endpoint.pathname.endsWith("/events")) {
        await route.fulfill({contentType: "text/event-stream", body: ": fixture\n\n"});
      } else if (endpoint.pathname.endsWith("/experiments")) {
        if (mode === "loading") await gate;
        if (mode === "error") {
          await route.fulfill({status: 503, json: {message: "实验服务暂时不可用"}});
          return;
        }
        const cursor = Number(endpoint.searchParams.get("cursor") || 0);
        const filtered = endpoint.searchParams.get("query") ? [] : records;
        await route.fulfill({json: {
          data: {items: filtered.slice(cursor, cursor + 2), total: filtered.length,
            next_cursor: cursor + 2 < filtered.length ? String(cursor + 2) : null},
          observed_at: "2026-11-03T01:00:00Z", revision: 1,
          freshness: "fresh", consistency: "consistent",
        }});
      } else {
        await route.fulfill({status: 404, json: {message: "Unknown fixture endpoint"}});
      }
    });
    await page.goto(`${url}/#/experiments`);
    await page.getByText("正在加载实验记录…", {exact: true}).waitFor();
    assert.equal(await page.locator(".empty").count(), 0);

    mode = "error";
    release();
    await page.getByRole("alert").filter({hasText: "实验列表读取失败"}).waitFor();
    assert.equal(await page.locator(".empty").count(), 0);

    mode = "ready";
    await page.getByRole("button", {name: "重试读取实验"}).click();
    await page.getByText("当前显示 2 条，共 3 条匹配记录").waitFor();
    await page.getByRole("link", {name: "first", exact: true}).waitFor();
    await page.getByRole("button", {name: "下一页 →"}).click();
    await page.getByRole("link", {name: "third", exact: true}).waitFor();
    assert(new URL(page.url()).hash.includes("cursor=2"));

    await page.getByRole("navigation").getByRole("link", {name: "实验与证据", exact: true}).click();
    await page.getByRole("link", {name: "first", exact: true}).waitFor();
    assert.equal(await page.locator("tbody tr").count(), 2);

    await page.getByLabel("搜索全部实验").fill("no-match");
    await page.getByRole("button", {name: "搜索", exact: true}).click();
    await page.getByText("当前筛选或分页没有匹配记录", {exact: false}).waitFor();
    await page.getByRole("button", {name: "显示全部实验"}).click();
    await page.getByRole("link", {name: "first", exact: true}).waitFor();
    assert.equal(await page.getByLabel("搜索全部实验").inputValue(), "");

    mode = "error";
    await page.evaluate(() => window.dispatchEvent(new Event("console-update")));
    await page.getByRole("alert").filter({hasText: "实验列表读取失败"}).waitFor();
    assert.equal(await page.locator("tbody tr").count(), 2);
    assert.equal(await page.locator(".empty").count(), 0);
    assert.deepEqual(errors, []);
    assert.deepEqual(writes, []);
  } finally {
    release();
    await browser.close();
  }
});
