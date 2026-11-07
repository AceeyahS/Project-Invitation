# Reading Group invite — setup (about 10 minutes)

**Files:** `index.html` (the page) · `Code.gs` (the Google Sheet backend)

## 1. Make the sheet + script
1. Create a new Google Sheet (name it "Reading Group Registrants").
2. **Extensions → Apps Script**, delete the default code, paste all of `Code.gs`.
3. Edit `CONFIG` at the top (host name, reply-to email). Leave `EVENT_START` blank until the date is confirmed.
4. Pick `setupSheet` in the function dropdown → **Run**. Approve the permissions (Sheets, Gmail send, Calendar).
   This creates the headers, the Status dropdown (Pending / Accepted / Declined / Waitlist) and the triggers.

## 2. Publish the form endpoint
**Deploy → New deployment → Web app** · Execute as: **Me** · Who has access: **Anyone** → Deploy → copy the URL.
Paste it into `CONFIG.endpoint` near the bottom of `index.html`.
(Any time you change `Code.gs`, use Deploy → Manage deployments → Edit → New version.)

## 3. Host the page
Drop `index.html` in your GitHub Pages repo (or Netlify/Vercel). Before then, opening it locally runs in demo mode (endpoint empty, nothing is sent).

## 4. Let your team edit
Share the Sheet with the people who should see/keep the data (Share → Editor). Only they can see registrants. The sheet is the single source of truth.

## Running the group
- Review rows → set **Status**. Accepted/Declined/Waitlist emails go out within seconds (edit trigger) or 15 min.
- When the date is set, fill `EVENT_START` / `EVENT_END` / `LOCATION` in `CONFIG` and save. Everyone already Accepted is added to a calendar event (guest list hidden), and anyone accepted later is added automatically.
- 48 hours before, accepted guests get a "Still coming?" email with one-click Yes / Can't make it links; answers land in the **Attendance** column.
- Email copy for decline / waitlist / reminders is placeholder. We'll write the real letters later.

## Privacy choices built in
- Age is asked first. If it's 12 or under, the rest of the form never appears, fields are wiped, and nothing is sent or saved. The script also refuses under-13 submissions server-side as a backstop.
- Duplicate emails are ignored; spreadsheet formulas in answers are neutralized.
- Gmail's free sending quota is roughly 100 emails/day, which is plenty for a group like this.
- Worth adding a one-line privacy note with a contact address before launch.
