"use strict";
const tabGroups = Array.from(document.querySelectorAll("[data-tabs]"), element => {
  const buttons = Array.from(element.querySelectorAll('[role="tab"]'));
  const panels = Array.from(element.querySelectorAll('[role="tabpanel"]'));
  const group = {
    element, buttons,
    source: element.hasAttribute("data-source-tabs"),
    select(key) {
      buttons.forEach(button => {
        const selected = button.dataset.answer === key;
        button.setAttribute("aria-selected", String(selected));
        button.tabIndex = selected ? 0 : -1;
        document.getElementById(button.getAttribute("aria-controls")).hidden = !selected;
      });
    }
  };
  panels.forEach(panel => panel.hidden = false);
  group.select(buttons[0].dataset.answer);
  element.classList.add("tabs-ready");
  return group;
});

function chooseAnswer(group, key) {
  if (group.source) {
    tabGroups.filter(other => other.source).forEach(other => other.select(key));
    const url = new URL(window.location.href);
    url.searchParams.set("source", key);
    window.history.replaceState(null, "", url);
  } else {
    group.select(key);
  }
}

tabGroups.forEach(group => group.buttons.forEach((button, index) => {
  button.addEventListener("click", () => chooseAnswer(group, button.dataset.answer));
  button.addEventListener("keydown", event => {
    const last = group.buttons.length - 1;
    const next = {
      ArrowRight: (index + 1) % group.buttons.length,
      ArrowLeft: (index + last) % group.buttons.length,
      Home: 0, End: last
    }[event.key];
    if (next === undefined) return;
    event.preventDefault();
    const target = group.buttons[next];
    chooseAnswer(group, target.dataset.answer);
    target.focus();
  });
}));

const requestedSource = new URL(window.location.href).searchParams.get("source");
if (["r16", "png", "practice"].includes(requestedSource)) {
  tabGroups.filter(group => group.source).forEach(group => group.select(requestedSource));
}

function revealAnswer(hash) {
  let target;
  try { target = document.getElementById(decodeURIComponent(hash.slice(1))); }
  catch { return; }
  const panel = target?.closest('[role="tabpanel"]');
  if (!panel) return;
  const group = tabGroups.find(item => item.element.contains(panel));
  const button = group?.buttons.find(item => item.getAttribute("aria-controls") === panel.id);
  if (button) chooseAnswer(group, button.dataset.answer);
}

document.addEventListener("click", event => {
  const link = event.target.closest('a[href^="#"]');
  if (link) revealAnswer(link.getAttribute("href"));
});
window.addEventListener("hashchange", () => revealAnswer(window.location.hash));
revealAnswer(window.location.hash);

document.querySelectorAll(".copy").forEach(button => {
  button.addEventListener("click", async () => {
    const content = button.parentElement.querySelector("code").innerText;
    try {
      await navigator.clipboard.writeText(content);
      button.textContent = "Copied";
      document.getElementById("copy-status").textContent = "Text copied to clipboard.";
      window.setTimeout(() => { button.textContent = "Copy"; }, 2000);
    } catch {
      const range = document.createRange();
      range.selectNodeContents(button.parentElement.querySelector("code"));
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      button.textContent = "Selected";
      document.getElementById("copy-status").textContent = "Text selected. Press Control+C or Command+C to copy.";
      window.setTimeout(() => { button.textContent = "Copy"; }, 2000);
    }
  });
});
