"use strict";

// Use the browser's Persian calendar in both directions; date-only values are
// never interpreted in the device's timezone. API/storage remain ISO Gregorian.
(() => {
  const DAY = 86400000;
  const dateParts = new Intl.DateTimeFormat("en-u-ca-persian-nu-latn", {
    calendar: "persian", numberingSystem: "latn", timeZone: "UTC",
    year: "numeric", month: "numeric", day: "numeric",
  });
  const wallParts = new Intl.DateTimeFormat("en-u-ca-gregory-nu-latn", {
    timeZone: "Asia/Tehran", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
  });
  const displayTime = new Intl.DateTimeFormat("fa-IR-u-ca-persian", {
    calendar: "persian", timeZone: "Asia/Tehran", dateStyle: "short", timeStyle: "short",
  });
  const pad = value => String(value).padStart(2, "0");
  const parts = (formatter, value) => Object.fromEntries(formatter.formatToParts(value)
    .filter(p => p.type !== "literal").map(p => [p.type, Number(p.value)]));
  const normalize = value => String(value).trim().replace(/[\u200e\u200f\u061c]/g, "")
    .replace(/[۰-۹]/g, c => String(c.charCodeAt(0) - 1776))
    .replace(/[٠-٩]/g, c => String(c.charCodeAt(0) - 1632));
  const key = p => p.year * 10000 + p.month * 100 + p.day;

  function fromSolar(value) {
    let input = normalize(value);
    if (!input) return null;
    if (/^\d{8}$/.test(input)) input = `${input.slice(0, 4)}/${input.slice(4, 6)}/${input.slice(6)}`;
    const match = /^(\d{4})[/-](\d{1,2})[/-](\d{1,2})$/.exec(input);
    if (!match) throw new Error("تاریخ شمسی را مانند ۱۳۷۰/۰۵/۲۱ وارد کنید.");
    const wanted = {year: Number(match[1]), month: Number(match[2]), day: Number(match[3])};
    if (wanted.year < 1000 || wanted.year > 2999 || wanted.month < 1 || wanted.month > 12 || wanted.day < 1 || wanted.day > 31)
      throw new Error("سال، ماه یا روز شمسی معتبر نیست.");
    let low = Math.floor(Date.UTC(wanted.year + 621, 0, 1) / DAY);
    let high = Math.floor(Date.UTC(wanted.year + 622, 11, 31) / DAY);
    const target = key(wanted);
    while (low <= high) {
      const middle = Math.floor((low + high) / 2);
      const actual = key(parts(dateParts, new Date(middle * DAY)));
      if (actual === target) return new Date(middle * DAY).toISOString().slice(0, 10);
      if (actual < target) low = middle + 1; else high = middle - 1;
    }
    throw new Error("این روز در تقویم شمسی وجود ندارد؛ روز ماه و سال کبیسه را بررسی کنید.");
  }

  function toSolar(value) {
    if (!value) return "";
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) throw new Error("Invalid stored date.");
    const instant = new Date(value + "T00:00:00Z");
    if (!Number.isFinite(instant.getTime()) || instant.toISOString().slice(0, 10) !== value)
      throw new Error("Invalid stored date.");
    const p = parts(dateParts, instant);
    return `${p.year}/${pad(p.month)}/${pad(p.day)}`;
  }

  function fromSolarTime(value) {
    const input = normalize(value);
    const match = /^(\d{4}[/-]\d{1,2}[/-]\d{1,2})[ T]+(\d{1,2}):(\d{2})(?::(\d{2}))?$/.exec(input);
    if (!match) throw new Error("تاریخ و ساعت شمسی را مانند ۱۴۰۵/۰۷/۲۷ ۱۵:۳۰ وارد کنید.");
    const iso = fromSolar(match[1]);
    const h = Number(match[2]), m = Number(match[3]), s = Number(match[4] || 0);
    if (h > 23 || m > 59 || s > 59) throw new Error("ساعت معتبر نیست.");
    const [year, month, day] = iso.split("-").map(Number);
    const target = Date.UTC(year, month - 1, day, h, m, s);
    let guess = target;
    for (let i = 0; i < 4; i++) {
      const p = parts(wallParts, new Date(guess));
      const actual = Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute, p.second);
      if (actual === target) return new Date(guess).toISOString();
      guess += target - actual;
    }
    throw new Error("این ساعت به وقت تهران معتبر نیست.");
  }

  function validate(input) {
    input.setCustomValidity("");
    if (!input.value.trim()) return true;
    try {
      const value = input.hasAttribute("data-solar-datetime") ? fromSolarTime(input.value) : fromSolar(input.value);
      const todayParts = parts(wallParts, new Date());
      const today = `${todayParts.year}-${pad(todayParts.month)}-${pad(todayParts.day)}`;
      if (input.hasAttribute("data-solar-past") && value > today)
        throw new Error("تاریخ نباید در آینده باشد.");
      return true;
    } catch (error) { input.setCustomValidity(error.message); return false; }
  }

  function readDate(input) {
    // Preserve invalid text for dirty-form detection; validation blocks saving.
    return validate(input) ? fromSolar(input.value) : input.value;
  }

  function formatDate(value) {
    if (!value) return "ثبت نشده";
    try { return toSolar(value).replace(/\d/g, c => "۰۱۲۳۴۵۶۷۸۹"[Number(c)]); }
    catch (_) { return "تاریخ نامعتبر"; }
  }

  function formatDateTime(value) {
    if (!value) return "—";
    const instant = new Date(value);
    return Number.isFinite(instant.getTime()) ? displayTime.format(instant) : "—";
  }

  function validateForm(form) {
    let valid = true;
    for (const input of form.querySelectorAll("[data-solar-date], [data-solar-datetime]"))
      if (!input.disabled && !validate(input)) valid = false;
    return valid;
  }

  document.addEventListener("input", event => {
    if (event.target.matches("[data-solar-date], [data-solar-datetime]")) validate(event.target);
  });
  document.addEventListener("submit", event => {
    if (!validateForm(event.target)) {
      event.preventDefault(); event.stopImmediatePropagation(); event.target.reportValidity();
    }
  }, true);

  window.MosSolarDate = Object.freeze({normalize, fromSolar, toSolar, fromSolarTime,
    readDate, formatDate, formatDateTime, validate, validateForm});
})();
