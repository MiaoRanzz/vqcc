import test from "node:test";
import assert from "node:assert/strict";
import { readFile, mkdir } from "node:fs/promises";
import { resolve } from "node:path";
import { chromium } from "playwright";

const url = process.env.VQCC_POLICY_TEST_URL;
const keyFile = process.env.VQCC_POLICY_TEST_KEY_FILE;

test(
  "after-optimization quota is distinct from the model budget",
  {
    skip: !url || !keyFile,
    timeout: 60000,
  },
  async () => {
    const browser = await chromium.launch({
      headless: true,
      executablePath:
        process.env.CHROMIUM_PATH ||
        "/root/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome",
      args: ["--no-sandbox"],
    });
    const page = await browser.newPage({
      viewport: { width: 1440, height: 1050 },
    });
    if (process.env.VQCC_TEST_FONT_FILE) {
      const font = (await readFile(process.env.VQCC_TEST_FONT_FILE)).toString(
        "base64",
      );
      await page.addInitScript(
        (value) =>
          document.addEventListener("DOMContentLoaded", () => {
            const style = document.createElement("style");
            style.textContent =
              "@font-face{font-family:ReviewCJK;src:url(data:font/otf;base64," +
              value +
              ")}body{font-family:Inter,-apple-system,ReviewCJK,sans-serif!important}";
            document.head.append(style);
          }),
        font,
      );
    }
    const errors = [],
      writes = [];
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("request", (request) => {
      if (request.method() !== "GET" && !request.url().endsWith("/session"))
        writes.push(request.url());
    });
    const shots = resolve(
      process.env.VQCC_SCREENSHOTS || "../../docs/screenshots",
    );
    await mkdir(shots, { recursive: true });
    try {
      await page.goto(url);
      await page
        .getByLabel("会话引导密钥")
        .fill((await readFile(keyFile, "utf8")).trim());
      await page.getByRole("button", { name: "进入工作空间" }).click();
      await page
        .getByRole("heading", { name: "实验总览", exact: true })
        .waitFor();
      await page.locator(".candidate-card").first().waitFor();
      const { data } = await (
        await page.request.get(`${url}/api/v1/submissions`)
      ).json();
      assert.equal(data.eligibility.policy, "after_optimization");
      assert.equal(data.eligibility.daily_limit, 5);
      const quota = `${data.eligibility.successes_today} / ${data.eligibility.daily_limit}`;
      assert.equal(
        await page
          .locator(".metric")
          .filter({ hasText: "当日成功提交 / 本地上限" })
          .locator("strong")
          .textContent(),
        quota,
      );
      assert(
        (
          await page
            .locator(".metric")
            .filter({ hasText: "当日成功提交 / 本地上限" })
            .textContent()
        ).includes(data.eligibility.quota_timezone),
      );
      assert.equal(
        await page.getByText("下一提交窗口", { exact: true }).count(),
        0,
      );
      await page.evaluate(() => document.fonts.ready);
      await page.screenshot({
        path: resolve(shots, "overview-desktop.png"),
        fullPage: true,
        animations: "disabled",
      });
      await page.goto(`${url}/#/submissions`);
      await page.getByRole("heading", { name: "每日提交台账" }).waitFor();
      await page.getByText("无固定时段", { exact: false }).waitFor();
      assert.equal(
        await page.getByRole("button", { name: "请求提交当前改进" }).count(),
        1,
      );
      assert.equal(
        await page.getByText("北京时间今日名额", { exact: true }).count(),
        0,
      );
      await page.evaluate(() => document.fonts.ready);
      await page.screenshot({
        path: resolve(shots, "submissions-desktop.png"),
        fullPage: true,
        animations: "disabled",
      });
      await page.goto(`${url}/#/config`);
      await page.getByRole("heading", { name: "自动提交与平台配额" }).waitFor();
      const { data: usage } = await (
        await page.request.get(`${url}/api/v1/usage`)
      ).json();
      assert.equal(
        await page
          .locator(".metric")
          .filter({ hasText: "今日已占用模型次数" })
          .locator("strong")
          .textContent(),
        `${usage.reserved} / ${usage.limit}`,
      );
      assert(
        (
          await page
            .getByRole("heading", { name: "自动提交与平台配额" })
            .locator("..")
            .locator("..")
            .textContent()
        ).includes("不自动增加模型预算"),
      );
      await page.setViewportSize({ width: 390, height: 844 });
      await page.goto(`${url}/#/`);
      await page.locator(".candidate-card").first().waitFor();
      assert(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      );
      await page.evaluate(() => document.fonts.ready);
      await page.screenshot({
        path: resolve(shots, "overview-mobile.png"),
        fullPage: true,
        animations: "disabled",
      });
      assert.deepEqual(
        writes,
        [],
        "read-only review must not create jobs or configuration revisions",
      );
      assert.deepEqual(errors, []);
    } finally {
      await browser.close();
    }
  },
);
