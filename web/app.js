const $ = (selector) => document.querySelector(selector);
const views = ["schedule", "substitutions", "homework", "messages", "applications", "dashboard"];
const weekGrid = $("#week-grid");
const timeLabels = $("#time-labels");
const editStoreKey = "schulportal-schedule-edits-v1";
const subjectColors = [
  ["#667eff", "#eff1ff"], ["#f09a6b", "#fff1e9"], ["#43aa8b", "#e7f7f1"],
  ["#aa83dd", "#f4edfc"], ["#e1ad4e", "#fff7e2"], ["#e37f9d", "#fff0f4"],
  ["#54a7c5", "#eaf7fb"], ["#7e9c66", "#eff5e9"],
];
let currentUser = null;
let weekStart = mondayOf(new Date());
let weekDays = [];
let editing = false;
let customDays = readEdits();
let activeView = "schedule";
let toastTimer;

function mondayOf(value) {
  const day = new Date(value);
  day.setHours(0, 0, 0, 0);
  day.setDate(day.getDate() - ((day.getDay() + 6) % 7));
  return day;
}

function nextSchoolDay(value = new Date()) {
  const day = new Date(value);
  day.setHours(0, 0, 0, 0);
  do { day.setDate(day.getDate() + 1); } while (day.getDay() === 0 || day.getDay() === 6);
  return day;
}

function dateKey(value) {
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
}

function readEdits() {
  try {
    const saved = JSON.parse(localStorage.getItem(editStoreKey) || "{}");
    return saved && typeof saved === "object" && !Array.isArray(saved) ? saved : {};
  } catch {
    return {};
  }
}

function saveEdits() {
  localStorage.setItem(editStoreKey, JSON.stringify(customDays));
}

