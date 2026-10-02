class DateRangePicker {
  constructor({ startInput, endInput, startTimeInput, endTimeInput, startAtInput, endAtInput, onChange }) {
    this.startInput = startInput;
    this.endInput = endInput;
    this.startTimeInput = startTimeInput;
    this.endTimeInput = endTimeInput;
    this.startAtInput = startAtInput;
    this.endAtInput = endAtInput;
    this.onChange = onChange;
    this.trigger = document.querySelector("#dateRangeButton");
    this.dialog = document.querySelector("#dateRangeDialog");
    this.months = document.querySelector("#calendarMonths");
    this.startButton = document.querySelector("#calendarStart");
    this.endButton = document.querySelector("#calendarEnd");
    this.hint = document.querySelector("#calendarHint");
    this.phase = "start";
    this.hoverDate = null;
    this.resetDates = new Map();
    this.timeControls = {
      start: [document.querySelector("#calendarStartHour"), document.querySelector("#calendarStartMinute")],
      end: [document.querySelector("#calendarEndHour"), document.querySelector("#calendarEndMinute")],
    };
    for (const [side, controls] of Object.entries(this.timeControls)) {
      controls.forEach((control, index) => {
        control.innerHTML = Array.from({ length: index === 0 ? 24 : 60 }, (_, value) => {
          const padded = String(value).padStart(2, "0");
          return `<option value="${padded}">${padded}</option>`;
        }).join("");
        control.addEventListener("change", () => {
          this[`${side}Time`] = controls.map(input => input.value).join(":");
          this.render();
          if (this.start && this.end) this.commit(false);
        });
      });
    }
    this.trigger.addEventListener("click", () => this.open());
    document.querySelector("#calendarClose").addEventListener("click", () => this.close());
    document.querySelector("#calendarReset").addEventListener("click", () => {
      this.start = null;
      this.end = null;
      this.phase = "start";
      this.hoverDate = null;
      this.startTime = "00:00";
      this.endTime = "23:59";
      this.render();
    });
    this.startButton.addEventListener("click", () => { this.phase = "start"; this.render(); });
    this.endButton.addEventListener("click", () => {
      this.phase = this.start ? "end" : "start";
      this.render();
    });
    document.querySelector("#calendarPrevious").addEventListener("click", () => this.moveMonth(-1));
    document.querySelector("#calendarNext").addEventListener("click", () => this.moveMonth(1));
    this.months.addEventListener("click", event => {
      const day = event.target.closest("button[data-date]");
      if (day && !day.disabled) this.select(day.dataset.date);
    });
    this.months.addEventListener("pointerover", event => {
      const day = event.target.closest("button[data-date]");
      if (this.phase !== "end" || !day || day.disabled || day.dataset.date === this.hoverDate) return;
      this.hoverDate = day.dataset.date;
      this.paintRange();
    });
    this.months.addEventListener("pointerleave", () => {
      this.hoverDate = null;
      this.paintRange();
    });
    this.months.addEventListener("keydown", event => this.onDayKey(event));
    this.dialog.addEventListener("click", event => {
      if (event.target !== this.dialog) return;
      const rect = this.dialog.getBoundingClientRect();
      if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) this.close();
    });
    this.dialog.addEventListener("close", () => {
      this.trigger.setAttribute("aria-expanded", "false");
      this.sync();
    });
    window.addEventListener("resize", () => { if (this.dialog.open) this.position(); });
  }

  today() {
    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone: document.body.dataset.timezone,
      year: "numeric", month: "2-digit", day: "2-digit",
    }).formatToParts(new Date());
    const values = Object.fromEntries(parts.map(part => [part.type, part.value]));
    return `${values.year}-${values.month}-${values.day}`;
  }

  setResetEvents(events = []) {
    this.resetDates.clear();
    const today = this.today();
    for (const event of events) {
      if (!this.date(event.date) || event.date > today) continue;
      const minutes = event.window_minutes;
      const window = minutes === 10080 ? "每周额度" : minutes % 60 === 0 ? `${minutes / 60} 小时额度` : `${minutes} 分钟额度`;
      const label = event.limit_id === "codex" ? window : `${event.limit_name || event.limit_id} · ${window}`;
      const labels = this.resetDates.get(event.date) || new Set();
      labels.add(`${label}已重置`);
      this.resetDates.set(event.date, labels);
    }
    if (this.dialog.open) {
      // Updating history must preserve the draft range, hover, and keyboard focus.
      const focusDate = this.months.contains(document.activeElement) ? document.activeElement.dataset.date : null;
      this.render(focusDate);
    }
  }

  date(value) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value || "")) return null;
    const parsed = new Date(`${value}T12:00:00`);
    return Number.isNaN(parsed.getTime()) || this.iso(parsed) !== value ? null : parsed;
  }

  dateTime(value) {
    if (!value || Number.isNaN(new Date(value).getTime())) return null;
    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone: document.body.dataset.timezone, hourCycle: "h23",
      year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit",
    }).formatToParts(new Date(value));
    const fields = Object.fromEntries(parts.map(part => [part.type, part.value]));
    return { date: `${fields.year}-${fields.month}-${fields.day}`, time: `${fields.hour}:${fields.minute}`, clock: `${fields.hour}:${fields.minute}:${fields.second}` };
  }

  iso(date) {
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
  }

  format(value) {
    const date = this.date(value);
    return date ? date.toLocaleDateString("zh-CN", { year: "numeric", month: "short", day: "numeric" }) : "请选择";
  }

  sync() {
    const today = this.today();
    let changed = false;
    for (const [input, fallback] of [[this.startTimeInput, "00:00"], [this.endTimeInput, "23:59"]]) {
      if (!/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(input.value)) {
        input.value = fallback;
        changed = true;
      }
    }
    for (const input of [this.startInput, this.endInput]) {
      if (this.date(input.value) && input.value > today) {
        input.value = today;
        changed = true;
      }
    }
    if (changed && this.startInput.value > this.endInput.value) this.startInput.value = this.endInput.value;
    if (this.startInput.value === this.endInput.value && this.startTimeInput.value > this.endTimeInput.value) {
      this.startTimeInput.value = "00:00";
      this.endTimeInput.value = "23:59";
      changed = true;
    }
    let exactStart = this.dateTime(this.startAtInput.value);
    let exactEnd = this.dateTime(this.endAtInput.value);
    if ((this.startAtInput.value || this.endAtInput.value) && (
      !exactStart || !exactEnd || exactStart.date !== this.startInput.value || exactEnd.date !== this.endInput.value
      || exactStart.time !== this.startTimeInput.value || exactEnd.time !== this.endTimeInput.value
      || new Date(this.startAtInput.value) >= new Date(this.endAtInput.value)
    )) {
      this.startAtInput.value = this.endAtInput.value = "";
      exactStart = exactEnd = null;
      changed = true;
    }
    document.querySelector("#calendarPrecision").hidden = !exactStart;
    const startLabel = `${this.format(this.startInput.value)} ${exactStart?.clock || this.startTimeInput.value}`;
    const endLabel = `${this.format(this.endInput.value)} ${exactEnd?.clock || this.endTimeInput.value}`;
    document.querySelector("#rangeStartLabel").textContent = startLabel;
    document.querySelector("#rangeEndLabel").textContent = endLabel;
    this.trigger.setAttribute("aria-label", `选择日期范围，${startLabel} 至 ${endLabel}`);
    return changed;
  }

  open() {
    if (this.dialog.open) return;
    this.start = this.date(this.startInput.value) ? this.startInput.value : null;
    this.end = this.date(this.endInput.value) ? this.endInput.value : null;
    this.startTime = this.startTimeInput.value;
    this.endTime = this.endTimeInput.value;
    const anchor = this.date(this.today());
    this.month = new Date(anchor.getFullYear(), anchor.getMonth() - 1, 1, 12);
    this.phase = "start";
    this.hoverDate = null;
    this.render();
    this.dialog.showModal();
    this.trigger.setAttribute("aria-expanded", "true");
    this.position();
    this.startButton.focus();
  }

  close() {
    if (!this.dialog.open) return;
    this.dialog.close();
    this.trigger.focus();
  }

  position() {
    const rect = this.trigger.getBoundingClientRect();
    const width = this.dialog.offsetWidth;
    const height = this.dialog.offsetHeight;
    const left = Math.max(12, Math.min(rect.right - width, window.innerWidth - width - 12));
    const top = rect.bottom + height + 20 <= window.innerHeight ? rect.bottom + 8
      : Math.max(12, Math.min(rect.top - height - 8, window.innerHeight - height - 12));
    this.dialog.style.left = `${left}px`;
    this.dialog.style.top = `${top}px`;
  }

  moveMonth(amount) {
    const next = new Date(this.month.getFullYear(), this.month.getMonth() + amount, 1, 12);
    if (this.iso(next) > this.today()) return;
    this.month = next;
    this.hoverDate = null;
    this.render();
    this.position();
  }

  select(value) {
    if (!this.date(value) || value > this.today()) return;
    if (this.phase === "start" || !this.start || value < this.start) {
      this.start = value;
      this.end = null;
      this.phase = "end";
      this.hoverDate = null;
      this.render(value);
      return;
    }
    this.end = value;
    this.commit();
  }

  commit(closeDialog = true) {
    if (!this.start || !this.end || `${this.start}T${this.startTime}` > `${this.end}T${this.endTime}`) {
      this.render();
      return;
    }
    this.startInput.value = this.start;
    this.endInput.value = this.end;
    this.startTimeInput.value = this.startTime;
    this.endTimeInput.value = this.endTime;
    this.startAtInput.value = this.endAtInput.value = "";
    this.sync();
    if (closeDialog) this.close();
    this.onChange({ closePicker: closeDialog });
  }

  render(focusDate = null) {
    const today = this.today();
    const nextMonth = new Date(this.month.getFullYear(), this.month.getMonth() + 1, 1, 12);
    document.querySelector("#calendarNext").disabled = this.iso(nextMonth) > today;
    this.startButton.querySelector("strong").textContent = this.format(this.start);
    this.endButton.querySelector("strong").textContent = this.format(this.end);
    this.startButton.classList.toggle("active", this.phase === "start");
    this.endButton.classList.toggle("active", this.phase === "end");
    this.hint.textContent = this.phase === "start" ? "请选择开始日期" : "请选择结束日期 · 同一天也可选择";
    const invalid = this.start && this.end && `${this.start}T${this.startTime}` > `${this.end}T${this.endTime}`;
    if (invalid) this.hint.textContent = "结束时间不能早于开始时间，请调整日期或时分";
    this.hint.classList.toggle("error-text", Boolean(invalid));
    for (const [side, controls] of Object.entries(this.timeControls)) {
      this[`${side}Time`].split(":").forEach((value, index) => { controls[index].value = value; });
    }
    const weekdays = ["日", "一", "二", "三", "四", "五", "六"];
    const tabDate = focusDate || this.start;
    let hasTabDay = false;
    this.months.innerHTML = [0, 1].map(offset => {
      const first = new Date(this.month.getFullYear(), this.month.getMonth() + offset, 1, 12);
      const year = first.getFullYear();
      const month = first.getMonth();
      const count = new Date(year, month + 1, 0, 12).getDate();
      const leading = first.getDay();
      const days = Array.from({ length: 42 }, (_, index) => {
        const day = index - leading + 1;
        if (day < 1 || day > count) return '<div class="calendar-cell empty" aria-hidden="true"></div>';
        const date = new Date(year, month, day, 12);
        const value = this.iso(date);
        const disabled = value > today;
        const reset = this.resetDates.get(value);
        const resetLabel = reset ? Array.from(reset).join("；") : "";
        const tab = !disabled && value === tabDate;
        hasTabDay ||= tab;
        const label = `${year}年${month + 1}月${day}日，星期${weekdays[date.getDay()]}${disabled ? "，未来日期不可选" : ""}${resetLabel ? `，${resetLabel}` : ""}`;
        return `<div class="calendar-cell" data-cell-date="${value}"><button class="calendar-day${reset ? " quota-reset-day" : ""}" data-date="${value}" aria-label="${this.escape(label)}" ${reset ? `title="${this.escape(resetLabel)}"` : ""} tabindex="${tab ? 0 : -1}" ${disabled ? "disabled" : ""}>${day}</button></div>`;
      }).join("");
      return `<section class="calendar-month" aria-labelledby="calendarMonth${offset}"><h3 id="calendarMonth${offset}">${year}年 ${month + 1}月</h3><div class="calendar-weekdays" aria-hidden="true">${weekdays.map(day => `<span>${day}</span>`).join("")}</div><div class="calendar-days">${days}</div></section>`;
    }).join("");
    if (!hasTabDay) this.months.querySelector("button[data-date]:not(:disabled)").tabIndex = 0;
    this.paintRange();
    if (focusDate) this.months.querySelector(`button[data-date="${focusDate}"]`)?.focus();
  }

  escape(value) {
    return String(value).replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
  }

  paintRange() {
    const end = this.phase === "end" && this.hoverDate >= this.start ? this.hoverDate : this.end;
    this.months.querySelectorAll("[data-cell-date]").forEach(cell => {
      const value = cell.dataset.cellDate;
      const isStart = value === this.start;
      const isEnd = value === end;
      cell.classList.toggle("in-range", Boolean(this.start && end && value >= this.start && value <= end));
      cell.classList.toggle("range-start", isStart);
      cell.classList.toggle("range-end", isEnd);
      cell.classList.toggle("single-day", isStart && (!end || isEnd));
      const button = cell.querySelector("button");
      button.classList.toggle("selected-start", isStart);
      button.classList.toggle("selected-end", isEnd);
      button.setAttribute("aria-pressed", String(isStart || isEnd));
    });
  }

  onDayKey(event) {
    const day = event.target.closest("button[data-date]");
    if (!day) return;
    const date = this.date(day.dataset.date);
    const offsets = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7, Home: -date.getDay(), End: 6 - date.getDay() };
    if (Object.hasOwn(offsets, event.key)) date.setDate(date.getDate() + offsets[event.key]);
    else if (event.key === "PageUp" || event.key === "PageDown") {
      const currentDay = date.getDate();
      date.setDate(1);
      date.setMonth(date.getMonth() + (event.key === "PageUp" ? -1 : 1));
      date.setDate(Math.min(currentDay, new Date(date.getFullYear(), date.getMonth() + 1, 0).getDate()));
    } else return;
    event.preventDefault();
    const value = this.iso(date) > this.today() ? this.today() : this.iso(date);
    if (!this.months.querySelector(`button[data-date="${value}"]`)) {
      const target = this.date(value);
      this.month = new Date(target.getFullYear(), target.getMonth(), 1, 12);
    }
    this.hoverDate = this.phase === "end" ? value : null;
    this.render(value);
  }
}
