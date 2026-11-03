import test from "node:test";
import assert from "node:assert/strict";
import { readFile, mkdir } from "node:fs/promises";
import { resolve } from "node:path";
import { chromium } from "playwright";
const url = process.env.VQCC_TEST_URL;
const keyFile = process.env.VQCC_TEST_KEY_FILE;
// Point this suite at an isolated fixture service: it creates/cancels local jobs
// and edits console configuration, but never starts a scheduler or model task.
test(
  "seven-page console, local workflow, configuration and mobile",
  { skip: !url || !keyFile, timeout: 120000 },
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
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    const shots = resolve(
      process.env.VQCC_SCREENSHOTS || "../../docs/screenshots",
    );
    await mkdir(shots, { recursive: true });
    try {
      await page.goto(url);
      await page.getByRole("heading", { name: "连接实验控制台" }).waitFor();
      await page
        .getByLabel("会话引导密钥")
        .fill((await readFile(keyFile, "utf8")).trim());
      await page.getByRole("button", { name: "进入工作空间" }).click();
      await page
        .getByRole("heading", { name: "实验总览", exact: true })
        .waitFor();
      await page.locator(".candidate-card").first().waitFor();
      await page.evaluate(() => document.fonts.ready);
      await page.screenshot({
        path: resolve(shots, "overview-desktop.png"),
        fullPage: true,
        animations: "disabled",
      });
      const get = async (path) =>
        (await page.request.get(`${url}/api/v1${path}`)).json();
      const experiments = (await get("/experiments?task=invsqrt")).data.items;
      assert(experiments.length >= 2, "fixture needs two InvSqrt candidates");
      const editable = experiments.find(
        (item) => typeof item.parameters?.delta_bits === "number",
      );
      assert(editable, "fixture needs an InvSqrt candidate with editable parameters");
      await page.goto(
        `${url}/#/experiments?compare=${experiments
          .slice(0, 2)
          .map((x) => x.id)
          .join(",")}`,
      );
      await page
        .getByRole("heading", { name: "同题比较", exact: true })
        .waitFor();
      assert.equal(await page.locator(".compare-table thead th").count(), 3);
      await page.screenshot({
        path: resolve(shots, "comparison-desktop.png"),
        fullPage: true,
        animations: "disabled",
      });
      await page.goto(`${url}/#/workbench?parent=${editable.id}`);
      await page.getByLabel("delta_bits", { exact: false }).waitFor();
      await page.getByText("所有可行优化均须验证。", { exact: false }).waitFor();
      assert.equal(await page.getByRole("option", { name: "仅生成与初筛" }).count(), 0);
      await page
        .getByLabel("实验假设与说明")
        .fill("浏览器验收：复制参数并排队，不运行计算");
      assert.equal(
        Number(
          await page.getByLabel("delta_bits", { exact: false }).inputValue(),
        ),
        editable.parameters.delta_bits,
      );
      const before = (await get("/jobs")).data.items.length;
      const fields = (await get("/parameter-schemas")).data.tasks.invsqrt
        .fields;
      const uncopied = Object.keys(editable.parameters).filter(
        (key) => !(key in fields),
      );
      if (uncopied.length) {
        await page
          .getByText(`未复制的参数：${uncopied.join("、")}`, { exact: false })
          .waitFor();
      }
      const previewRequest = page.waitForRequest(
        (request) =>
          request.url().endsWith("/jobs/preview") &&
          request.method() === "POST",
      );
      await page.getByRole("button", { name: "预检工作" }).click();
      assert.equal((await previewRequest).postDataJSON().validate, true);
      assert.deepEqual(
        Object.keys((await previewRequest).postDataJSON().parameters).sort(),
        Object.keys(fields).sort(),
        "copy only generator-supported editable parameters",
      );
      await page.getByRole("heading", { name: "确认并加入队列" }).waitFor();
      await page.screenshot({
        path: resolve(shots, "workbench-preview.png"),
        fullPage: true,
        animations: "disabled",
      });
      await page
        .getByRole("button", { name: "确认加入队列", exact: true })
        .click({ clickCount: 2 });
      await page.getByRole("link", { name: "查看队列中的任务" }).waitFor();
      const after = (await get("/jobs")).data.items;
      assert.equal(
        after.length,
        before + 1,
        "double click creates a single job",
      );
      const created = after.find(
        (j) => j.hypothesis === "浏览器验收：复制参数并排队，不运行计算",
      );
      assert(created);
      assert.equal(created.validate, true);
      assert(["queued", "blocked"].includes(created.state));
      await page.getByRole("link", { name: "查看队列中的任务" }).click();
      await page.getByRole("heading", { name: "这次任务的状态" }).waitFor();
      await page.getByRole("button", { name: "取消排队", exact: true }).click();
      await page
        .getByRole("status")
        .filter({ hasText: "排队已取消" })
        .waitFor();
      assert.equal(
        (await get(`/jobs/${created.job_id}`)).data.state,
        "cancelled",
      );
      await page.getByRole("link", { name: "返回任务列表" }).click();
      await page.getByRole("button", { name: "暂停后续自动任务" }).click();
      await page.getByRole("button", { name: "恢复自动调度" }).waitFor();
      assert.equal((await get("/overview")).data.scheduler.paused, true);
      await page.getByRole("button", { name: "恢复自动调度" }).click();
      await page.getByRole("button", { name: "暂停后续自动任务" }).waitFor();
      assert.equal((await get("/overview")).data.scheduler.paused, false);
      await page.goto(`${url}/#/config`);
      await page.getByLabel("每日顶层模型次数", { exact: false }).waitFor();
      const configBefore = (await get("/config")).data;
      await page
        .getByLabel("每日顶层模型次数", { exact: false })
        .fill(String(configBefore.config.daily_model_limit + 1));
      await page.getByLabel("磁盘余量（GiB）", { exact: false }).fill("20");
      await page.getByRole("button", { name: "预览配置差异" }).click();
      await page.getByRole("button", { name: "确认保存新版本" }).click();
      await page
        .getByRole("status")
        .filter({ hasText: "配置新版本已保存" })
        .waitFor();
      assert.equal(
        (await get("/config")).data.revision,
        configBefore.revision + 1,
      );
      await page.goto(`${url}/#/research`);
      await page
        .getByRole("heading", { name: "研究假设", exact: true })
        .waitFor();
      await page.locator(".research-card").first().waitFor();
      const research = page.locator(".research-card").first();
      await research.getByRole("button", { name: "编辑状态与备注" }).click();
      await research.getByLabel("备注", { exact: true }).fill("浏览器验收备注");
      await research.getByRole("button", { name: "保存变更" }).click();
      await research
        .getByRole("status")
        .filter({ hasText: "研究记录已保存" })
        .waitFor();
      assert(
        (await get("/research")).data.items.some(
          (i) => i.notes === "浏览器验收备注",
        ),
      );
      await page.goto(`${url}/#/submissions`);
      await page.getByRole("heading", { name: "每日提交台账" }).waitFor();
      await page.screenshot({
        path: resolve(shots, "submissions-desktop.png"),
        fullPage: true,
        animations: "disabled",
      });
      await page.setViewportSize({ width: 390, height: 844 });
      await page.goto(`${url}/#/`);
      await page
        .getByRole("heading", { name: "实验总览", exact: true })
        .waitFor();
      await page.locator(".candidate-card").first().waitFor();
      assert(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
        "mobile page must not overflow horizontally",
      );
      await page.screenshot({
        path: resolve(shots, "overview-mobile.png"),
        fullPage: true,
        animations: "disabled",
      });
      await page.getByRole("button", { name: "打开导航" }).click();
      await page.getByRole("button", { name: "退出会话" }).click();
      await page.getByRole("heading", { name: "连接实验控制台" }).waitFor();
      assert.equal(
        (await page.request.get(`${url}/api/v1/overview`)).status(),
        401,
      );
      assert.deepEqual(errors, [], "no browser runtime exceptions");
    } catch (error) {
      await mkdir("test-results", { recursive: true });
      await page.screenshot({
        path: resolve("test-results", "failure.png"),
        fullPage: true,
        animations: "disabled",
      });
      console.error(
        "Page notices:",
        await page.locator(".notice").allTextContents(),
      );
      throw error;
    } finally {
      await browser.close();
    }
  },
);
