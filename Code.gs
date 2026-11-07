/**
 * Reading Group — backend for the invite page.
 * Bound to a Google Sheet (Extensions > Apps Script). See README.md for setup.
 *
 * Flow:
 *  1. Page POSTs registrant -> row added (Status = Pending) + "we got it" email.
 *  2. You set Status to Accepted / Declined / Waitlist in the sheet.
 *  3. Accepted  -> acceptance email; once EVENT_START is set, they're added to the calendar event.
 *     Declined  -> decline email.
 *  4. 48h before the event, Accepted + invited people get a "still coming?" email with one-click links.
 */

const CONFIG = {
  SHEET_ID: '',   // only needed if this script was NOT created from the Sheet's Extensions > Apps Script menu
  SHEET_NAME: 'Registrants',
  GROUP_NAME: 'Reading Group',
  HOST: 'Will Sentance',
  FROM_NAME: 'Reading Group',
  REPLY_TO: 'aceeyahsa@gmail.com',   // replies to any email from the script land here
  // Leave blank until the date is confirmed. ISO with offset, e.g. '2026-12-04T18:30:00-08:00'
  EVENT_START: '',
  EVENT_END: '',                // e.g. '2026-12-04T20:30:00-08:00'
  LOCATION: 'South Park Commons, San Francisco (to be confirmed)',
  MIN_AGE: 13
};

const HEADERS = ['Timestamp','ID','Name','Email','Age','LinkedIn','Other links','Answer','Status',
                 'Notes (private)','Receipt sent','Decision email sent','Calendar invite sent','Reminder sent','Attendance'];