async function request(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    ...options,
    headers: { ...(options.body ? { "Content-Type": "application/json" } : {}), ...options.headers },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status}).`);
  return data;
}

function showToast(message, isError = false) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.toggle("error", isError);
  toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toast.hidden = true; }, 3500);
}

function showError(container, error) {
  container.replaceChildren();
  const note = document.createElement("div");
  note.className = "empty-state";
  note.textContent = error.message || "Something went wrong. Please try again.";
  container.append(note);
}

function setAuthenticated(user) {
  currentUser = user;
  $("#login-view").hidden = Boolean(user);
  $("#app-view").hidden = !user;
  if (user) {
    $("#profile-user").textContent = user.user;
    $("#profile-school").textContent = `School ${user.school}`;
    $("#today-label").textContent = new Intl.DateTimeFormat(undefined, { weekday: "short", month: "short", day: "numeric" }).format(new Date());
    loadWeek();
  }
}

function setView(name) {
  activeView = name;
  document.querySelectorAll(".page-view").forEach((view) => { view.hidden = view.id !== `${name}-view`; });
  document.querySelectorAll(".nav-link").forEach((link) => { link.classList.toggle("active", link.dataset.view === name); });
  $("#breadcrumb-current").textContent = ({
    schedule: "My schedule", substitutions: "Substitutions", homework: "Homework",
    messages: "Messages", applications: "Applications", dashboard: "Portal diagnostics",
  })[name];
  if (name === "substitutions") loadSubstitutions();
  if (name === "homework") loadHomework();
  if (name === "messages") loadApplications(true);
  if (name === "applications") loadApplications(false);
  if (name === "dashboard") loadDashboard();
}

function formatWeek(days) {
  if (!days.length) return "";
  const first = new Date(`${days[0].date}T12:00:00`);
  const last = new Date(`${days[days.length - 1].date}T12:00:00`);
  const monthFormat = new Intl.DateTimeFormat(undefined, { month: "long" });
  const yearFormat = new Intl.DateTimeFormat(undefined, { year: "numeric" });
  if (first.getMonth() === last.getMonth()) return `${monthFormat.format(first)} ${yearFormat.format(first)}`;
  if (first.getFullYear() === last.getFullYear()) {
    return `${monthFormat.format(first)} – ${monthFormat.format(last)} ${yearFormat.format(last)}`;
  }
  return `${monthFormat.format(first)} ${yearFormat.format(first)} – ${monthFormat.format(last)} ${yearFormat.format(last)}`;
}

function lessonTime(lesson) {
  if (lesson.start && lesson.end) return `${lesson.start} – ${lesson.end}`;
  if (lesson.from_hour !== null && lesson.from_hour !== undefined) {
    return lesson.to_hour && lesson.to_hour !== lesson.from_hour
      ? `Period ${lesson.from_hour}–${lesson.to_hour}`
      : `Period ${lesson.from_hour}`;
  }
  return "Time not listed";
}

function minutesOf(value) {
  if (!value || !/^\d{1,2}:\d{2}$/.test(value)) return null;
  const [hours, minutes] = value.split(":").map(Number);
  return hours * 60 + minutes;
}

function colorsFor(name) {
  const value = (name || "Lesson").toLowerCase();
  let hash = 0;
  for (const char of value) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return subjectColors[hash % subjectColors.length];
}

function effectiveLessons(day) {
  return Object.prototype.hasOwnProperty.call(customDays, day.date)
    ? customDays[day.date]
    : day.lessons.map((lesson) => ({ ...lesson, cancelled: false }));
}

function renderSchedule() {
  $("#week-title").textContent = formatWeek(weekDays) || "My schedule";
  const weekNumber = weekDays.find((day) => day.week)?.week;
  $("#week-subtitle").textContent = weekNumber ? `Schulportal · Week ${weekNumber}` : "Monday – Friday";
  const notice = $("#schedule-notice");
  const notices = [];
  if (weekDays[0]?.personal_timetable === false) notices.push("Your personal timetable is not available, so this view uses the full school timetable.");
  if (weekDays[0]?.substitution_error) notices.push(`Substitution updates could not be loaded: ${weekDays[0].substitution_error}`);
  notice.hidden = notices.length === 0;
  notice.textContent = notices.join(" ");

  timeLabels.replaceChildren();
  for (let hour = 7; hour <= 16; hour += 1) {
    const label = document.createElement("span");
    label.className = "time-label";
    label.style.top = `${(hour - 7) * 64}px`;
    label.textContent = `${String(hour).padStart(2, "0")}:00`;
    timeLabels.append(label);
  }

  weekGrid.replaceChildren();
  const today = dateKey(new Date());
  for (const day of weekDays) {
    const column = document.createElement("div");
    column.className = `day-column${day.date === today ? " today" : ""}`;
    const heading = document.createElement("div");
    heading.className = "day-heading";
    const weekday = document.createElement("span");
    weekday.className = "day-name";
    weekday.textContent = new Intl.DateTimeFormat(undefined, { weekday: "short" }).format(new Date(`${day.date}T12:00:00`));
    const number = document.createElement("span");
    number.className = "day-date";
    number.textContent = new Intl.DateTimeFormat(undefined, { day: "numeric" }).format(new Date(`${day.date}T12:00:00`));
    heading.append(weekday, number);
    const body = document.createElement("div");
    body.className = "day-body";
    for (const [index, lesson] of effectiveLessons(day).entries()) {
      body.append(renderLesson(day, lesson, index));
    }
    column.append(heading, body);
    weekGrid.append(column);
  }
}

function renderLesson(day, lesson, index) {
  const card = document.createElement("article");
  card.className = `lesson-card${lesson.cancelled ? " cancelled" : ""}${editing ? " editing" : ""}`;
  const [color, background] = lesson.cancelled ? ["#a5a9b0", "#eceef1"] : colorsFor(lesson.name);
  card.style.setProperty("--lesson-color", color);
  card.style.setProperty("--lesson-bg", background);
  const start = minutesOf(lesson.start);
  const end = minutesOf(lesson.end);
  const fallbackStart = 8 * 60 + Math.max(0, (Number(lesson.hour) || 0) - 1) * 45;
  const top = Math.max(0, (start === null ? fallbackStart : start) - 7 * 60) * (64 / 60);
  const duration = Math.max(40, end !== null && start !== null ? end - start : (Number(lesson.hours) || 1) * 45);
  card.style.top = `${top}px`;
  card.style.height = `${Math.max(46, duration * (64 / 60))}px`;

  const name = document.createElement("span");
  name.className = "lesson-name";
  name.textContent = lesson.name || "Untitled lesson";
  const time = document.createElement("span");
  time.className = "lesson-time";
  time.textContent = lessonTime(lesson);
  card.append(name, time);

  const detail = [lesson.room && `Room ${lesson.room}`, lesson.teacher && `· ${lesson.teacher}`].filter(Boolean).join(" ");
  if (detail) {
    const small = document.createElement("span");
    small.className = "lesson-detail";
    small.textContent = detail;
    card.append(small);
  }
  if (lesson.badge) {
    const badge = document.createElement("span");
    badge.className = "lesson-detail";
    badge.textContent = lesson.badge;
    card.append(badge);
  }
  if (lesson.cancelled) {
    const status = document.createElement("span");
    status.className = "lesson-status";
    status.textContent = "Not taking place";
    card.append(status);
  }
  if (lesson.changes?.length) {
    const change = document.createElement("span");
    change.className = "lesson-detail";
    change.textContent = lesson.changes.map((item) => `${item.Art || "Change"}${item.Hinweis ? `: ${item.Hinweis}` : ""}`).join(" · ");
    card.append(change);
  }
  if (editing) {
    const actions = document.createElement("div");
    actions.className = "lesson-actions";
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "lesson-action";
    cancel.title = lesson.cancelled ? "Mark as taking place" : "Mark not taking place";
    cancel.setAttribute("aria-label", cancel.title);
    cancel.textContent = lesson.cancelled ? "↻" : "×";
    cancel.addEventListener("click", () => updateLesson(day.date, index, "cancel"));
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "lesson-action";
    remove.title = "Delete lesson";
    remove.setAttribute("aria-label", remove.title);
    remove.textContent = "−";
    remove.addEventListener("click", () => updateLesson(day.date, index, "delete"));
    actions.append(cancel, remove);
    card.append(actions);
  }
  return card;
}

function ensureCustomDay(day) {
  if (!Object.prototype.hasOwnProperty.call(customDays, day.date)) {
    customDays[day.date] = day.lessons.map((lesson) => ({ ...lesson, cancelled: false }));
  }
}

function updateLesson(dayDate, index, action) {
  const day = weekDays.find((item) => item.date === dayDate);
  if (!day) return;
  ensureCustomDay(day);
  if (action === "delete") customDays[dayDate].splice(index, 1);
  else customDays[dayDate][index].cancelled = !customDays[dayDate][index].cancelled;
  saveEdits();
  renderSchedule();
  showToast(action === "delete" ? "Lesson removed from your schedule." : "Lesson status updated.");
}

function setEditMode(value) {
  editing = value;
  const button = $("#edit-toggle");
  button.innerHTML = value ? "<span>✓</span> Done editing" : "<span>✎</span> Edit schedule";
  button.classList.toggle("button-primary", value);
  button.classList.toggle("button-secondary", !value);
  $("#add-lesson").hidden = !value;
  renderSchedule();
}

async function loadWeek() {
  $("#week-title").textContent = "Loading your week…";
  $("#jump-date").value = dateKey(weekStart);
  weekGrid.replaceChildren();
  try {
    const data = await request(`/api/week?date=${dateKey(weekStart)}`);
    weekDays = data.days.map((day) => ({
      ...day,
      personal_timetable: data.personal_timetable,
      substitution_error: data.substitution_error,
      week: data.week,
    }));
    renderSchedule();
  } catch (error) {
    weekDays = [];
    $("#week-title").textContent = "Could not load this week";
    showToast(error.message, true);
  }
}

function readableDate(raw) {
  if (!raw) return "Date not provided";
  const parsed = new Date(`${raw}T12:00:00`);
  return Number.isNaN(parsed.valueOf()) ? raw : new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(parsed);
}

async function loadSubstitutions() {
  const container = $("#substitutions-content");
  container.innerHTML = '<div class="loading-state">Loading substitutions…</div>';
  try {
    const { substitutions } = await request("/api/substitutions");
    if (!substitutions.length) {
      container.innerHTML = '<div class="empty-state">No substitutions were found.</div>';
      return;
    }
    const list = document.createElement("div");
    list.className = "data-list";
    for (const item of substitutions) {
      const row = document.createElement("article");
      row.className = "data-row";
      const copy = document.createElement("div");
      const title = document.createElement("h3");
      title.textContent = item.Art || "Substitution";
      const description = document.createElement("p");
      description.textContent = item.Hinweis || item._sprechend || "No additional information.";
      const meta = document.createElement("p");
      meta.className = "data-meta";
      meta.textContent = `${item.Lehrerkuerzel || "Teacher not listed"} · Period ${item.Stunde || "—"}`;
      copy.append(title, description, meta);
      const tag = document.createElement("span");
      tag.className = "data-tag";
      tag.textContent = readableDate(item.Tag_en);
      row.append(copy, tag);
      list.append(row);
    }
    container.replaceChildren(list);
  } catch (error) { showError(container, error); }
}

async function loadHomework() {
  const container = $("#homework-content");
  container.innerHTML = '<div class="loading-state">Loading homework…</div>';
  try {
    const { text } = await request("/api/homework");
    if (!text.trim()) {
      container.innerHTML = '<div class="empty-state">Your “Mein Unterricht” page is empty.</div>';
      return;
    }
    const output = document.createElement("pre");
    output.className = "homework-text";
    output.textContent = text;
    container.replaceChildren(output);
  } catch (error) { showError(container, error); }
}

async function loadApplications(forMessages) {
  const container = forMessages ? $("#message-apps") : $("#applications-content");
  container.innerHTML = '<div class="loading-state">Looking for applications…</div>';
  if (forMessages) $("#message-page").replaceChildren();
  try {
    const { applications } = await request("/api/applications");
    if (!applications.length) {
      container.innerHTML = '<div class="empty-state">No message-related applications were discovered on the portal dashboard.</div>';
      return;
    }
    const list = document.createElement("div");
    list.className = "data-list";
    for (const application of applications) {
      const row = document.createElement("article");
      row.className = "data-row";
      const name = document.createElement("h3");
      name.textContent = application.name || application.url;
      const url = document.createElement("p");
      url.textContent = application.url;
      const copy = document.createElement("div");
      copy.append(name, url);
      row.append(copy);
      if (forMessages) {
        const open = document.createElement("button");
        open.className = "link-button";
        open.type = "button";
        open.textContent = "Explore →";
        open.addEventListener("click", () => openMessage(application.url));
        row.append(open);
      } else {
        const tag = document.createElement("span");
        tag.className = "data-tag";
        tag.textContent = "Message app";
        row.append(tag);
      }
      list.append(row);
    }
    container.replaceChildren(list);
  } catch (error) { showError(container, error); }
}

async function openMessage(url) {
  const target = $("#message-page");
  target.innerHTML = '<div class="loading-state">Opening message page…</div>';
  try {
    const result = await request("/api/messages/open", {
      method: "POST",
      body: JSON.stringify({ url }),
    });
    const title = document.createElement("h3");
    title.textContent = result.title || result.url;
    const content = document.createElement("pre");
    content.className = "message-content";
    content.textContent = result.text || "This page contains no readable text.";
    target.replaceChildren(title, content);
    if (result.links.length) {
      const links = document.createElement("div");
      links.className = "message-links";
      for (const link of result.links) {
        const button = document.createElement("button");
        button.className = "link-button";
        button.type = "button";
        button.textContent = link.name;
        button.addEventListener("click", () => openMessage(link.url));
        links.append(button);
      }
      target.append(links);
    }
    const forms = document.createElement("p");
    forms.className = "form-summary";
    forms.textContent = result.forms.length
      ? `${result.forms.length} form${result.forms.length === 1 ? "" : "s"} found on this page.`
      : "No forms found on this page.";
    target.append(forms);
  } catch (error) { showError(target, error); }
}

async function loadDashboard() {
  const container = $("#dashboard-content");
  container.innerHTML = '<div class="loading-state">Inspecting your dashboard…</div>';
  try {
    const data = await request("/api/dashboard");
    const heading = document.createElement("p");
    heading.className = "data-meta";
    heading.textContent = `Dashboard: ${data.url}`;
    const linksHeading = document.createElement("h3");
    linksHeading.textContent = `Available links (${data.links.length})`;
    const list = document.createElement("div");
    list.className = "data-list";
    for (const item of data.links) {
      const row = document.createElement("article");
      row.className = "data-row";
      const label = document.createElement("strong");
      label.textContent = item.name || "(No label)";
      const url = document.createElement("p");
      url.textContent = item.url;
      const copy = document.createElement("div");
      copy.append(label, url);
      row.append(copy);
      list.append(row);
    }
    const forms = document.createElement("p");
    forms.className = "form-summary";
    forms.textContent = `Forms found: ${data.forms.length}`;
    const formList = document.createElement("div");
    formList.className = "data-list";
    for (const form of data.forms) {
      const row = document.createElement("article");
      row.className = "data-row";
      const copy = document.createElement("div");
      const method = document.createElement("h3");
      method.textContent = form.method;
      const action = document.createElement("p");
      action.textContent = form.action;
      copy.append(method, action);
      row.append(copy);
      formList.append(row);
    }
    container.replaceChildren(heading, linksHeading, list, forms, formList);
  } catch (error) { showError(container, error); }
}

$("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.currentTarget.querySelector("button[type=submit]");
  const errorNote = $("#login-error");
  errorNote.hidden = true;
  button.disabled = true;
  button.textContent = "Connecting…";
  const values = Object.fromEntries(new FormData(event.currentTarget).entries());
  try {
    const user = await request("/api/login", { method: "POST", body: JSON.stringify(values) });
    event.currentTarget.reset();
    setAuthenticated(user);
  } catch (error) {
    errorNote.textContent = error.message;
    errorNote.hidden = false;
  } finally {
    button.disabled = false;
    button.innerHTML = 'Continue to your schedule <span aria-hidden="true">→</span>';
  }
});

document.querySelectorAll("[data-view]").forEach((button) => {
  button.addEventListener("click", () => setView(button.dataset.view));
});
$("#logout-button").addEventListener("click", async () => {
  try { await request("/api/logout", { method: "POST", body: "{}" }); } catch (error) { showToast(error.message, true); }
  setAuthenticated(null);
});
$("#previous-week").addEventListener("click", () => { weekStart.setDate(weekStart.getDate() - 7); loadWeek(); });
$("#next-week").addEventListener("click", () => { weekStart.setDate(weekStart.getDate() + 7); loadWeek(); });
$("#current-week").addEventListener("click", () => { weekStart = mondayOf(new Date()); loadWeek(); });
$("#next-school-day").addEventListener("click", () => { weekStart = mondayOf(nextSchoolDay()); loadWeek(); });
$("#jump-date").addEventListener("change", (event) => {
  if (!event.currentTarget.value) return;
  weekStart = mondayOf(new Date(`${event.currentTarget.value}T12:00:00`));
  loadWeek();
});
$("#edit-toggle").addEventListener("click", () => setEditMode(!editing));
$("#add-lesson").addEventListener("click", () => {
  $("#lesson-form").reset();
  $("#lesson-form").elements.start.value = "08:00";
  $("#lesson-form").elements.end.value = "08:45";
  const dateSelect = $("#lesson-date");
  dateSelect.replaceChildren();
  for (const day of weekDays) {
    const option = document.createElement("option");
    option.value = day.date;
    option.textContent = new Intl.DateTimeFormat(undefined, { weekday: "long", month: "short", day: "numeric" }).format(new Date(`${day.date}T12:00:00`));
    dateSelect.append(option);
  }
  $("#lesson-dialog").showModal();
});
$("#close-dialog").addEventListener("click", () => $("#lesson-dialog").close());
$("#cancel-dialog").addEventListener("click", () => $("#lesson-dialog").close());
$("#lesson-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const data = Object.fromEntries(new FormData(form).entries());
  if (data.end <= data.start) {
    showToast("The end time must be after the start time.", true);
    return;
  }
  const targetDate = data.date;
  const target = weekDays.find((day) => day.date === targetDate);
  if (!target) {
    showToast("Load a week before adding lessons.", true);
    return;
  }
  ensureCustomDay(target);
  customDays[targetDate].push({
    id: `${targetDate}-custom-${Date.now()}`,
    name: data.name.trim(),
    room: data.room.trim(),
    teacher: data.teacher.trim(),
    start: data.start,
    end: data.end,
    from_hour: null,
    to_hour: null,
    hour: Math.max(1, Math.round((minutesOf(data.start) - 8 * 60) / 45) + 1),
    hours: 1,
    cancelled: form.elements.cancelled.checked,
    changes: [],
  });
  customDays[targetDate].sort((a, b) => (minutesOf(a.start) ?? 0) - (minutesOf(b.start) ?? 0));
  saveEdits();
  $("#lesson-dialog").close();
  renderSchedule();
  showToast("Lesson added to your schedule.");
});
document.querySelectorAll(".refresh-button").forEach((button) => {
  button.addEventListener("click", () => setView(activeView));
});

request("/api/session").then((session) => {
  setAuthenticated(session.authenticated ? session : null);
}).catch(() => setAuthenticated(null));
