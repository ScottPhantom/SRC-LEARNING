import { defineMorphIcon } from "morphicons/element";
import {
  ArrowLeft, ArrowRight, BookOpen, Check, ClipboardList, Eye, History,
  Plus, RotateCcw, RotateCw, Settings, Sparkles, Zap,
} from "lucide";

defineMorphIcon();

const icons = {
  ArrowLeft, ArrowRight, BookOpen, Check, ClipboardList, Eye, History,
  Plus, RotateCcw, RotateCw, Settings, Sparkles, Zap,
};

function decorate() {
  document.querySelectorAll("morph-icon[data-src-icon]").forEach((element) => {
    if (element.dataset.srcReady) return;
    const selected = icons[element.dataset.srcIcon];
    if (!selected) return;
    element.icon = selected;
    element.reducedMotion = "user";
    element.dataset.srcReady = "true";
  });
  for (const [name, data] of Object.entries(icons)) {
    document.querySelectorAll(`.src-icon-${name} button, button.src-icon-${name}`).forEach((button) => {
      if (button.querySelector("morph-icon")) return;
      const element = document.createElement("morph-icon");
      element.icon = data;
      element.reducedMotion = "user";
      element.setAttribute("aria-hidden", "true");
      button.prepend(element);
    });
  }
  document.querySelectorAll(".src-clock[data-end]").forEach((element) => {
    const remaining = Math.max(0, Number(element.dataset.end) - Math.floor(Date.now() / 1000));
    const label = `⏱ ${String(Math.floor(remaining / 60)).padStart(2, "0")}:${String(remaining % 60).padStart(2, "0")}`;
    if (element.textContent !== label) element.textContent = label;
  });
}

new MutationObserver(decorate).observe(document.documentElement, { childList: true, subtree: true });
decorate();
setInterval(decorate, 1000);