/* ---------- one-time setup: run this once from the editor ---------- */
function setupSheet() {
  const ss = getSS_();
  const sh = ss.getSheetByName(CONFIG.SHEET_NAME) || ss.insertSheet(CONFIG.SHEET_NAME);
  sh.getRange(1, 1, 1, HEADERS.length).setValues([HEADERS]).setFontWeight('bold').setBackground('#E7DFCC');
  sh.setFrozenRows(1);
  const statusCol = HEADERS.indexOf('Status') + 1;
  sh.getRange(2, statusCol, 1000, 1).setDataValidation(
    SpreadsheetApp.newDataValidation().requireValueInList(['Pending','Accepted','Declined','Waitlist'], true).build());
  sh.setColumnWidth(HEADERS.indexOf('Answer') + 1, 420);
  sh.getRange(2, HEADERS.indexOf('Answer') + 1, 1000, 1).setWrap(true);
  sh.hideColumns(HEADERS.indexOf('ID') + 1);

  ScriptApp.getProjectTriggers().forEach(t => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('processQueue').timeBased().everyMinutes(15).create();
  ScriptApp.newTrigger('onSheetEdit').forSpreadsheet(ss).onEdit().create();
}

/* ---------- receive registrations ---------- */
function doPost(e) {
  try {
    const d = JSON.parse(e.postData.contents);
    const age = Number(d.age);
    // Backstop for the under-13 rule: refuse BEFORE touching the sheet. Nothing is stored or emailed.
    if (!Number.isInteger(age) || age < CONFIG.MIN_AGE) return json({ ok: false, reason: 'age' });

    const email = clean(d.email, 200).toLowerCase();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return json({ ok: false, reason: 'email' });

    const lock = LockService.getScriptLock(); lock.waitLock(20000);
    try {
      const sh = sheet();
      // ignore duplicate signups from the same email
      const emails = sh.getRange(2, col('Email'), Math.max(sh.getLastRow() - 1, 1), 1).getValues().flat();
      if (emails.map(String).map(s => s.toLowerCase()).includes(email)) return json({ ok: true, duplicate: true });

      const id = Utilities.getUuid();
      const row = new Array(HEADERS.length).fill('');
      row[col('Timestamp') - 1] = new Date();
      row[col('ID') - 1] = id;
      row[col('Name') - 1] = clean(d.name, 120);
      row[col('Email') - 1] = email;
      row[col('Age') - 1] = age;
      row[col('LinkedIn') - 1] = clean(d.linkedin, 300);
      row[col('Other links') - 1] = clean(d.links, 1200);
      row[col('Answer') - 1] = clean(d.answer, 1500);
      row[col('Status') - 1] = 'Pending';
      sh.appendRow(row);
      const r = sh.getLastRow();
      sendReceipt(row);
      sh.getRange(r, col('Receipt sent')).setValue(new Date());
    } finally { lock.release(); }
    return json({ ok: true });
  } catch (err) {
    return json({ ok: false, reason: 'server' });
  }
}

/* ---------- one-click attendance links from the 48h email ---------- */
function doGet(e) {
  const p = e.parameter || {};
  let msg = 'Sorry, that link didn’t work.';
  if (p.id && (p.action === 'yes' || p.action === 'no')) {
    const sh = sheet(), n = sh.getLastRow() - 1;
    if (n > 0) {
      const ids = sh.getRange(2, col('ID'), n, 1).getValues().flat();
      const i = ids.indexOf(p.id);
      if (i >= 0) {
        sh.getRange(i + 2, col('Attendance')).setValue(p.action === 'yes' ? 'Confirmed' : 'Can’t make it');
        msg = p.action === 'yes' ? 'You’re confirmed. See you there.' : 'Thanks for letting us know — we’ve freed your seat.';
      }
    }
  }
  return HtmlService.createHtmlOutput(
    '<body style="font-family:Georgia,serif;background:#F1EBDD;color:#26231F;display:flex;min-height:90vh;align-items:center;justify-content:center;text-align:center">' +
    '<div><p style="font-size:12px;letter-spacing:.2em;text-transform:uppercase">' + CONFIG.GROUP_NAME + '</p><h1 style="font-weight:500">' + msg + '</h1></div></body>');
}

/* ---------- decisions, calendar, reminders ---------- */
function onSheetEdit(e) {
  if (e && e.range && e.range.getSheet().getName() === CONFIG.SHEET_NAME && e.range.getColumn() === col('Status')) processQueue();
}

function processQueue() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(15000)) return;
  try {
    const sh = sheet(), n = sh.getLastRow() - 1;
    if (n < 1) return;
    const rng = sh.getRange(2, 1, n, HEADERS.length), rows = rng.getValues();
    const start = CONFIG.EVENT_START ? new Date(CONFIG.EVENT_START) : null;
    const end = CONFIG.EVENT_END ? new Date(CONFIG.EVENT_END) : (start ? new Date(start.getTime() + 2 * 3600e3) : null);
    const now = new Date();
    const get = (r, h) => r[col(h) - 1], set = (r, h, v) => { r[col(h) - 1] = v; };

    rows.forEach(r => {
      const status = get(r, 'Status');
      if (!get(r, 'Email')) return;

      if (status === 'Accepted' && !get(r, 'Decision email sent')) {
        sendAccepted(r, start); set(r, 'Decision email sent', now);
      }
      if (status === 'Declined' && !get(r, 'Decision email sent')) {
        sendDeclined(r); set(r, 'Decision email sent', now);
      }
      if (status === 'Waitlist' && !get(r, 'Decision email sent')) {
        sendWaitlist(r); set(r, 'Decision email sent', now);
      }
      // calendar: as soon as a date exists, add every accepted person
      if (status === 'Accepted' && start && !get(r, 'Calendar invite sent')) {
        addToCalendar(get(r, 'Email'), start, end); set(r, 'Calendar invite sent', now);
      }
      // 48h reminder
      if (status === 'Accepted' && start && get(r, 'Calendar invite sent') && !get(r, 'Reminder sent')
          && start > now && (start - now) <= 48 * 3600e3 && get(r, 'Attendance') !== 'Can’t make it') {
        sendReminder(r, start); set(r, 'Reminder sent', now);
      }
    });
    rng.setValues(rows);
  } finally { lock.release(); }
}

function addToCalendar(email, start, end) {
  const props = PropertiesService.getScriptProperties();
  const cal = CalendarApp.getDefaultCalendar();
  let ev = null, id = props.getProperty('EVENT_ID_' + start.getTime());
  if (id) { try { ev = cal.getEventById(id); } catch (x) {} }
  if (!ev) {
    ev = cal.createEvent(CONFIG.GROUP_NAME, start, end, {
      location: CONFIG.LOCATION,
      description: 'Hosted by ' + CONFIG.HOST + '.'
    });
    ev.setGuestsCanSeeGuests(false);   // registrants never see each other
    props.setProperty('EVENT_ID_' + start.getTime(), ev.getId());
  }
  ev.addGuest(email);
}

