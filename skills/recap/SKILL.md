---
name: recap
description: Refresh the workspace's recap page, which shows activity, papers, insights, pins, and the knowledge graph in a browser. Use after any change to the research files, or when the user asks to see what has been done so far.
---

# Recap page

Run from the workspace root. `<skills>` is the folder that contains this skill's base directory.

Run `python <skills>/recap/scripts/recap.py`. It copies the fixed page into `research/recap/` and writes `recap-data.js` beside it from the research files. It prints the page's path.

- **After any change to the research files:** run it in the same turn. Never edit the page or the data file by hand.
- **If the user asks to see it:** give them the full path it printed, and tell them to open it in a browser, not in an editor preview, which blocks the page's scripts.
- **If it warns that the graph can't be shown:** report the reason, and fix the graph with the `graph` skill.
