"use strict";
export const $ = (id) => document.getElementById(id);
export const formatNumber = (n) => new Intl.NumberFormat("pt-PT").format(n);
export const formatMediaTime = (seconds) => {
  const n = Math.max(0, Math.floor(seconds || 0));
  const parts = [Math.floor(n / 3600), Math.floor(n / 60) % 60, n % 60];
  return (parts[0] ? parts : parts.slice(1))
    .map((n) => String(n).padStart(2, "0"))
    .join(":");
};
let toastTimer;
export function showToast(message) {
  $("toast").textContent = message;
  $("toast").classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $("toast").classList.add("hidden"), 9000);
}
export function createTextElement(tag, className, value) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.textContent = value;
  return node;
}