/* ---------- emails (placeholder copy — we'll write the real letters later) ---------- */
function mail(to, subject, text) {
  const opts = { name: CONFIG.FROM_NAME };
  if (CONFIG.REPLY_TO) opts.replyTo = CONFIG.REPLY_TO;
  MailApp.sendEmail(to, subject, text, opts);
}
const first = r => String(r[col('Name') - 1] || '').split(' ')[0] || 'there';
const whenText = s => s ? Utilities.formatDate(s, Session.getScriptTimeZone(), "EEEE, MMMM d 'at' h:mm a z") : 'to be confirmed';

function sendReceipt(r) {
  mail(r[col('Email') - 1], 'Thank you for submitting — ' + CONFIG.GROUP_NAME,
    'Hi ' + first(r) + ',\n\nThank you for submitting your answers to the ' + CONFIG.GROUP_NAME +
    '. If you’re a fit, we’ll be in touch with more information about the opportunity and the event.\n\n— ' + CONFIG.HOST);
}
function sendAccepted(r, start) {
  mail(r[col('Email') - 1], 'You’re in — ' + CONFIG.GROUP_NAME,
    'Hi ' + first(r) + ',\n\nYou’ve been accepted to the ' + CONFIG.GROUP_NAME + '.\nWhen: ' + whenText(start) +
    '\nWhere: ' + CONFIG.LOCATION + '\n\n' + (start ? 'A calendar invite is on its way.' : 'A calendar invite will follow as soon as the date is confirmed.') +
    '\n\n— ' + CONFIG.HOST);
}
function sendDeclined(r) {   // TODO: final wording
  mail(r[col('Email') - 1], 'Your request — ' + CONFIG.GROUP_NAME,
    'Hi ' + first(r) + ',\n\nThank you for applying. We aren’t able to offer you a seat this time.\n\n— ' + CONFIG.HOST);
}
function sendWaitlist(r) {   // TODO: final wording
  mail(r[col('Email') - 1], 'You’re on the waitlist — ' + CONFIG.GROUP_NAME,
    'Hi ' + first(r) + ',\n\nWe’ve placed you on the waitlist and will write if a seat opens.\n\n— ' + CONFIG.HOST);
}
function sendReminder(r, start) {
  const url = ScriptApp.getService().getUrl(), id = r[col('ID') - 1];
  mail(r[col('Email') - 1], 'Still coming? — ' + CONFIG.GROUP_NAME + ' in 48 hours',
    'Hi ' + first(r) + ',\n\nThe ' + CONFIG.GROUP_NAME + ' meets ' + whenText(start) + ' at ' + CONFIG.LOCATION + '.\n\n' +
    'Still interested? Please confirm your seat:\n' + url + '?action=yes&id=' + id +
    '\n\nCan’t make it? Let us know so we can free the seat:\n' + url + '?action=no&id=' + id + '\n\n— ' + CONFIG.HOST);
}

/* ---------- helpers ---------- */
function getSS_() {
  // Works whether the script is bound to a Sheet or standalone (script.google.com).
  const active = SpreadsheetApp.getActiveSpreadsheet();
  if (active) return active;
  if (!CONFIG.SHEET_ID) throw new Error('Standalone script: paste your Sheet ID into CONFIG.SHEET_ID (the long string in the Sheet URL between /d/ and /edit).');
  return SpreadsheetApp.openById(CONFIG.SHEET_ID);
}
function sheet() { return getSS_().getSheetByName(CONFIG.SHEET_NAME); }
function col(h) { return HEADERS.indexOf(h) + 1; }
function json(o) { return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON); }
// trim, cap length, and defuse spreadsheet formulas (=, +, -, @)
function clean(v, max) {
  let s = String(v == null ? '' : v).trim().slice(0, max);
  return /^[=+\-@]/.test(s) ? "'" + s : s;
}
