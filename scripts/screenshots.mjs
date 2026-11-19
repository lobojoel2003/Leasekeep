// Capture README screenshots from a running Leasekeep with demo data:
//   python manage.py seed_demo --with-users && python manage.py runserver
//   node scripts/screenshots.mjs [base-url] [out-dir] [scale]
import { createRequire } from "node:module";
import { mkdirSync } from "node:fs";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const base = process.argv[2] || "http://127.0.0.1:8000";
const out = process.argv[3] || "docs/screenshots";
const scale = Number(process.argv[4] || 2);
mkdirSync(out, { recursive: true });

const staffPages = [
  ["dashboard", "/dashboard/"],
  ["home-timeline", "/homes/{alder}/"],
  ["formula-price", "/ownerships/{rivera}/formula/"],
  ["homes", "/homes/"],
  ["lease-fees", "/fees/"],
  ["occupancy", "/occupancy/"],
  ["improvement-review", "/improvements/{solar}/"],
  ["refinance-review", "/refinances/{refi}/"],
  ["formulas", "/formulas/"],
  ["board-report", "/reports/board/"],
  ["home-compliance", "/reports/hud-home-compliance/?format=html"],
];
const ownerPages = [
  ["portal-home", "/portal/"],
  ["portal-resale-value", "/portal/resale-value/"],
];

async function login(page, username, password) {
  await page.goto(`${base}/accounts/login/`);
  await page.fill("#id_username", username);
  await page.fill("#id_password", password);
  await Promise.all([page.waitForNavigation(), page.click("button[type=submit]")]);
}

async function ids(page) {
  return page.evaluate(async (b) => {
    const html = await (await fetch(`${b}/homes/?q=Alder`)).text();
    const alder = html.match(/href="\/homes\/(\d+)\/"/)[1];
    const home = await (await fetch(`${b}/homes/${alder}/`)).text();
    const rivera = home.match(/\/ownerships\/(\d+)\/resale\//)[1];
    const imp = await (await fetch(`${b}/improvements/`)).text();
    const solar = imp.match(/href="\/improvements\/(\d+)\/"[^>]*>Rooftop solar/)[1];
    const refis = await (await fetch(`${b}/refinances/`)).text();
    const refi = refis.match(/href="\/refinances\/(\d+)\/"/)[1];
    return { alder, rivera, solar, refi };
  }, base);
}

const browser = await chromium.launch();
const shoot = async (page, name, path, values, height = 0) => {
  const url = base + path.replace(/\{(\w+)\}/g, (_, k) => values[k]);
  const size = page.viewportSize();
  if (height) await page.setViewportSize({ width: size.width, height });
  const res = await page.goto(url);
  if (!res.ok()) throw new Error(`${url} returned ${res.status()}`);
  await page.waitForLoadState("networkidle");
  await page.screenshot({ path: `${out}/${name}.png` });
  if (height) await page.setViewportSize(size);
  console.log(`saved ${out}/${name}.png`);
};

const staff = await browser.newContext({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: scale });
const sp = await staff.newPage();
await login(sp, "staff", "leasekeep-demo");
const values = await ids(sp);
const tall = { "home-timeline": 1500, "formula-price": 1180, "board-report": 1180 };
for (const [name, path] of staffPages) await shoot(sp, name, path, values, tall[name] || 0);

const owner = await browser.newContext({ viewport: { width: 1280, height: 960 }, deviceScaleFactor: scale });
const op = await owner.newPage();
await login(op, "ana.rivera@riverbendclt.example", "leasekeep-demo");
for (const [name, path] of ownerPages) await shoot(op, name, path, values);

const anon = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: scale });
await shoot(await anon.newPage(), "sign-in", "/accounts/login/", values);

const phone = await browser.newContext({ ...require("playwright").devices["iPhone 13"] });
const pp = await phone.newPage();
await login(pp, "ana.rivera@riverbendclt.example", "leasekeep-demo");
await shoot(pp, "portal-mobile", "/portal/", values);

await browser.close();
