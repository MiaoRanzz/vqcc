import test from "node:test";
import assert from "node:assert/strict";
import { readFile, mkdir } from "node:fs/promises";
import { resolve } from "node:path";
import { chromium } from "playwright";

const url = process.env.VQCC_USABILITY_TEST_URL;
const keyFile = process.env.VQCC_USABILITY_TEST_KEY_FILE;

test(
  "task explanations, visible job details, queue reasons and separate budgets",
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
      viewport: { width: 1440, height: 1100 },
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
    const screenshot = async (name) => {
      await page.evaluate(() => document.fonts.ready);
      await page.screenshot({
        path: resolve(shots, name),
        fullPage: true,
        animations: "disabled",
      });
    };
    try {
      await page.goto(url);
      await page
        .getByLabel("会话引导密钥")
        .fill((await readFile(keyFile, "utf8")).trim());
      await page.getByRole("button", { name: "进入工作空间" }).click();
      await page.locator(".candidate-card").first().waitFor();
      const get = async (path) =>
        (await (await page.request.get(`${url}/api/v1${path}`)).json()).data;
      const overview = await get("/overview");
      assert.equal(
        overview.queue.queued,
        0,
        "review fixture has no queued work",
      );
      await page
        .getByRole("heading", { name: "队列与下一次自动运行" })
        .waitFor();
      assert(
        (await page.locator(".queue-summary").textContent()).includes(
          overview.queue.message,
        ),
      );
      assert(
        (await page.locator(".queue-summary").textContent()).includes(
          "不能相加",
        ),
      );
      const activity = await page.locator(".submission-activity").textContent();
      assert(activity.includes(overview.submission_activity.message));
      if (overview.submission_activity.report_excerpt)
        assert(activity.includes(overview.submission_activity.report_excerpt));
      assert.equal(
        await page
          .getByRole("heading", { name: "服务器资源与任务占用" })
          .count(),
        1,
      );
      assert(
        (await page.locator(".task-resource-summary").textContent()).includes(
          overview.resources.task.reason,
        ),
      );
      assert(
        (await page.locator(".resource-scope").textContent()).includes(
          "其他项目",
        ),
      );
      await page.getByText("这些数字怎么比较？", { exact: true }).click();
      assert(
        (await page.locator(".metric-explainer").textContent()).includes(
          "几何平均",
        ),
      );
      await screenshot("overview-desktop.png");
      await page
        .getByRole("navigation")
        .getByRole("link", { name: "任务介绍", exact: true })
        .click();
      await page
        .getByRole("heading", { name: "任务介绍", exact: true })
        .waitFor();
      assert.equal(await page.locator(".task-guide").count(), 3);
      for (const text of [
        "R(ε₊) × Q² × Toffoli",
        "Q × (Toffoli + T / 4)",
        "λ_eff × T_total × Q_total",
      ])
        assert((await page.locator("main").textContent()).includes(text));
      await page
        .locator(".task-tabs")
        .getByRole("link", { name: "InvSqrt", exact: true })
        .click();
      await page.waitForFunction(
        () => document.querySelectorAll(".task-guide").length === 1,
      );
      assert.equal(await page.locator(".task-guide").count(), 1);
      await page.reload();
      await page.locator(".task-guide").waitFor();
      assert(
        (await page.locator(".task-guide").textContent()).includes("3,133,452"),
      );
      await page.getByRole("img", { name: /invsqrt 官方成本历史/i }).waitFor();
      assert.equal(await page.locator(".task-history .history-chart").count(), 1);
      assert(
        (await page.locator(".task-history").textContent()).includes("正式 PASS"),
      );
      await page.getByText(/全部正式 PASS 分数/).click();
      assert((await page.locator(".history-details table tbody tr").count()) >= 2);
      await screenshot("tasks-desktop.png");
      await page.goto(`${url}/#/jobs?state=completed`);
      await page
        .getByRole("heading", { name: "任务记录", exact: true })
        .waitFor();
      const jobs = (await get("/jobs?state=completed")).items;
      assert(jobs.length, "fixture needs a completed job");
      const job = jobs.find((item) => item.run_id) || jobs[0];
      const row = page.locator("tr").filter({ hasText: job.job_id });
      await row.getByRole("link", { name: "查看详情 →", exact: true }).click();
      await page.getByRole("heading", { name: "这次任务的状态" }).waitFor();
      assert(
        (await page.locator(".page-heading h1").textContent()).includes(
          "任务详情",
        ),
      );
      assert(
        (await page.locator(".page-heading h1").boundingBox()).y < 400,
        "job detail must be visible immediately",
      );
      assert.equal(
        await page
          .getByRole("heading", { name: "任务记录", exact: true })
          .count(),
        0,
        "detail is a dedicated view, not appended under the table",
      );
      if (job.run_id)
        await page
          .getByRole("heading", { name: "运行报告与实验结果" })
          .waitFor();
      await screenshot("job-detail-desktop.png");
      await page.getByRole("link", { name: "返回任务列表" }).click();
      await page
        .getByRole("heading", { name: "任务记录", exact: true })
        .waitFor();
      assert.equal(
        await page.getByLabel("筛选任务状态").inputValue(),
        "completed",
      );
      await page.goto(`${url}/#/jobs?id=${job.job_id}`);
      await page.reload();
      await page.getByRole("heading", { name: "这次任务的状态" }).waitFor();
      await page.goto(`${url}/#/jobs`);
      const jobPath = `**/api/v1/jobs/${job.job_id}`;
      await page.route(jobPath, (route) => route.abort("failed"));
      await page.goto(`${url}/#/jobs?id=${job.job_id}`);
      await page.getByRole("heading", { name: "任务读取失败" }).waitFor();
      await page.unroute(jobPath);
      await page.getByRole("button", { name: "重试读取任务" }).click();
      await page.getByRole("heading", { name: "这次任务的状态" }).waitFor();
      await page.goto(`${url}/#/jobs`);
      await page.route(jobPath, async (route) => {
        await new Promise((resolve) => setTimeout(resolve, 700));
        try {
          await route.continue();
        } catch (error) {
          if (!String(error).includes("Route is already handled")) throw error;
        }
      });
      await page.goto(`${url}/#/jobs?id=${job.job_id}`);
      await page
        .getByRole("status")
        .filter({ hasText: "正在读取这次任务" })
        .waitFor();
      await page.getByRole("heading", { name: "这次任务的状态" }).waitFor();
      await page.unroute(jobPath);
      await page.goto(`${url}/#/config`);
      await page
        .getByRole("heading", { name: "为提交与对账保留的模型次数" })
        .waitFor();
      const usage = await get("/usage");
      const allocations = await page
        .locator(".reservation-grid>div strong")
        .allTextContents();
      assert.deepEqual(
        allocations.map((text) => text.replace(/\s/g, "")),
        [`${usage.reserve_submit}次`, `${usage.reserve_reconcile}次`],
      );
      assert(
        (await page.locator(".reservation-explanation").textContent()).includes(
          "两个独立配置值",
        ),
      );
      assert.equal(
        await page.getByText("提交 / 对账预留", { exact: true }).count(),
        0,
      );
      await screenshot("config-budget-desktop.png");
      await page.goto(`${url}/#/submissions`);
      await page
        .getByRole("heading", { name: "当前提交进度", exact: true })
        .waitFor();
      assert.equal(await page.locator(".submission-rules").count(), 1);
      await page
        .getByRole("heading", { name: "Kaggle 分数历史", exact: true })
        .waitFor();
      await page.locator(".platform-history tbody tr").first().waitFor();
      assert((await page.locator(".platform-history tbody tr").count()) >= 1);
      await screenshot("submissions-desktop.png");
      await page.setViewportSize({ width: 390, height: 844 });
      assert(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
        "Kaggle history must not overflow the mobile page",
      );
      await screenshot("submissions-mobile.png");
      await page.goto(`${url}/#/tasks?task=invsqrt`);
      await page.getByRole("img", { name: /invsqrt 官方成本历史/i }).waitFor();
      assert(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
        "task history must not overflow the mobile page",
      );
      await screenshot("tasks-mobile.png");
      await page.goto(`${url}/#/jobs?id=${job.job_id}`);
      await page.getByRole("heading", { name: "这次任务的状态" }).waitFor();
      assert(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      );
      await screenshot("job-detail-mobile.png");
      await page.goto(`${url}/#/`);
      await page.locator(".candidate-card").first().waitFor();
      assert(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      );
      await screenshot("overview-mobile.png");
      assert.deepEqual(
        writes,
        [],
        "usability review must not write business state",
      );
      assert.deepEqual(errors, [], "no browser runtime exceptions");
    } catch (error) {
      await mkdir("test-results", { recursive: true });
      await page.screenshot({
        path: resolve("test-results/usability-failure.png"),
        fullPage: true,
        animations: "disabled",
      });
      throw error;
    } finally {
      await browser.close();
    }
  },
);
