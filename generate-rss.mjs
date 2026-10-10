import fs from 'node:fs';
process.env.TZ='America/Los_Angeles';
const DAY_ORDER=['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];
function addDays(iso,n){const d=new Date(iso+'T12:00:00');d.setDate(d.getDate()+n);return d.toLocaleDateString('en-CA');}
function weekendRange(today) {
  // Sahil's call (Aug 30): weekend = Friday-Sunday, week = Monday-Thursday.
  const dow = new Date(today + "T12:00:00").getDay(); // 0 Sun … 6 Sat
  if (dow === 0) return [today, today];                 // Sunday: today only
  if (dow >= 5) return [today, addDays(today, 7 - dow)]; // Fri→+2, Sat→+1
  return [addDays(today, 5 - dow), addDays(today, 7 - dow)]; // Mon-Thu → this Fri-Sun
}

function monthEndISO(iso) {
  const d = new Date(iso + "T12:00:00");
  const e = new Date(d.getFullYear(), d.getMonth() + 1, 0);
  return `${e.getFullYear()}-${String(e.getMonth() + 1).padStart(2, "0")}-${String(e.getDate()).padStart(2, "0")}`;
}

// "3:00pm – 5:00pm" → 900. Used only for ordering within a day.
function startMinutes(t) {
  const m = /(\d{1,2})(?::(\d{2}))?\s*(am|pm)/i.exec(t || "");
  if (!m) return null;
  let h = Number(m[1]) % 12;
  if (/pm/i.test(m[3])) h += 12;
  return h * 60 + Number(m[2] || 0);
}

// The sheet writes real dates into the notes ("Upcoming: 8/25, 9/29"), which beats
// guessing a pattern. Months more than six back are next year's.
function mdToISO(month, day, today) {
  const y = Number(today.slice(0, 4));
  const cur = Number(today.slice(5, 7));
  const year = month < cur - 6 ? y + 1 : y;
  return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}
function datesIn(text, today) {
  const out = [];
  const re = /(\d{1,2})\/(\d{1,2})/g;
  let m;
  while ((m = re.exec(text || ""))) out.push(mdToISO(Number(m[1]), Number(m[2]), today));
  return out;
}
function upcomingDates(details, today) {
  const m = /upcoming:\s*([^.]*)/i.exec(details || "");
  return m ? datesIn(m[1], today) : [];
}
function skippedDates(details, today) {
  const out = [];
  const re = /skips?\b([^.]*)/gi;
  let m;
  while ((m = re.exec(details || ""))) out.push(...datesIn(m[1], today));
  return out;
}
// "First Saturday, monthly", "Last Tuesday of the month", "Monthly Tuesday (last Tue)"
const ORDINALS = { first: 1, second: 2, third: 3, fourth: 4, last: -1 };
function ordinalDates(when, dayLabel, from, to) {
  const w = (when || "").toLowerCase();
  const ord = Object.keys(ORDINALS).find(k => w.includes(k));
  const dow = DAY_ORDER.indexOf(dayLabel);
  if (!ord || dow < 0) return [];
  const n = ORDINALS[ord];
  const out = [];
  const start = new Date(from + "T12:00:00");
  for (let i = 0; i < 6; i++) {
    const y = start.getFullYear(), mo = start.getMonth() + i;
    let d;
    if (n === -1) {
      d = new Date(y, mo + 1, 0);
      while (d.getDay() !== dow) d.setDate(d.getDate() - 1);
    } else {
      d = new Date(y, mo, 1);
      while (d.getDay() !== dow) d.setDate(d.getDate() + 1);
      d.setDate(d.getDate() + (n - 1) * 7);
      if (d.getMonth() !== ((mo % 12) + 12) % 12) continue;
    }
    const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    if (iso >= from && iso <= to) out.push(iso);
  }
  return out;
}
function weekdayDates(dayLabel, from, to) {
  const out = [];
  const every = /daily|every day/i.test(dayLabel || "");
  const dow = DAY_ORDER.indexOf(dayLabel);
  if (!every && dow < 0) return out;
  for (let iso = from; iso <= to; iso = addDays(iso, 1)) {
    if (every || new Date(iso + "T12:00:00").getDay() === dow) out.push(iso);
  }
  return out;
}

// One calendar: one-off events, weekly rhythm and standing happy hours all become
// dated entries. Nothing is invented — a pattern with no derivable date stays undated
// and is listed separately rather than guessed onto a day.
function dateParts(iso) {
  const d = new Date(iso + "T12:00:00");
  return { day: DAY_ORDER[d.getDay()], month: d.toLocaleDateString("en-US", { month: "short" }), dayNum: d.getDate() };
}
function isFull(e) {
  return /\bfull\b|sold[ -]?out/i.test(e.status || "");
}
function isConfirmed(e) {
  const s = e.status;
  if (s == null || s === "") return true; // older data files carry no status column
  return /confirm/i.test(s) || isFull(e);
}
function buildEntries(data, today, horizon) {
  const dated = [];
  const undated = [];
  const push = (iso, entry) => dated.push({ ...entry, ...dateParts(iso), date: iso, sortKey: `${iso} ${String(startMinutes(entry.time) ?? 9999).padStart(4, "0")}` });

  for (const e of (data.events || [])) {
    if (!isConfirmed(e)) continue;
    if (e.date < today) continue;
    push(e.date, { ...e, kind: "event", baseId: e.id, typeTags: [], whenLabel: "" });
  }

  const hasHH = Array.isArray(data.happyHours) && data.happyHours.length > 0;
  for (const r of (data.recurring || [])) {
    const weekly = r.cadence === "weekly" || /daily/i.test(r.day || "");
    if (weekly && hasHH && /happy hour|drink special/i.test(r.title || "")) continue; // lives on the happy hours tab now
    const base = {
      kind: weekly ? "weekly" : "monthly", baseId: r.id, title: r.title,
      desc: r.desc || "",
      location: r.location || "", address: "", time: r.time || "", start: "",
      tags: r.tags || [], typeTags: [weekly ? "weekly" : "monthly"],
      free: !!r.free, price: "", url: r.url || "",
      source: r.url ? (r.url.split("/")[2] || "").replace("www.", "") : "",
      whenLabel: weekly ? (/daily/i.test(r.day || "") ? "Every day" : `Every ${r.day}`) : (r.when || "Monthly"),
    };
    const listed = upcomingDates(r.details, today).filter(d => d >= today);
    let dates = [];
    if (listed.length) dates = listed;
    else if (weekly) {
      const skip = new Set(skippedDates(r.details, today));
process.env.TZ='America/Los_Angeles';
const DAY_ORDER=['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];
function addDays(iso,n){const d=new Date(iso+'T12:00:00');d.setDate(d.getDate()+n);return d.toLocaleDateString('en-CA');}
function startMinutes(t) {
  const m = /(\d{1,2})(?::(\d{2}))?\s*(am|pm)/i.exec(t || "");
  if (!m) return null;
  let h = Number(m[1]) % 12;
  if (/pm/i.test(m[3])) h += 12;
  return h * 60 + Number(m[2] || 0);
}

function mdToISO(month, day, today) {
  const y = Number(today.slice(0, 4));
  const cur = Number(today.slice(5, 7));
  const year = month < cur - 6 ? y + 1 : y;
  return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}
function datesIn(text, today) {
  const out = [];
  const re = /(\d{1,2})\/(\d{1,2})/g;
  let m;
  while ((m = re.exec(text || ""))) out.push(mdToISO(Number(m[1]), Number(m[2]), today));
  return out;
}
function upcomingDates(details, today) {
  const m = /upcoming:\s*([^.]*)/i.exec(details || "");
  return m ? datesIn(m[1], today) : [];
}
function skippedDates(details, today) {
  const out = [];
  const re = /skips?\b([^.]*)/gi;
  let m;
  while ((m = re.exec(details || ""))) out.push(...datesIn(m[1], today));
  return out;
}
const ORDINALS = { first: 1, second: 2, third: 3, fourth: 4, last: -1 };
function ordinalDates(when, dayLabel, from, to) {
  const w = (when || "").toLowerCase();
  const ord = Object.keys(ORDINALS).find(k => w.includes(k));
  const dow = DAY_ORDER.indexOf(dayLabel);
  if (!ord || dow < 0) return [];
  const n = ORDINALS[ord];
  const out = [];
  const start = new Date(from + "T12:00:00");
  for (let i = 0; i < 6; i++) {
    const y = start.getFullYear(), mo = start.getMonth() + i;
    let d;
    if (n === -1) {
      d = new Date(y, mo + 1, 0);
      while (d.getDay() !== dow) d.setDate(d.getDate() - 1);
    } else {
      d = new Date(y, mo, 1);
      while (d.getDay() !== dow) d.setDate(d.getDate() + 1);
      d.setDate(d.getDate() + (n - 1) * 7);
      if (d.getMonth() !== ((mo % 12) + 12) % 12) continue;
    }
    const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    if (iso >= from && iso <= to) out.push(iso);
  }
  return out;
}
function weekdayDates(dayLabel, from, to) {
  const out = [];
  const every = /daily|every day/i.test(dayLabel || "");
  const dow = DAY_ORDER.indexOf(dayLabel);
  if (!every && dow < 0) return out;
  for (let iso = from; iso <= to; iso = addDays(iso, 1)) {
    if (every || new Date(iso + "T12:00:00").getDay() === dow) out.push(iso);
  }
  return out;
}

function dateParts(iso) {
  const d = new Date(iso + "T12:00:00");
  return { day: DAY_ORDER[d.getDay()], month: d.toLocaleDateString("en-US", { month: "short" }), dayNum: d.getDate() };
}
function isFull(e) {
  return /\bfull\b|sold[ -]?out/i.test(e.status || "");
}
function isConfirmed(e) {
  const s = e.status;
  if (s == null || s === "") return true;
  return /confirm/i.test(s) || isFull(e);
}
function buildEntries(data, today, horizon) {
  const dated = [];
  const undated = [];
  const push = (iso, entry) => dated.push({ ...entry, ...dateParts(iso), date: iso, sortKey: `${iso} ${String(startMinutes(entry.time) ?? 9999).padStart(4, "0")}` });

  for (const e of (data.events || [])) {
    if (!isConfirmed(e)) continue;
    if (e.date < today) continue;
    push(e.date, { ...e, kind: "event", baseId: e.id, typeTags: [], whenLabel: "" });
  }

  const hasHH = Array.isArray(data.happyHours) && data.happyHours.length > 0;
  for (const r of (data.recurring || [])) {
    const weekly = r.cadence === "weekly" || /daily/i.test(r.day || "");
    if (weekly && hasHH && /happy hour|drink special/i.test(r.title || "")) continue;
    const base = {
      kind: weekly ? "weekly" : "monthly", baseId: r.id, title: r.title,
      desc: r.desc || "",
      location: r.location || "", address: "", time: r.time || "", start: "",
      tags: r.tags || [], typeTags: [weekly ? "weekly" : "monthly"],
      free: !!r.free, price: "", url: r.url || "",
      source: r.url ? (r.url.split("/")[2] || "").replace("www.", "") : "",
      whenLabel: weekly ? (/daily/i.test(r.day || "") ? "Every day" : `Every ${r.day}`) : (r.when || "Monthly"),
    };
    const listed = upcomingDates(r.details, today).filter(d => d >= today);
    let dates = [];
    if (listed.length) dates = listed;
    else if (weekly) {
      const skip = new Set(skippedDates(r.details, today));
      dates = weekdayDates(r.day, today, horizon).filter(d => !skip.has(d));
    } else {
      dates = ordinalDates(r.when, r.day, today, horizon);
    }
    if (!dates.length) { undated.push({ ...base, reason: r.when || "no dates published" }); continue; }
    const inst = new Set(r.instanceDates || []);
    for (const iso of dates) { if (inst.has(iso)) continue; push(iso, { ...base, id: `${r.id}@${iso}` }); }
  }

  for (const h of (data.happyHours || [])) {
    const base = {
      kind: "happyhour", baseId: h.id, title: h.venue,
      desc: [h.deal, h.details].filter(Boolean).join("; "),
      location: h.address || "", address: "", time: h.time || "", start: "",
      tags: ["food"], typeTags: ["happyhour"], free: false, price: "",
      url: h.url || "", source: h.source || "", sourceNote: h.sourceNote || "",
      checkedAt: h.checkedAt || "", lastChecked: h.lastChecked || "",
      whenLabel: h.when || "", timePosted: h.timePosted !== false,
    };
    const dates = weekdayDates2(h.dayList, today, horizon);
    if (!dates.length) { undated.push({ ...base, reason: h.time || "days not published" }); continue; }
    for (const iso of dates) push(iso, { ...base, id: `${h.id}@${iso}` });
  }

  dated.sort((a, b) => (a.sortKey < b.sortKey ? -1 : a.sortKey > b.sortKey ? 1 : 0));
  return { dated, undated };
}
function weekdayDates2(dayList, from, to) {
  const set = new Set(dayList || []);
  if (!set.size) return [];
  const out = [];
  for (let iso = from; iso <= to; iso = addDays(iso, 1)) {
    if (set.has(DAY_ORDER[new Date(iso + "T12:00:00").getDay()])) out.push(iso);
  }
  return out;
}
const data=JSON.parse(fs.readFileSync('events.json','utf8'));
const today=new Date().toLocaleDateString('en-CA',{timeZone:'America/Los_Angeles'});
const {dated}=buildEntries(data,today,addDays(today,60));
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&apos;'}[c]));
const now=new Date().toUTCString();
const items=dated.filter(e=>!e.cancelled&&!e.postponed).map(e=>{
 const link='https://noeplacelikehome.io/?utm_source=rss&utm_medium=feed&event='+encodeURIComponent(e.id)+'#event-'+encodeURIComponent(e.id);
 const teaser=[e.date,e.time,e.location,(e.desc||'').slice(0,180)+(e.desc?.length>180?'...':'')].filter(Boolean).join(' | ');
 const pub=new Date(e.checkedAt||data.generatedAt);if(Number.isNaN(+pub))throw Error('Invalid publication date');
 return '<item><title>'+esc(e.title)+'</title><link>'+esc(link)+'</link><guid isPermaLink="false">'+esc('nplh:'+e.id)+'</guid><description>'+esc(teaser)+'</description><pubDate>'+pub.toUTCString()+'</pubDate></item>';
}).join('\n');
fs.writeFileSync('rss.xml','<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom"><channel><title>Noe Place Like Home</title><link>https://noeplacelikehome.io/</link><description>Upcoming Noe Valley events, checked by a neighbor. Tap through for details and reminders.</description><language>en-us</language><lastBuildDate>'+now+'</lastBuildDate><atom:link href="https://noeplacelikehome.io/rss.xml" rel="self" type="application/rss+xml"/>\n'+items+'\n</channel></rss>\n');
console.log('RSS: '+dated.length+' upcoming calendar entries');
