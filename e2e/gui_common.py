"""Find the operation panel's (lil-gui) controls and folders by their names.

Never by position ("the first select", "the first checkbox"): a control added
above another would silently take its clicks (test_section_annotation.py once
ticked グリッド for 断面's 有効 that way). Names are the Japanese labels, which
the app keeps fixed.

A control inside a closed folder is shown first: its closed folders are
opened (outermost first) and the opening animation (300 ms) is waited out,
so a test does not depend on which folders are open by default. Opening a
folder changes the panel's size: a test that checks a fit opens what it needs
before the fit.

This module is not named test_*.py, so the E2E loops do not run it.
"""
import re


def folder_title(page, name):
    """a folder's title bar, by the folder's exact name"""
    return page.locator(".lil-gui .lil-title", has_text=re.compile("^" + re.escape(name) + "$")).first


def wait_gui_idle(page):
    """until no folder is opening or closing (lil-gui adds lil-transition a frame after the click)"""
    page.evaluate("new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")
    page.wait_for_function("!document.querySelector('.lil-gui.lil-transition')", timeout=5000)


def open_folder(page, name):
    """open a folder (and the folders around it) by its exact name"""
    title = folder_title(page, name)
    if _open_around(title):
        wait_gui_idle(page)


def ctl(page, name):
    """the control whose name starts with `name`, shown (its closed folders opened)"""
    label = page.locator(".lil-name", has_text=re.compile("^" + re.escape(name)))
    control = page.locator(".lil-gui .lil-controller").filter(has=label).first
    if _open_around(control):
        wait_gui_idle(page)
    return control


def _open_around(locator):
    """open the closed folders that hold this element (or are it); how many were opened"""
    return locator.evaluate(
        """el => {
             const closed = []
             for (let g = el.closest('.lil-gui'); g; g = g.parentElement && g.parentElement.closest('.lil-gui')) {
               if (g.classList.contains('lil-closed')) closed.unshift(g)
             }
             for (const g of closed) g.querySelector(':scope > .lil-title').click()
             return closed.length
           }"""
    )


def set_mode(page, label):
    """モード: なし / 計測 / 注記 (the select gives the focus back to the page)"""
    ctl(page, "モード").locator("select").select_option(label)
    page.evaluate("document.activeElement && document.activeElement.blur()")
