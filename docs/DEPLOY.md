# Live demo on Streamlit Community Cloud

The public demo runs in **sample mode only**: Maya's made-up data from `data/maya/`, the recorded answers in
`demo_answers/`, no keys, no Zetaris, no Meterless Nightshift, and no web search. Run it locally for live Nemotron
answers and Zetaris (README, "Full mode").

## What the hosted demo does differently

`config.HOSTED_DEMO` is on when the app's secrets contain `HOSTED_DEMO = "true"` (Cloud exposes root-level secrets
as environment variables). It is also on automatically when the app runs from Cloud's checkout folder
(`/mount/src/...`), so the demo is safe even if the secret is forgotten. When it is on:

- Sample mode is forced (local files, recorded answers, no AI provider called, online search off).
- One line under the header: "Live demo in sample mode: recorded answers, made-up student data. Run locally for
  live Nemotron and Zetaris."
- "My data" is hidden: nobody can upload a bank file to a shared server.
- Each visitor's changes stay in their own browser session: the meal log, My college, the jobs and estimates they
  add, "What Runway remembers", and the actions they mark done. Nothing is written to a shared file, and a refresh
  starts fresh.
- A disk that can't be written never crashes the app: the change stays in the session.

Locally nothing changes: with no `HOSTED_DEMO`, the app behaves exactly as before.

## Deploy (about 5 minutes)

The repository must be public (or Streamlit must be allowed to read it).

1. Go to https://share.streamlit.io and click **Continue with GitHub**. Sign in as `earg555890` and allow access.
2. Click **Create app** (top right), then choose **Deploy a public app from GitHub** (or "Yup, I have an app").
3. Fill in the form:

   | Field | Type exactly |
   |---|---|
   | Repository | `earg555890/Runway-GenAi-10.27` |
   | Branch | `main` |
   | Main file path | `ui/app.py` |
   | App URL (optional) | `runway-genai` (any free name; it becomes `https://runway-genai.streamlit.app`) |

4. Click **Advanced settings**:
   - **Python version:** `3.12` (tested; 3.13 also works).
   - **Secrets:** paste this one line:

     ```toml
     HOSTED_DEMO = "true"
     ```

   - Click **Save**.
5. Click **Deploy**. The first build installs `requirements.txt` (a few minutes). The app opens on Maya's
   status card: "Your money runs out in 2 weeks, on Mon, Nov 9."
6. Check: the header shows "Sample mode" and the live-demo line; there is no "My data" switch; the suggested
   question "Can I afford a $400 flight home for Thanksgiving if I book it Nov 10?" types out "Yes, if you do 2
   things."
7. Copy the app URL into the README's "Live demo" line and into the submission form.

## Notes

- `requirements.txt` at the repo root is what Cloud installs. JayDeBeApi (Zetaris over JDBC) installs cleanly on
  Linux with Python 3.12 and 3.13, and the app only imports it in Zetaris mode, so sample mode never loads Java.
- `.streamlit/config.toml` (theme, fonts, hidden toolbar) is used by Cloud too.
- Typed questions that have no recorded answer get a plain message explaining that live answers need a local run.
- To update the demo, push to `main`; Cloud redeploys on its own. To restart it, use the app's menu
  (**Manage app** > **Reboot app**).
