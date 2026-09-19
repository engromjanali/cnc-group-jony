# R2 CORS - optional, not applied

**You do not need this to add designs.** The backend uploads files to R2
itself, so no browser ever sends a file to R2 and there is nothing for CORS to
block on upload.

It only matters for one case: the **Flutter web app downloading** a design's
cutting file. The app fetches the file from a short-lived signed R2 link. If
the browser blocks that (no CORS rule on the bucket), the app already falls
back to opening the link in a new tab, where the user can save it - so
downloads still work, just less smoothly. Android/iOS are never affected.

`r2-cors.json` allows `GET` from the listed origins so the web download can
stay in-page. **It has not been applied to the bucket.**

## Before applying

1. Replace `https://cncgroupjony.web.app` if that isn't the real deployed
   origin. `http://localhost:55915` was the `flutter run -d chrome` origin when
   this was written - Flutter picks a **random** port each run unless you pin
   one (`flutter run -d chrome --web-port 55915`).
2. `origins` and `methods` are the two fields Cloudflare's docs confirm for
   this file shape. Check the dashboard (R2 -> bucket -> Settings -> CORS
   Policy) or `wrangler r2 bucket cors set --help` before adding anything else
   rather than guessing field names.

## Applying it

```
wrangler r2 bucket cors set cnc --file r2-cors.json
```

or paste the `rules` into the Cloudflare dashboard: **R2 -> cnc -> Settings ->
CORS Policy**.

Never set `origins` to `*` on a private bucket.
