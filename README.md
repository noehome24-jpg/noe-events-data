# noe-events-data

Public data endpoint for https://noeplacelikehome.io

`events.json` is the published calendar. The site fetches it at runtime, so a verified data
change reaches visitors by pushing this file - no site deploy. Only verified rows are in here:
anything flagged in the master sheet never makes it into this file.

Endpoint: https://raw.githubusercontent.com/noehome24-jpg/noe-events-data/main/events.json
