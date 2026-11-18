# Answer-key requests (Shaurya sends; never auto-sent)

Why: the blind test (18 Nov 2026, `attribution/validation/BLIND_REPORT.md`) showed Kaun's local source
calls agree with no independent witness. To reach a measured 95% we need hourly, instrument-measured
source shares for Delhi. Two places may have them: the Delhi govt real-time source apportionment
supersite at Rouse Avenue (IIT Kanpur consortium, launched 30 Jan 2023) and IIT Delhi researchers.

Fill the `[...]` before sending. Verify the email address on the official faculty page first.

---

## 1. Email to Dr Shahzad Gani (IIT Delhi)

This one is also a mentorship, internship and recommendation-letter opening, so it is written to show
three things a researcher looks for in a student: real work already done, honesty about a negative
result, and a small, concrete ask that is easy to say yes to. Keep it this short; do not add adjectives.

Before sending:
- Verify the address and current affiliation on the official IIT Delhi faculty page.
- Verify the paper title in the second paragraph against Google Scholar; change it if it is wrong.
- Attach `kaun_blind_test.pdf` (one page: what Kaun does, the blind-test table, what you plan next).
  Export it from `attribution/validation/BLIND_REPORT.md` plus a 5-line method summary.
- Fill `[...]`. Send from your personal email, Tuesday to Thursday morning.
- No reply in 10 days: one short follow-up in the same thread with any new result. Never a third.

**To:** [verified address]
**Subject:** Class [..] student: my Delhi source-attribution model failed its blind test. Could I learn to fix it with you?

Dear Dr Gani,

I am Shaurya Vardhan Shandilya, a Class [..] student at [school], Delhi. Over the past month I built
Kaun, a system that runs every hour on all 54 CPCB and DPCC stations in Delhi NCR and tries to say what
caused each PM2.5 spike. It separates the region-wide part of a spike (from the city-wide background,
wind and mixing height) from the local part, then names a likely local source from pollutant ratios,
NO freshness, humidity, factor analysis, wind sector and an OpenStreetMap inventory of nearby sites.

Last week I tested it blind. On 161 real spikes from 12 to 18 November, I switched off the map, clock
and fire inputs and compared the chemistry-only calls with evidence they never saw: satellite fires,
time of day, land use, and pairs of stations under 3 km apart. It failed every check. Neighbouring
stations agreed only 34% of the time, no better than chance. The region-wide part holds up because it
is measured; the local source label does not. I came to your work through this problem: your Delhi
Aerosol Supersite study ("Submicron aerosol composition in the world's most polluted megacity",
ACP 2019) is the kind of measured ground truth that station data alone cannot replace.

I would like to fix this properly rather than tune it on guesses, and I would like to learn how from
someone who measures these sources directly. Three requests, smallest first:

1. Could you point me to any hourly speciated or source-apportioned Delhi data I could use for
   validation, from your campaigns or the Rouse Avenue supersite? I would tune on part of it and report
   results only on held-out data.
2. Could I have 15 minutes of your critique of the method, at your convenience? A one-page summary
   is attached.
3. If your group takes school students, I would be glad to work under your guidance in summer 2027,
   on this or on whatever you think would teach me most.

Thank you for reading this.

Shaurya Vardhan Shandilya
Class [..], [school], Delhi
[phone]
[link to a public page about Kaun, if one exists by then]

---

## 2. RTI application to DPCC (Delhi Pollution Control Committee)

**File at:** the Delhi govt RTI online portal (verify the URL on delhi.gov.in), or by post to the
Public Information Officer, DPCC, 4th Floor, ISBT Building, Kashmere Gate, Delhi 110006 (verify the address on
dpcc.delhigovt.nic.in). Fee: Rs 10.

**Subject:** Information on the Real-Time Source Apportionment Supersite, Rouse Avenue

Under the Right to Information Act, 2005, please provide:

1. The hourly source-wise PM2.5 (and PM10, if available) contributions produced by the Real-Time Source
   Apportionment Supersite at Sarvodaya Bal Vidyalaya, Rouse Avenue, from its launch on 30 January 2023
   to the date of reply, in machine-readable form (CSV or Excel), with the list of source categories.
2. The hourly chemical speciation measured at the supersite over the same period (elements, ions,
   organic and elemental carbon, and any VOCs such as benzene and toluene), in machine-readable form.
3. The same hourly source-wise contributions from the mobile monitoring van, with its location per day.
4. Whether the supersite is operating today. If it has stopped, the date it stopped and the reason
   recorded in DPCC's files.
5. Copies of all project reports submitted by the IIT Kanpur-led consortium after the September 2023
   winter report.

I am a citizen of India. Please provide the information in electronic form by email to
[your email].

[Name, address, date]
