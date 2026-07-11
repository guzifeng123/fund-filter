async (page) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("http://localhost:3001/funds/000001");
  await page.waitForSelector('nav[aria-label="移动端主导航"]');

  return page.evaluate(() => {
    const nav = document.querySelector('nav[aria-label="移动端主导航"]');
    const current = nav?.querySelector('a[aria-current="page"]');
    if (nav) {
      nav.scrollLeft = 120;
      nav.dispatchEvent(new Event("scroll", { bubbles: true }));
    }

    return {
      ok: current?.textContent?.trim() === "基金筛选"
        && window.sessionStorage.getItem("fund-workbench:mobile-nav-scroll-left") === "120",
      currentText: current?.textContent?.trim() ?? null,
      storedScrollLeft: window.sessionStorage.getItem("fund-workbench:mobile-nav-scroll-left")
    };
  });
}
